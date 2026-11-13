"""BE-165 : file de lettres mortes et reprise manuelle tracée.

Tests écrits d'après la définition `### BE-165` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : un échec définitif après épuisement des tentatives est déplacé en lettre morte ;
- CA-2 : une reprise sans motif est refusée (422) ; avec motif, elle écrit `operateur`,
  `motif` et `originalId`, relance l'effet une fois et journalise l'action ;
- CA-3 : une reprise sans `integrations.manage` renvoie 403 et ne relance rien ;
- CA-4 : une reprise rejouée sur une lettre déjà reprise renvoie `REPLAY_DUPLICATE` (409)
  et ne relance rien une seconde fois ;
- CA-5 : un opérateur du tenant A ne peut pas reprendre ni lire une lettre du tenant B (404 ;
  la lecture ne renvoie que les lettres du tenant demandé).

Les routes sont couvertes par un test de montage (401 sans session, jamais 404).
Les permissions sont portées par des rôles de test créés pour chaque cas (pas de montage
massif de fixtures).
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.audit.ecriture import IdentiteEmettrice
from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.identity.models import Organization, User
from app.integrations.lettres_mortes import (
    deplacer_en_lettre_morte,
    lister_lettres_mortes,
    reprendre_lettre_morte,
)
from app.integrations.models import Connecteur, LettreMorte, TentativeIntegration
from app.integrations.tentatives import ErreurDefinitive, ErreurTransitoire, PolitiqueBackoff, executer_effet
from app.rbac.models import Permission, Role, RolePermission, UserRole

LIRE = "integrations.read"
GERER = "integrations.manage"
MAINTENANT = datetime(2026, 11, 5, 10, 0, 0, tzinfo=timezone.utc)
POLITIQUE = PolitiqueBackoff(base_secondes=10, plafond_secondes=100)
ACTION_REPRISE = "integration.lettre_morte.reprendre"


class _Relance:
    """Relance factice : compte les appels, peut lever une erreur."""

    def __init__(self) -> None:
        self.appels: list[uuid.UUID] = []

    async def __call__(self, lettre: LettreMorte) -> None:
        self.appels.append(lettre.id)


async def _utilisateur(registered_user: dict) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        return user.id


async def _autre_organisation() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="Tenant B BE-165", slug=f"be165-b-{uuid.uuid4().hex[:10]}")
        db.add(organisation)
        await db.flush()
        org_id = organisation.id
        await db.commit()
    return org_id


async def _accorder(user_id: uuid.UUID, org_id: uuid.UUID, codes: list[str]) -> None:
    """Attribue à l'utilisateur un rôle de test portant `codes` dans `org_id`."""
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=org_id, code=f"be165-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-165")
        db.add(role)
        await db.flush()
        for code in codes:
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(code=code, moduleCode="integrations", description="Permission de test BE-165")
                db.add(permission)
                await db.flush()
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        db.add(UserRole(userId=user_id, organizationId=org_id, roleId=role.id))
        await db.commit()


async def _connecteur(org_id: uuid.UUID) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        connecteur = Connecteur(portee="tenant", organizationId=org_id, nom=f"be165-{uuid.uuid4().hex[:8]}", etat="activé")
        db.add(connecteur)
        await db.flush()
        connecteur_id = connecteur.id
        await db.commit()
    return connecteur_id


async def _echec_definitif(connecteur_id: uuid.UUID, org_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Produit un échec définitif réel via `executer_effet` ; rend (tentativeId, eventId)."""
    event_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:

        async def effet() -> None:
            raise ErreurDefinitive("REFUS_METIER")

        ligne = await executer_effet(
            db,
            connecteur_id=connecteur_id,
            organization_id=org_id,
            correlation_id=uuid.uuid4(),
            event_id=event_id,
            effet=effet,
            politique=POLITIQUE,
            maintenant=MAINTENANT,
            tentative_no=3,
        )
        await db.commit()
        return ligne.id, event_id


async def _lettre_de_test(org_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Crée une lettre morte réelle ; rend (lettreId, eventId)."""
    connecteur_id = await _connecteur(org_id)
    tentative_id, event_id = await _echec_definitif(connecteur_id, org_id)
    async with AsyncSessionLocal() as db:
        lettre = await deplacer_en_lettre_morte(db, tentative_id=tentative_id, organization_id=org_id)
        await db.commit()
        return lettre.id, event_id


async def _reprendre(identite, org_id, lettre_id, motif, relance):
    async with AsyncSessionLocal() as db:
        resultat = await reprendre_lettre_morte(
            db,
            identite=identite,
            organization_id=org_id,
            lettre_id=lettre_id,
            motif=motif,
            relance=relance,
        )
        await db.commit()
        return resultat


async def _lettre(lettre_id: uuid.UUID) -> LettreMorte:
    async with AsyncSessionLocal() as db:
        return await db.get(LettreMorte, lettre_id)


async def test_be165_ca1_echec_definitif_part_en_lettre_morte(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    connecteur_id = await _connecteur(org_id)
    tentative_id, event_id = await _echec_definitif(connecteur_id, org_id)

    async with AsyncSessionLocal() as db:
        lettre = await deplacer_en_lettre_morte(db, tentative_id=tentative_id, organization_id=org_id)
        await db.commit()
        lettre_id = lettre.id

    lue = await _lettre(lettre_id)
    assert lue.tentativeId == tentative_id
    assert lue.originalId == event_id
    assert lue.organizationId == org_id
    assert lue.motif is None
    assert lue.operateur is None
    assert lue.reprisAt is None


async def test_be165_ca1_tentative_non_definitive_refusee(registered_user, organization):
    """Une tentative qui peut encore être reprise (backoff planifié) n'est pas une lettre morte."""
    org_id = uuid.UUID(organization["id"])
    connecteur_id = await _connecteur(org_id)
    event_id = uuid.uuid4()

    async def effet() -> None:
        raise ErreurTransitoire("TIMEOUT_FOURNISSEUR")

    async with AsyncSessionLocal() as db:
        ligne = await executer_effet(
            db,
            connecteur_id=connecteur_id,
            organization_id=org_id,
            correlation_id=uuid.uuid4(),
            event_id=event_id,
            effet=effet,
            politique=POLITIQUE,
            maintenant=MAINTENANT,
            tentative_no=1,
        )
        await db.commit()
        tentative_id = ligne.id

    async with AsyncSessionLocal() as db:
        with pytest.raises(ValueError):
            await deplacer_en_lettre_morte(db, tentative_id=tentative_id, organization_id=org_id)


async def test_be165_ca2_reprise_sans_motif_renvoie_422(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_id, [LIRE, GERER])
    lettre_id, _ = await _lettre_de_test(org_id)
    relance = _Relance()
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)

    for motif in (None, "", "   "):
        with pytest.raises(ErreurCatalogue) as erreur:
            await _reprendre(identite, org_id, lettre_id, motif, relance)
        assert erreur.value.code == CodeErreur.SCHEMA_INVALID
        assert erreur.value.status_code == 422

    assert relance.appels == []
    lue = await _lettre(lettre_id)
    assert lue.reprisAt is None


async def test_be165_ca2_reprise_avec_motif_ecrit_et_journalise(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_id, [LIRE, GERER])
    lettre_id, event_id = await _lettre_de_test(org_id)
    relance = _Relance()
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)

    await _reprendre(identite, org_id, lettre_id, "Fournisseur rétabli, relance validée", relance)

    lue = await _lettre(lettre_id)
    assert lue.operateur == user_id
    assert lue.motif == "Fournisseur rétabli, relance validée"
    assert lue.originalId == event_id
    assert lue.reprisAt is not None
    assert relance.appels == [lettre_id]

    async with AsyncSessionLocal() as db:
        journal = await db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == ACTION_REPRISE, AuditEvent.entityId == lettre_id, AuditEvent.actorUserId == user_id)
        )
    assert journal == 1


async def test_be165_ca3_reprise_sans_permission_renvoie_403_sans_relance(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_id, [LIRE])  # lecture seule : pas integrations.manage
    lettre_id, _ = await _lettre_de_test(org_id)
    relance = _Relance()
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)

    with pytest.raises(ErreurCatalogue) as erreur:
        await _reprendre(identite, org_id, lettre_id, "Motif valable", relance)

    assert erreur.value.code == CodeErreur.PERMISSION_DENIED
    assert erreur.value.status_code == 403
    assert relance.appels == []
    lue = await _lettre(lettre_id)
    assert lue.reprisAt is None
    assert lue.operateur is None


async def test_be165_ca4_reprise_rejouee_renvoie_replay_duplicate(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_id, [LIRE, GERER])
    lettre_id, _ = await _lettre_de_test(org_id)
    relance = _Relance()
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)

    await _reprendre(identite, org_id, lettre_id, "Premier passage", relance)
    with pytest.raises(ErreurCatalogue) as erreur:
        await _reprendre(identite, org_id, lettre_id, "Second passage", relance)

    assert erreur.value.code == CodeErreur.REPLAY_DUPLICATE
    assert erreur.value.status_code == 409
    assert relance.appels == [lettre_id]
    lue = await _lettre(lettre_id)
    assert lue.motif == "Premier passage"


async def test_be165_ca5_lettre_d_un_autre_tenant_renvoie_404(registered_user, organization):
    org_a = uuid.UUID(organization["id"])
    org_b = await _autre_organisation()
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_a, [LIRE, GERER])
    lettre_b, _ = await _lettre_de_test(org_b)
    relance = _Relance()
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_a)

    with pytest.raises(ErreurCatalogue) as erreur:
        await _reprendre(identite, org_a, lettre_b, "Tentative inter-tenant", relance)

    assert erreur.value.code == CodeErreur.TENANT_MISMATCH
    assert erreur.value.status_code == 404
    assert relance.appels == []
    lue = await _lettre(lettre_b)
    assert lue.reprisAt is None


async def test_be165_ca5_liste_limitee_au_tenant(registered_user, organization):
    org_a = uuid.UUID(organization["id"])
    org_b = await _autre_organisation()
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_a, [LIRE])
    lettre_a, _ = await _lettre_de_test(org_a)
    lettre_b, _ = await _lettre_de_test(org_b)
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_a)

    async with AsyncSessionLocal() as db:
        lettres = await lister_lettres_mortes(db, identite, org_a)
    ids = {lettre.id for lettre in lettres}
    assert lettre_a in ids
    assert lettre_b not in ids


async def test_be165_lecture_sans_integrations_read_renvoie_403(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    user_id = await _utilisateur(registered_user)  # aucun rôle attribué
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)

    async with AsyncSessionLocal() as db:
        with pytest.raises(ErreurCatalogue) as erreur:
            await lister_lettres_mortes(db, identite, org_id)
    assert erreur.value.code == CodeErreur.PERMISSION_DENIED
    assert erreur.value.status_code == 403


async def test_be165_routes_montees(client):
    """Les deux routes existent : sans session, elles répondent 401 et jamais 404."""
    liste = await client.get("/api/v1/integrations/lettres-mortes")
    reprise = await client.post(
        f"/api/v1/integrations/lettres-mortes/{uuid.uuid4()}/reprises", json={"motif": "Motif"}
    )
    assert liste.status_code == 401
    assert reprise.status_code == 401
