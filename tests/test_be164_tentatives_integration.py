"""BE-164 : journal des tentatives d'intégration et backoff.

Tests écrits d'après la définition `### BE-164` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : chaque tentative écrit une ligne avec code, durée mesurée et corrélation, sans payload ;
- CA-2 : un échec transitoire planifie une tentative suivante avec backoff croissant plafonné ;
  base et plafond sont lus de la configuration, sans défaut codé (QE-PAR-09) ;
- CA-3 : une même clé d'effet (connecteur, événement) exécutée deux fois produit un seul effet ;
- CA-4 : un opérateur sans `integrations.read` ne voit aucune tentative (403 PERMISSION_DENIED) ;
- CA-5 : les tentatives du tenant A ne sont jamais listées pour le tenant B.

Les routes n'existent pas dans BE-164 (« Routes : aucune ») : ces tests appellent le service.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.audit.ecriture import IdentiteEmettrice
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import Organization, User
from app.integrations.models import Connecteur, TentativeIntegration
from app.integrations.tentatives import (
    ConfigurationBackoffAbsente,
    ErreurDefinitive,
    ErreurTransitoire,
    PolitiqueBackoff,
    delai_backoff,
    executer_effet,
    lire_politique_backoff,
    lister_tentatives,
)
from app.rbac.models import Permission, Role, RolePermission, UserRole

PERMISSION_LIRE = "integrations.read"
MAINTENANT = datetime(2026, 11, 5, 10, 0, 0, tzinfo=timezone.utc)
POLITIQUE = PolitiqueBackoff(base_secondes=10, plafond_secondes=100)


class _Effet:
    """Effet externe factice : compte ses appels et peut lever une erreur."""

    def __init__(self, erreur: Exception | None = None) -> None:
        self.appels = 0
        self.erreur = erreur

    async def __call__(self) -> None:
        self.appels += 1
        if self.erreur is not None:
            raise self.erreur


async def _utilisateur(registered_user: dict) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        return user.id


async def _autre_organisation() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="Tenant B BE-164", slug=f"be164-b-{uuid.uuid4().hex[:10]}")
        db.add(organisation)
        await db.flush()
        org_id = organisation.id
        await db.commit()
    return org_id


async def _connecteur(org_id: uuid.UUID) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        connecteur = Connecteur(portee="tenant", organizationId=org_id, nom=f"be164-{uuid.uuid4().hex[:8]}", etat="activé")
        db.add(connecteur)
        await db.flush()
        connecteur_id = connecteur.id
        await db.commit()
    return connecteur_id


async def _accorder(user_id: uuid.UUID, org_id: uuid.UUID, codes: list[str]) -> None:
    """Attribue à l'utilisateur un rôle de test contenant `codes` dans `org_id`."""
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=org_id, code=f"be164-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-164")
        db.add(role)
        await db.flush()
        for code in codes:
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(code=code, moduleCode="integrations", description="Permission de test BE-164")
                db.add(permission)
                await db.flush()
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        db.add(UserRole(userId=user_id, organizationId=org_id, roleId=role.id))
        await db.commit()


async def _executer(connecteur_id, org_id, event_id, effet, **surcharges):
    async with AsyncSessionLocal() as db:
        parametres = {
            "connecteur_id": connecteur_id,
            "organization_id": org_id,
            "correlation_id": uuid.uuid4(),
            "event_id": event_id,
            "effet": effet,
            "politique": POLITIQUE,
            "maintenant": MAINTENANT,
            "tentative_no": 1,
            **surcharges,
        }
        ligne = await executer_effet(db, **parametres)
        await db.commit()
        return ligne.id


async def test_be164_ca1_chaque_tentative_ecrit_une_ligne_sans_payload(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    connecteur_id = await _connecteur(org_id)
    event_id = uuid.uuid4()
    correlation = uuid.uuid4()

    async with AsyncSessionLocal() as db:
        ligne = await executer_effet(
            db,
            connecteur_id=connecteur_id,
            organization_id=org_id,
            correlation_id=correlation,
            event_id=event_id,
            effet=_Effet(),
            politique=POLITIQUE,
            maintenant=MAINTENANT,
            tentative_no=1,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(
                select(TentativeIntegration).where(
                    TentativeIntegration.connecteurId == connecteur_id, TentativeIntegration.eventId == event_id
                )
            )
        ).scalars().all()
    assert len(lignes) == 1
    tentative = lignes[0]
    assert tentative.id == ligne.id
    assert tentative.issue == "succes"
    assert tentative.codeErreur is None
    assert tentative.correlationId == correlation
    assert isinstance(tentative.dureeMs, int) and tentative.dureeMs >= 0
    assert tentative.tentativeNo == 1
    assert tentative.prochaineTentativeAt is None

    colonnes = {colonne.name for colonne in TentativeIntegration.__table__.columns}
    assert colonnes == {
        "id",
        "connecteurId",
        "correlationId",
        "eventId",
        "issue",
        "codeErreur",
        "dureeMs",
        "tentativeNo",
        "prochaineTentativeAt",
        "organizationId",
        "createdAt",
        "updatedAt",
    }


async def test_be164_ca1_echec_ecrit_le_code_erreur(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    connecteur_id = await _connecteur(org_id)
    event_id = uuid.uuid4()

    await _executer(connecteur_id, org_id, event_id, _Effet(ErreurTransitoire("TIMEOUT_FOURNISSEUR")))

    async with AsyncSessionLocal() as db:
        tentative = await db.scalar(
            select(TentativeIntegration).where(
                TentativeIntegration.connecteurId == connecteur_id, TentativeIntegration.eventId == event_id
            )
        )
    assert tentative.issue == "echec"
    assert tentative.codeErreur == "TIMEOUT_FOURNISSEUR"
    assert isinstance(tentative.dureeMs, int) and tentative.dureeMs >= 0


def test_be164_ca2_delai_croissant_puis_plafonne():
    delais = [delai_backoff(n, POLITIQUE) for n in range(1, 7)]
    assert delais == [10, 20, 40, 80, 100, 100]


def test_be164_ca2_base_et_plafond_lus_de_la_configuration(monkeypatch):
    monkeypatch.setattr(settings, "INTEGRATION_BACKOFF_BASE_SECONDS", 10, raising=False)
    monkeypatch.setattr(settings, "INTEGRATION_BACKOFF_CAP_SECONDS", 100, raising=False)
    assert lire_politique_backoff() == PolitiqueBackoff(base_secondes=10, plafond_secondes=100)


def test_be164_ca2_configuration_absente_refusee_sans_defaut_code(monkeypatch):
    monkeypatch.setattr(settings, "INTEGRATION_BACKOFF_BASE_SECONDS", None, raising=False)
    monkeypatch.setattr(settings, "INTEGRATION_BACKOFF_CAP_SECONDS", 100, raising=False)
    with pytest.raises(ConfigurationBackoffAbsente):
        lire_politique_backoff()


async def test_be164_ca2_echec_transitoire_planifie_la_tentative_suivante(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    connecteur_id = await _connecteur(org_id)
    event_id = uuid.uuid4()

    await _executer(
        connecteur_id, org_id, event_id, _Effet(ErreurTransitoire("HTTP_503")), tentative_no=3
    )

    async with AsyncSessionLocal() as db:
        tentative = await db.scalar(
            select(TentativeIntegration).where(
                TentativeIntegration.connecteurId == connecteur_id, TentativeIntegration.eventId == event_id
            )
        )
    assert tentative.tentativeNo == 3
    # Tentative 3 : base 10 s x 2^(3-1) = 40 s après MAINTENANT (10:00:00).
    assert tentative.prochaineTentativeAt == datetime(2026, 11, 5, 10, 0, 40, tzinfo=timezone.utc)


async def test_be164_ca2_echec_definitif_ne_planifie_rien(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    connecteur_id = await _connecteur(org_id)
    event_id = uuid.uuid4()

    await _executer(connecteur_id, org_id, event_id, _Effet(ErreurDefinitive("REFUS_400")))

    async with AsyncSessionLocal() as db:
        tentative = await db.scalar(
            select(TentativeIntegration).where(
                TentativeIntegration.connecteurId == connecteur_id, TentativeIntegration.eventId == event_id
            )
        )
    assert tentative.issue == "echec"
    assert tentative.prochaineTentativeAt is None


async def test_be164_ca3_meme_cle_executee_deux_fois_produit_un_seul_effet(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    connecteur_id = await _connecteur(org_id)
    event_id = uuid.uuid4()
    effet = _Effet()

    premiere = await _executer(connecteur_id, org_id, event_id, effet)
    seconde = await _executer(connecteur_id, org_id, event_id, effet)

    assert effet.appels == 1
    assert premiere == seconde
    async with AsyncSessionLocal() as db:
        nombre = await db.scalar(
            select(func.count())
            .select_from(TentativeIntegration)
            .where(
                TentativeIntegration.connecteurId == connecteur_id,
                TentativeIntegration.eventId == event_id,
                TentativeIntegration.issue == "succes",
            )
        )
    assert nombre == 1


async def test_be164_ca4_sans_integrations_read_aucune_tentative_visible(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    user_id = await _utilisateur(registered_user)
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as exc:
            await lister_tentatives(db, identite, org_id)
    assert exc.value.status_code == 403
    assert exc.value.code == "PERMISSION_DENIED"


async def test_be164_ca4_avec_integrations_read_les_tentatives_sont_listees(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_id, [PERMISSION_LIRE])
    connecteur_id = await _connecteur(org_id)
    event_id = uuid.uuid4()
    tentative_id = await _executer(connecteur_id, org_id, event_id, _Effet())
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)

    async with AsyncSessionLocal() as db:
        lignes = await lister_tentatives(db, identite, org_id)
    assert tentative_id in {ligne.id for ligne in lignes}


async def test_be164_ca5_tentatives_du_tenant_a_absentes_pour_le_tenant_b(registered_user, organization):
    org_a = uuid.UUID(organization["id"])
    org_b = await _autre_organisation()
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_a, [PERMISSION_LIRE])
    await _accorder(user_id, org_b, [PERMISSION_LIRE])
    connecteur_a = await _connecteur(org_a)
    tentative_a = await _executer(connecteur_a, org_a, uuid.uuid4(), _Effet())
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_a)

    async with AsyncSessionLocal() as db:
        vues_par_a = {ligne.id for ligne in await lister_tentatives(db, identite, org_a)}
        vues_par_b = {ligne.id for ligne in await lister_tentatives(db, identite, org_b)}
    assert tentative_a in vues_par_a
    assert tentative_a not in vues_par_b
