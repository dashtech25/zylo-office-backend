"""Fermeture du contournement de la règle « un rôle par module et par utilisateur » (T-018, T-021).

Avant ce correctif, la route générique d'attribution de rôle (`POST /rbac/organizations/{id}/user-roles`)
acceptait un rôle de module à l'échelle de l'organisation sans appliquer la règle, que
l'API d'affectation de module (`module-roles/assignments`) fait respecter.

Règles testées :
- un rôle de module attribué à l'organisation entière passe par l'API de module (même refus) ;
- module inactif : refus, comme par l'API de module ;
- compatibilité explicite conservée pour les portées ressource (station, zylo_liquid / zylo_tanker) :
  duplicat exact refusé comme avant, second rôle du même module refusé ;
- un rôle sans module garde son comportement.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditLog
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"


def _entetes(utilisateur: dict, organisation_id: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['token']}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _proprietaire(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Propriétaire"})
    token = (await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})).json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    acteur = {"id": me.json()["id"], "token": token}
    res = await client.post(
        "/api/v1/organizations",
        json={"name": f"Org {uuid.uuid4().hex[:6]}", "slug": f"org-{uuid.uuid4().hex[:10]}"},
        headers=_entetes(acteur),
    )
    assert res.status_code == 201, res.text
    acteur["organisation"] = res.json()["id"]
    return acteur


async def _activer_module(client: AsyncClient, acteur: dict, module: str = "zylo_liquid") -> None:
    res = await client.post(
        f"/api/v1/modules/organizations/{acteur['organisation']}/activate",
        json={"moduleCode": module},
        headers=_entetes(acteur, acteur["organisation"]),
    )
    assert res.status_code == 200, res.text


async def _role_de_module(client: AsyncClient, acteur: dict, code: str, module: str = "zylo_liquid") -> str:
    res = await client.post(
        f"/api/v1/rbac/organizations/{acteur['organisation']}/module-roles",
        json={"moduleCode": module, "code": f"{code}-{uuid.uuid4().hex[:6]}", "name": f"Rôle {code}", "permissionCodes": []},
        headers=_entetes(acteur, acteur["organisation"]),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _membre(client: AsyncClient, acteur: dict) -> str:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Membre"})
    me = (await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE}))
    identifiant = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {me.json()['accessToken']}"})).json()["id"]
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(acteur["organisation"]), userId=uuid.UUID(identifiant)))
        await db.commit()
    return identifiant


async def _attribuer_generique(client: AsyncClient, acteur: dict, cible: str, role: str, **portee):
    return await client.post(
        f"/api/v1/rbac/organizations/{acteur['organisation']}/user-roles",
        json={"userId": cible, "roleId": role, **portee},
        headers=_entetes(acteur, acteur["organisation"]),
    )


async def test_second_role_du_meme_module_refuse_par_la_route_generique(client: AsyncClient):
    acteur = await _proprietaire(client)
    await _activer_module(client, acteur)
    premier = await _role_de_module(client, acteur, "terrain")
    second = await _role_de_module(client, acteur, "bureau")
    cible = await _membre(client, acteur)

    assert (await _attribuer_generique(client, acteur, cible, premier)).status_code == 201

    res = await _attribuer_generique(client, acteur, cible, second)
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "module_role_already_assigned"


async def test_role_de_module_organisation_entiere_passe_par_l_api_de_module(client: AsyncClient):
    acteur = await _proprietaire(client)
    await _activer_module(client, acteur)
    role = await _role_de_module(client, acteur, "terrain")
    cible = await _membre(client, acteur)

    assert (await _attribuer_generique(client, acteur, cible, role)).status_code == 201

    async with AsyncSessionLocal() as db:
        trace = await db.scalar(
            select(AuditLog.id).where(
                AuditLog.organizationId == uuid.UUID(acteur["organisation"]),
                AuditLog.action == "rbac.moduleRole.assign",
            )
        )
    assert trace is not None, "l'attribution doit être faite et journalisée par l'API de module"


async def test_role_de_module_refuse_si_module_inactif(client: AsyncClient):
    acteur = await _proprietaire(client)
    # Module non activé : l'API de module refuse, la route générique doit refuser de même.
    role = await _role_de_module(client, acteur, "terrain")
    cible = await _membre(client, acteur)

    res = await _attribuer_generique(client, acteur, cible, role)

    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "module_not_active"


async def test_compatibilite_portee_station_conservee_et_duplicat_refuse(client: AsyncClient):
    acteur = await _proprietaire(client)
    await _activer_module(client, acteur)
    role = await _role_de_module(client, acteur, "chef")
    autre = await _role_de_module(client, acteur, "adjoint")
    cible = await _membre(client, acteur)
    station_a, station_b = str(uuid.uuid4()), str(uuid.uuid4())

    # Chemin station (zylo_liquid) : toujours accepté, portée explicite.
    res = await _attribuer_generique(client, acteur, cible, role, resourceType="station", resourceId=station_a)
    assert res.status_code == 201, res.text

    # Même rôle, même portée : refus comme avant (duplicat).
    res = await _attribuer_generique(client, acteur, cible, role, resourceType="station", resourceId=station_a)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "role_already_assigned"

    # Un second rôle du même module, même sur une autre station : refusé (un rôle par module).
    res = await _attribuer_generique(client, acteur, cible, autre, resourceType="station", resourceId=station_b)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "module_role_already_assigned"


async def test_role_sans_module_garde_son_comportement(client: AsyncClient):
    acteur = await _proprietaire(client)
    res = await client.post(
        f"/api/v1/rbac/organizations/{acteur['organisation']}/roles",
        json={"code": f"custom-{uuid.uuid4().hex[:6]}", "name": "Personnalisé", "permissionCodes": []},
        headers=_entetes(acteur, acteur["organisation"]),
    )
    assert res.status_code == 201, res.text
    role = res.json()["id"]
    cible = await _membre(client, acteur)

    assert (await _attribuer_generique(client, acteur, cible, role)).status_code == 201
    assert (await _attribuer_generique(client, acteur, cible, role)).status_code == 409
