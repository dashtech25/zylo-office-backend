"""BE-239 : intégrations externes, références, secrets, curseur et réconciliation.

Tests écrits d'après la définition `### BE-239` de
implementation-backend/tasks-exploitation-architecture.md, avant le code.

Couverture :
- CA-1 : une clé distante nue est refusée (422) ; seule une référence composée
  `fournisseur/compte/ressource` est acceptée, et aucun lien n'est créé sur refus ;
- CA-2 : la déconnexion supprime l'accès au secret (la résolution pour l'envoi échoue) ;
- CA-3 : un lien d'un tenant est introuvable (404) pour un tenant B, et n'apparaît pas dans sa liste ;
- CA-4 : connexion sans `integrations.manage` renvoie 403 et n'écrit rien ;
- CA-5 : une erreur de synchronisation ne modifie ni la vérité amont ni le curseur ; une
  réconciliation réussie avance le curseur.

Les permissions sont portées par des rôles de test créés pour chaque cas (pas de montage
massif de fixtures). La route est couverte par un test de montage (401 sans session, jamais 404).
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.audit.ecriture import IdentiteEmettrice
from app.core.database import AsyncSessionLocal
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.core.errors import AppError
from app.core.secrets import SecretStore
from app.identity.models import Organization, User
from app.integrations.liens import (
    connecter_integration,
    deconnecter_integration,
    lister_integrations,
    reconcilier_lien,
    verifier_cle_composee,
)
from app.integrations.models import IntegrationLink
from app.integrations.permissions import INTEGRATIONS_MANAGE, INTEGRATIONS_READ
from app.integrations.secrets import SERVICE_INTEGRATION, resoudre_secret_pour_envoi
from app.rbac.models import Permission, Role, RolePermission, UserRole

PROVIDER = "holykell"
COMPTE = "compte-1"
MAINTENANT = datetime(2026, 11, 5, 10, 0, 0, tzinfo=timezone.utc)
VALEUR_SECRETE = "valeur-secrete-be239"


class _Amont:
    """Vérité amont factice : un état qui ne doit jamais changer pendant une synchronisation en erreur."""

    def __init__(self) -> None:
        self.etat: dict[str, int] = {"capteur-7": 42}

    async def lire_changements(self, remote_key: str, curseur: str | None) -> tuple[str, list[dict]]:
        raise RuntimeError("délai dépassé côté fournisseur")


class _AmontSain(_Amont):
    async def lire_changements(self, remote_key: str, curseur: str | None) -> tuple[str, list[dict]]:
        return "c-2", []


async def _utilisateur(registered_user: dict) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        return user.id


async def _autre_organisation() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="Tenant B BE-239", slug=f"be239-b-{uuid.uuid4().hex[:10]}")
        db.add(organisation)
        await db.flush()
        org_id = organisation.id
        await db.commit()
    return org_id


async def _accorder(user_id: uuid.UUID, org_id: uuid.UUID, codes: list[str]) -> None:
    """Attribue à l'utilisateur un rôle de test portant `codes` dans `org_id`."""
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=org_id, code=f"be239-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-239")
        db.add(role)
        await db.flush()
        for code in codes:
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(code=code, moduleCode="integrations", description="Permission de test BE-239")
                db.add(permission)
                await db.flush()
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        db.add(UserRole(userId=user_id, organizationId=org_id, roleId=role.id))
        await db.commit()


async def _connecter(identite: IdentiteEmettrice, store: SecretStore, compte: str = COMPTE) -> IntegrationLink:
    async with AsyncSessionLocal() as db:
        lien = await connecter_integration(
            db,
            store,
            identite,
            PROVIDER,
            compte,
            f"{PROVIDER}/{compte}/capteur-7",
            VALEUR_SECRETE,
        )
        await db.commit()
        return lien


async def _lien(lien_id: uuid.UUID) -> IntegrationLink:
    async with AsyncSessionLocal() as db:
        return await db.get(IntegrationLink, lien_id)


async def _liens_de(org_id: uuid.UUID) -> list[IntegrationLink]:
    async with AsyncSessionLocal() as db:
        return list(
            (await db.execute(select(IntegrationLink).where(IntegrationLink.organizationId == org_id))).scalars()
        )


def test_be239_ca1_cle_distante_nue_refusee():
    """Une clé nue (sans fournisseur ni compte) est refusée ; la forme composée est acceptée."""
    with pytest.raises(AppError) as erreur:
        verifier_cle_composee(PROVIDER, COMPTE, "capteur-7")
    assert erreur.value.status_code == 422

    with pytest.raises(AppError) as erreur:
        verifier_cle_composee(PROVIDER, COMPTE, f"{PROVIDER}/autre-compte/capteur-7")
    assert erreur.value.status_code == 422

    assert verifier_cle_composee(PROVIDER, COMPTE, f"{PROVIDER}/{COMPTE}/capteur-7") is None


async def test_be239_ca1_connexion_avec_cle_nue_ne_cree_aucun_lien(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_id, [INTEGRATIONS_READ, INTEGRATIONS_MANAGE])
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)

    async with AsyncSessionLocal() as db:
        try:
            await connecter_integration(db, SecretStore(), identite, PROVIDER, COMPTE, "capteur-7", VALEUR_SECRETE)
        except AppError as erreur:
            assert erreur.status_code == 422
        else:
            raise AssertionError("une clé distante nue doit être refusée")
        await db.rollback()

    assert await _liens_de(org_id) == []


async def test_be239_ca2_deconnexion_supprime_acces_au_secret(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_id, [INTEGRATIONS_READ, INTEGRATIONS_MANAGE])
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)
    store = SecretStore()
    lien = await _connecter(identite, store)

    async with AsyncSessionLocal() as db:
        valeur = await resoudre_secret_pour_envoi(
            db, store, SERVICE_INTEGRATION, lien.connecteurId, org_id, MAINTENANT
        )
        assert valeur == VALEUR_SECRETE

        await deconnecter_integration(db, store, identite, lien.id)
        await db.commit()

    async with AsyncSessionLocal() as db:
        try:
            await resoudre_secret_pour_envoi(db, store, SERVICE_INTEGRATION, lien.connecteurId, org_id, MAINTENANT)
        except AppError as erreur:
            assert erreur.status_code == 404
        else:
            raise AssertionError("après déconnexion, aucune valeur de secret ne doit être résolue")

    assert (await _lien(lien.id)).statut == "déconnectée"


async def test_be239_ca3_lien_d_un_autre_tenant_introuvable(registered_user, organization):
    org_a = uuid.UUID(organization["id"])
    org_b = await _autre_organisation()
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_a, [INTEGRATIONS_READ, INTEGRATIONS_MANAGE])
    await _accorder(user_id, org_b, [INTEGRATIONS_READ, INTEGRATIONS_MANAGE])
    identite_a = IdentiteEmettrice(user_id=user_id, organization_id=org_a)
    identite_b = IdentiteEmettrice(user_id=user_id, organization_id=org_b)
    lien_a = await _connecter(identite_a, SecretStore())

    async with AsyncSessionLocal() as db:
        try:
            await deconnecter_integration(db, SecretStore(), identite_b, lien_a.id)
        except AppError as erreur:
            assert erreur.status_code == 404
        else:
            raise AssertionError("un lien du tenant A doit être introuvable pour le tenant B")
        await db.rollback()

    async with AsyncSessionLocal() as db:
        ids_b = {lien.id for lien in await lister_integrations(db, identite_b, org_b)}
    assert lien_a.id not in ids_b
    assert (await _lien(lien_a.id)).statut == "connectée"


async def test_be239_ca4_connexion_sans_droit_renvoie_403(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_id, [INTEGRATIONS_READ])  # lecture seule : pas integrations.manage
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)

    async with AsyncSessionLocal() as db:
        try:
            await connecter_integration(
                db, SecretStore(), identite, PROVIDER, COMPTE, f"{PROVIDER}/{COMPTE}/capteur-7", VALEUR_SECRETE
            )
        except ErreurCatalogue as erreur:
            assert erreur.code == CodeErreur.PERMISSION_DENIED
            assert erreur.status_code == 403
        else:
            raise AssertionError("sans integrations.manage, la connexion doit être refusée")
        await db.rollback()

    assert await _liens_de(org_id) == []


async def test_be239_ca5_erreur_de_synchronisation_ne_modifie_pas_la_verite_amont(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_id, [INTEGRATIONS_READ, INTEGRATIONS_MANAGE])
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)
    lien = await _connecter(identite, SecretStore())
    amont = _Amont()
    etat_avant = dict(amont.etat)

    async with AsyncSessionLocal() as db:
        await reconcilier_lien(db, lien.id, amont, MAINTENANT)
        await db.commit()

    lu = await _lien(lien.id)
    assert amont.etat == etat_avant
    assert lu.curseurSync is None
    assert lu.statut == "connectée"
    assert lu.statutReconciliation == "echec"
    assert lu.derniereReconciliation == MAINTENANT


async def test_be239_ca5_reconciliation_reussie_avance_le_curseur(registered_user, organization):
    org_id = uuid.UUID(organization["id"])
    user_id = await _utilisateur(registered_user)
    await _accorder(user_id, org_id, [INTEGRATIONS_READ, INTEGRATIONS_MANAGE])
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)
    lien = await _connecter(identite, SecretStore())

    async with AsyncSessionLocal() as db:
        await reconcilier_lien(db, lien.id, _AmontSain(), MAINTENANT)
        await db.commit()

    lu = await _lien(lien.id)
    assert lu.curseurSync == "c-2"
    assert lu.statutReconciliation == "succes"


async def test_be239_routes_montees(client):
    """Les routes existent : sans session, elles répondent 401 et jamais 404."""
    liste = await client.get("/api/v1/integrations")
    connexion = await client.post(
        f"/api/v1/integrations/{PROVIDER}/connect",
        json={"externalAccount": COMPTE, "remoteKey": f"{PROVIDER}/{COMPTE}/capteur-7", "secretValue": VALEUR_SECRETE},
    )
    deconnexion = await client.post(f"/api/v1/integrations/{uuid.uuid4()}/disconnect")
    assert liste.status_code == 401
    assert connexion.status_code == 401
    assert deconnexion.status_code == 401


