"""BE-210 : configuration d'intégration et référence de credential.

Tests écrits d'après `### BE-210` de implementation-backend/tasks-donnees-api-contrats.md,
avant le code.

Couverture :
- CA-1 : après création, le secret ne peut plus être relu : `GET` ne renvoie aucun secret ;
- CA-2 : aucun secret, token ou ciphertext dans les journaux, l'audit ni les exports ;
- CA-3 : après révocation, toute résolution de la référence est refusée ;
- CA-4 : pendant une rotation, l'ancien secret reste valide jusqu'à révocation, puis est refusé ;
- CA-5 : sans `integrations.manage`, la création renvoie 403 PERMISSION_DENIED et ne crée rien ;
- CA-6 : une intégration d'un autre tenant renvoie 404 (test d'isolation).

Droit : `integrations.manage` (déclaré par `app/integrations/permissions.py`, réutilisé pour
`integration.manage` de la définition). Écriture d'audit : `executer_mutation_sensible`.
"""

import logging
import uuid

import pytest
from sqlalchemy import func, select, text

from app.audit.ecriture import IdentiteEmettrice
from app.core.database import AsyncSessionLocal
from app.core.erreurs.codes import CodeErreur
from app.core.errors import AppError
from app.identity.models import Organization, OrganizationUser, User
from app.rbac.models import Permission, Role, RolePermission, UserRole

INTEGRATIONS_READ = "integrations.read"
INTEGRATIONS_MANAGE = "integrations.manage"
ROUTE = "/api/v1/integrations"


def _entete(utilisateur: dict, organization_id: str) -> dict:
    return {
        "Authorization": f"Bearer {utilisateur['accessToken']}",
        "X-Organization-Id": organization_id,
    }


async def _accorder(user_id: uuid.UUID, org_id: uuid.UUID, codes: list[str]) -> None:
    """Attribue à l'utilisateur un rôle de test portant `codes` dans `org_id`."""
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=org_id, code=f"be210-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-210")
        db.add(role)
        await db.flush()
        for code in codes:
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(code=code, moduleCode="integrations", description="Permission de test BE-210")
                db.add(permission)
                await db.flush()
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        db.add(UserRole(userId=user_id, organizationId=org_id, roleId=role.id))
        await db.commit()


async def _utilisateur_id(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _membre_sans_droit(client, organization_id: str) -> dict:
    """Inscrit un utilisateur, le rattache à l'organisation, sans aucun rôle (refus `403`)."""
    from tests.conftest import unique_email

    email = unique_email()
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Sans droit"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=user.id))
        await db.commit()
    return {"email": email, "accessToken": login.json()["accessToken"], "id": str(user.id)}


async def _autre_organisation() -> uuid.UUID:
    """Crée un tenant B distinct du tenant de test."""
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="Tenant B BE-210", slug=f"be210-b-{uuid.uuid4().hex[:10]}")
        db.add(organisation)
        await db.flush()
        org_id = organisation.id
        await db.commit()
    return org_id


async def _nombre_integrations(organization_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            text('SELECT count(*) FROM "integration" WHERE "organizationId" = :org'),
            {"org": uuid.UUID(organization_id)},
        )


async def _etat_en_base(integration_id: str) -> str:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            text('SELECT state FROM "integration" WHERE id = :id'), {"id": uuid.UUID(integration_id)}
        )


async def _reference_version(integration_id: str, version: int) -> str:
    """Référence du coffre pour une version donnée, lue en base (la base ne porte que la référence)."""
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            text(
                'SELECT "referenceSecret" FROM "integration_credential" '
                'WHERE "integrationId" = :id AND version = :version'
            ),
            {"id": uuid.UUID(integration_id), "version": version},
        )


async def _resoudre(organization_id: str, reference: str) -> str:
    """Résout une référence de credential comme le ferait le service d'envoi."""
    from app.integrations.configuration import resoudre_reference

    async with AsyncSessionLocal() as db:
        return await resoudre_reference(db, uuid.UUID(organization_id), reference)


async def _creer(client, utilisateur: dict, organisation: dict, *, provider="smtp", purpose="envoi", secret="s"):
    res = await client.post(
        ROUTE,
        json={
            "provider": provider,
            "purpose": purpose,
            "scopes": ["mail.send"],
            "configSchemaVersion": 1,
            "secret": secret,
        },
        headers=_entete(utilisateur, organisation["id"]),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest.fixture
async def gestionnaire(client, registered_user: dict, organization: dict) -> dict:
    """Propriétaire de test avec les permissions de lecture et d'écriture des intégrations."""
    await _accorder(
        await _utilisateur_id(registered_user["email"]),
        uuid.UUID(organization["id"]),
        [INTEGRATIONS_READ, INTEGRATIONS_MANAGE],
    )
    return registered_user


async def test_ca1_apres_creation_le_secret_ne_peut_plus_etre_relu(client, gestionnaire, organization):
    secret = f"ca1-{uuid.uuid4().hex}"
    res = await client.post(
        ROUTE,
        json={"provider": "smtp", "purpose": "envoi", "scopes": ["mail.send"], "configSchemaVersion": 1, "secret": secret},
        headers=_entete(gestionnaire, organization["id"]),
    )
    assert res.status_code == 201, res.text
    assert secret not in res.text
    assert res.json()["state"] == "configured"
    integration_id = res.json()["id"]

    lecture = await client.get(f"{ROUTE}/{integration_id}", headers=_entete(gestionnaire, organization["id"]))
    assert lecture.status_code == 200, lecture.text
    assert secret not in lecture.text
    cles = " ".join(lecture.json().keys()).lower()
    assert "secret" not in cles and "token" not in cles and "ciphertext" not in cles


async def test_ca1_unicite_fournisseur_et_usage_par_tenant(client, gestionnaire, organization):
    await _creer(client, gestionnaire, organization, provider="sms", purpose="alerte")
    doublon = await client.post(
        ROUTE,
        json={"provider": "sms", "purpose": "alerte", "scopes": [], "configSchemaVersion": 1, "secret": "autre"},
        headers=_entete(gestionnaire, organization["id"]),
    )
    assert doublon.status_code == 409, doublon.text


async def test_ca2_aucun_secret_dans_journaux_audit_ni_exports(client, gestionnaire, organization, caplog):
    caplog.set_level(logging.DEBUG)
    secret_initial = f"ca2-init-{uuid.uuid4().hex}"
    secret_rotation = f"ca2-rot-{uuid.uuid4().hex}"
    entete = _entete(gestionnaire, organization["id"])

    integration_id = await _creer(client, gestionnaire, organization, secret=secret_initial)
    rotation = await client.post(
        f"{ROUTE}/{integration_id}/rotate", json={"secret": secret_rotation}, headers=entete
    )
    assert rotation.status_code == 200, rotation.text
    revocation = await client.post(f"{ROUTE}/{integration_id}/revoke", headers=entete)
    assert revocation.status_code == 200, revocation.text

    assert secret_initial not in caplog.text
    assert secret_rotation not in caplog.text

    async with AsyncSessionLocal() as db:
        lignes_audit = (
            await db.execute(
                text('SELECT row_to_json(e)::text FROM "audit_event" e WHERE e."organizationId" = :org'),
                {"org": uuid.UUID(organization["id"])},
            )
        ).scalars().all()
        lignes_credential = (
            await db.execute(text('SELECT row_to_json(e)::text FROM "integration_credential" e'))
        ).scalars().all()
        lignes_export = (await db.execute(text('SELECT row_to_json(e)::text FROM "export_audit" e'))).scalars().all()

    assert lignes_audit, "l'audit de création, rotation et révocation doit exister"
    for ligne in [*lignes_audit, *lignes_credential, *lignes_export]:
        assert secret_initial not in ligne
        assert secret_rotation not in ligne


async def test_ca3_apres_revocation_toute_resolution_est_refusee(client, gestionnaire, organization):
    secret = f"ca3-{uuid.uuid4().hex}"
    integration_id = await _creer(client, gestionnaire, organization, secret=secret)
    reference = await _reference_version(integration_id, 1)
    assert await _resoudre(organization["id"], reference) == secret

    revocation = await client.post(f"{ROUTE}/{integration_id}/revoke", headers=_entete(gestionnaire, organization["id"]))
    assert revocation.status_code == 200, revocation.text
    assert revocation.json()["state"] == "revoked"

    with pytest.raises(AppError) as erreur:
        await _resoudre(organization["id"], reference)
    assert erreur.value.status_code == 401


async def test_ca4_rotation_garde_l_ancien_secret_jusqu_a_revocation(client, gestionnaire, organization):
    secret_v1 = f"ca4-v1-{uuid.uuid4().hex}"
    secret_v2 = f"ca4-v2-{uuid.uuid4().hex}"
    entete = _entete(gestionnaire, organization["id"])
    integration_id = await _creer(client, gestionnaire, organization, secret=secret_v1)

    rotation = await client.post(f"{ROUTE}/{integration_id}/rotate", json={"secret": secret_v2}, headers=entete)
    assert rotation.status_code == 200, rotation.text

    reference_v1 = await _reference_version(integration_id, 1)
    reference_v2 = await _reference_version(integration_id, 2)
    assert reference_v1 != reference_v2
    assert await _resoudre(organization["id"], reference_v1) == secret_v1
    assert await _resoudre(organization["id"], reference_v2) == secret_v2

    revocation = await client.post(f"{ROUTE}/{integration_id}/revoke", headers=entete)
    assert revocation.status_code == 200, revocation.text
    for reference in (reference_v1, reference_v2):
        with pytest.raises(AppError) as erreur:
            await _resoudre(organization["id"], reference)
        assert erreur.value.status_code == 401


async def test_ca5_sans_integrations_manage_renvoie_403_et_ne_cree_rien(client, gestionnaire, organization):
    organisation_id = organization["id"]
    sans_droit = await _membre_sans_droit(client, organisation_id)
    avant = await _nombre_integrations(organisation_id)

    res = await client.post(
        ROUTE,
        json={"provider": "smtp", "purpose": "refus", "scopes": [], "configSchemaVersion": 1, "secret": "refuse"},
        headers=_entete(sans_droit, organisation_id),
    )

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"
    assert await _nombre_integrations(organisation_id) == avant


async def test_ca6_integration_d_un_autre_tenant_renvoie_404(client, gestionnaire, organization):
    from app.integrations.configuration import creer_integration

    org_b = await _autre_organisation()
    async with AsyncSessionLocal() as db:
        integration_b = await creer_integration(
            db,
            IdentiteEmettrice(user_id=await _utilisateur_id(gestionnaire["email"]), organization_id=org_b),
            provider="smtp",
            purpose="tenant-b",
            scopes=[],
            config_schema_version=1,
            secret="valeur-tenant-b",
        )
        await db.commit()
        integration_b_id = str(integration_b.id)

    entete = _entete(gestionnaire, organization["id"])
    lecture = await client.get(f"{ROUTE}/{integration_b_id}", headers=entete)
    assert lecture.status_code == 404, lecture.text
    rotation = await client.post(f"{ROUTE}/{integration_b_id}/rotate", json={"secret": "x"}, headers=entete)
    assert rotation.status_code == 404, rotation.text
    revocation = await client.post(f"{ROUTE}/{integration_b_id}/revoke", headers=entete)
    assert revocation.status_code == 404, revocation.text
    assert await _etat_en_base(integration_b_id) == "configured"
