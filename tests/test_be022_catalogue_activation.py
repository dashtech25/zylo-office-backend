"""BE-022 : catalogue et activation des modules par organisation.

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-socle-tenant-identite.md,
section BE-022) :

- GET  /api/v1/organizations/current/modules : catalogue croisé avec l'état d'activation, lecture
  pour tout membre ;
- PUT  /api/v1/organizations/current/modules/{moduleId}/activation : activation ou désactivation,
  permission requise (refus 403 sans elle), module inconnu ou incompatible refusé, audit à chaque
  transition.

Chaque test crée ses propres organisations et utilisateurs ; les modifications du registre
(module incompatible, module inconnu) sont annulées dans un bloc `finally`.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.modules_registry.models import Module, OrganizationModule

URL_CATALOGUE = "/api/v1/organizations/current/modules"


def _url_activation(module_id: str) -> str:
    return f"/api/v1/organizations/current/modules/{module_id}/activation"


def _entetes(user: dict, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization_id}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    """Crée un compte et ouvre une session : le compte n'a aucune permission particulière."""
    email = f"be022-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Be022"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    tokens = login.json()
    return {"email": email, "accessToken": tokens["accessToken"], "refreshToken": tokens["refreshToken"]}


async def _ajoute_membre_sans_permission(user: dict, organization_id: str) -> None:
    """Rattache l'utilisateur à l'organisation sans lui donner de rôle : il est membre, pas administrateur."""
    async with AsyncSessionLocal() as db:
        user_id = (await db.execute(select(User.id).where(User.email == user["email"]))).scalar_one()
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=user_id))
        await db.commit()


async def _module_id(client: AsyncClient, headers: dict, module_code: str) -> str:
    res = await client.get(URL_CATALOGUE, headers=headers)
    assert res.status_code == 200, res.text
    return next(m["moduleId"] for m in res.json() if m["moduleCode"] == module_code)


async def _compte_activations(organization_id: str, action: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.organizationId == uuid.UUID(organization_id), AuditEvent.action == action)
            )
        ).scalar_one()


async def _statut_organisation(organization_id: str, module_code: str) -> str | None:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(OrganizationModule.status).where(
                    OrganizationModule.organizationId == uuid.UUID(organization_id),
                    OrganizationModule.moduleCode == module_code,
                )
            )
        ).scalar_one_or_none()


async def test_ca1_activer_puis_desactiver_persiste_l_etat(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _entetes(registered_user, organization["id"])
    module_id = await _module_id(client, headers, "zylo_liquid")

    res = await client.put(_url_activation(module_id), json={"active": True}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "active"
    assert await _statut_organisation(organization["id"], "zylo_liquid") == "active"
    catalogue = await client.get(URL_CATALOGUE, headers=headers)
    assert next(m for m in catalogue.json() if m["moduleCode"] == "zylo_liquid")["status"] == "active"

    res = await client.put(_url_activation(module_id), json={"active": False}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "inactive"
    assert await _statut_organisation(organization["id"], "zylo_liquid") == "inactive"
    catalogue = await client.get(URL_CATALOGUE, headers=headers)
    assert next(m for m in catalogue.json() if m["moduleCode"] == "zylo_liquid")["status"] == "inactive"


async def test_catalogue_expose_l_identifiant_du_module_et_son_statut(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _entetes(registered_user, organization["id"])
    res = await client.get(URL_CATALOGUE, headers=headers)
    assert res.status_code == 200, res.text
    ligne = next(m for m in res.json() if m["moduleCode"] == "zylo_liquid")
    uuid.UUID(ligne["moduleId"])  # lève si l'identifiant n'est pas un UUID
    assert ligne["status"] == "inactive"


async def test_ca2_membre_sans_permission_recoit_403_et_l_etat_ne_change_pas(
    client: AsyncClient, registered_user: dict, organization: dict
):
    owner_headers = _entetes(registered_user, organization["id"])
    module_id = await _module_id(client, owner_headers, "zylo_liquid")

    membre = await _nouvel_utilisateur(client)
    await _ajoute_membre_sans_permission(membre, organization["id"])
    membre_headers = _entetes(membre, organization["id"])

    # La lecture du catalogue reste ouverte à tout membre.
    assert (await client.get(URL_CATALOGUE, headers=membre_headers)).status_code == 200

    res = await client.put(_url_activation(module_id), json={"active": True}, headers=membre_headers)
    assert res.status_code == 403, res.text
    assert await _statut_organisation(organization["id"], "zylo_liquid") is None
    catalogue = await client.get(URL_CATALOGUE, headers=owner_headers)
    assert next(m for m in catalogue.json() if m["moduleCode"] == "zylo_liquid")["status"] == "inactive"


async def test_ca3_activation_dans_o1_sans_effet_sur_o2(client: AsyncClient, registered_user: dict, organization: dict):
    headers_o1 = _entetes(registered_user, organization["id"])
    module_id = await _module_id(client, headers_o1, "zylo_liquid")

    autre = await _nouvel_utilisateur(client)
    org_o2 = await client.post(
        "/api/v1/organizations",
        json={"name": "Org O2", "slug": f"be022-o2-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {autre['accessToken']}"},
    )
    assert org_o2.status_code == 201, org_o2.text
    headers_o2 = _entetes(autre, org_o2.json()["id"])

    res = await client.put(_url_activation(module_id), json={"active": True}, headers=headers_o1)
    assert res.status_code == 200, res.text

    catalogue_o2 = await client.get(URL_CATALOGUE, headers=headers_o2)
    assert next(m for m in catalogue_o2.json() if m["moduleCode"] == "zylo_liquid")["status"] == "inactive"
    assert await _statut_organisation(org_o2.json()["id"], "zylo_liquid") is None


async def test_organisation_dont_on_n_est_pas_membre_renvoie_404(client: AsyncClient, registered_user: dict, organization: dict):
    autre = await _nouvel_utilisateur(client)
    org_o2 = await client.post(
        "/api/v1/organizations",
        json={"name": "Org O2 bis", "slug": f"be022-o2b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {autre['accessToken']}"},
    )
    assert org_o2.status_code == 201, org_o2.text
    headers_o1 = _entetes(registered_user, organization["id"])
    module_id = await _module_id(client, headers_o1, "zylo_liquid")

    # Le propriétaire de O1 cible O2 par l'en-tête : il n'en est pas membre, donc 404.
    intrus = _entetes(registered_user, org_o2.json()["id"])
    res = await client.put(_url_activation(module_id), json={"active": True}, headers=intrus)
    assert res.status_code == 404, res.text
    assert await _statut_organisation(org_o2.json()["id"], "zylo_liquid") is None


async def test_ca4_module_inconnu_ou_identifiant_absent_est_refuse(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _entetes(registered_user, organization["id"])

    res = await client.put(_url_activation(str(uuid.uuid4())), json={"active": True}, headers=headers)
    assert res.status_code == 404, res.text

    code_inconnu = f"module_fantome_be022_{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        ligne = Module(code=code_inconnu, name="Fantome", description=None, version="0.1.0")
        db.add(ligne)
        await db.commit()
        module_id = str(ligne.id)
    try:
        res = await client.put(_url_activation(module_id), json={"active": True}, headers=headers)
        assert res.status_code == 404, res.text
        assert await _statut_organisation(organization["id"], code_inconnu) is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Module).where(Module.code == code_inconnu))
            await db.commit()


async def test_ca4_module_incompatible_ne_peut_pas_etre_active(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _entetes(registered_user, organization["id"])
    module_id = await _module_id(client, headers, "zylo_tanker")
    async with AsyncSessionLocal() as db:
        await db.execute(update(Module).where(Module.code == "zylo_tanker").values(manifestVersion=99))
        await db.commit()
    try:
        res = await client.put(_url_activation(module_id), json={"active": True}, headers=headers)
        assert res.status_code == 409, res.text
        assert res.json()["error"]["code"] == "module_incompatible"
        assert await _statut_organisation(organization["id"], "zylo_tanker") is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(update(Module).where(Module.code == "zylo_tanker").values(manifestVersion=1))
            await db.commit()


async def test_ca5_chaque_activation_et_desactivation_cree_une_entree_d_audit(
    client: AsyncClient, registered_user: dict, organization: dict
):
    headers = _entetes(registered_user, organization["id"])
    module_id = await _module_id(client, headers, "zylo_liquid")
    org_id = organization["id"]
    activations_avant = await _compte_activations(org_id, "modulesRegistry.module.activate")
    desactivations_avant = await _compte_activations(org_id, "modulesRegistry.module.deactivate")

    assert (await client.put(_url_activation(module_id), json={"active": True}, headers=headers)).status_code == 200
    assert await _compte_activations(org_id, "modulesRegistry.module.activate") == activations_avant + 1

    assert (await client.put(_url_activation(module_id), json={"active": False}, headers=headers)).status_code == 200
    assert await _compte_activations(org_id, "modulesRegistry.module.deactivate") == desactivations_avant + 1
