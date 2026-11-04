"""BE-016 : lecture des rôles et permissions de l'organisation courante.

Tests écrits d'après la définition `### BE-016` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.

Décisions (valeurs NON DÉFINIES dans la définition, QE-SOC-04 et QE-SOC-06) :
- Chemins : `GET /api/v1/organizations/current/roles` et
  `GET /api/v1/organizations/current/roles/{roleId}`, organisation résolue par
  l'en-tête `X-Organization-Id` (même sélecteur que `GET /organizations/current`, BE-010).
- Permission de lecture : code NON DÉFINI. Provisoire : `rbac.role.manage`
  (ROLE_MANAGE, déjà accordé au propriétaire). Une permission de lecture distincte
  ajoutée au rôle propriétaire ferait passer son nombre de permissions de 12 à 13,
  ce que CA-1 exclut. À reprendre si QE-SOC-06 tranche autrement.
- CA-1 : 12 permissions, nombre observé dans OWNER_DEFAULT_PERMISSIONS (app/identity/service.py).
- CA-2 : un membre sans rôle reçoit 403 (refus de permission, pas 404 : il est membre).
- CA-3 : PUT, PATCH et DELETE sur les deux chemins renvoient 405 (lecture seule).
- CA-4 : un rôle de O2 demandé avec le contexte de O1 renvoie 404.
"""

import importlib
import inspect
import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.identity.service import OWNER_DEFAULT_PERMISSIONS
from app.rbac.models import Role
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
CHEMIN_ROLES = "/api/v1/organizations/current/roles"


def _entetes(token: str, organisation_id: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {token}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _creer_utilisateur(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-016"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers=_entetes(token))
    return {"id": me.json()["id"], "token": token}


async def _ajouter_membre(organisation_id: str, utilisateur_id: str) -> None:
    """Appartenance sans rôle : insertion directe, faute d'API d'ajout de membre
    avant BE-012 (même procédé que tests/test_be009_garde_contexte.py)."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(utilisateur_id)))
        await db.commit()


async def _id_role_proprietaire(organisation_id: str) -> str:
    async with AsyncSessionLocal() as db:
        role = (
            await db.execute(select(Role).where(Role.organizationId == uuid.UUID(organisation_id), Role.code == "owner"))
        ).scalar_one()
        return str(role.id)


async def test_be016_ca1_proprietaire_lit_ses_12_permissions(client: AsyncClient, organization: dict, registered_user: dict):
    headers = _entetes(registered_user["accessToken"], organization["id"])
    liste = await client.get(CHEMIN_ROLES, headers=headers)
    assert liste.status_code == 200, liste.text
    assert "owner" in [role["code"] for role in liste.json()]

    role_id = await _id_role_proprietaire(organization["id"])
    detail = await client.get(f"{CHEMIN_ROLES}/{role_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    permissions = detail.json()["permissionCodes"]
    assert len(permissions) == 12
    assert set(permissions) == {code for code, _module, _description in OWNER_DEFAULT_PERMISSIONS}


async def test_be016_ca2_membre_sans_permission_de_lecture_recoit_403(client: AsyncClient, organization: dict, registered_user: dict):
    membre = await _creer_utilisateur(client)
    await _ajouter_membre(organization["id"], membre["id"])
    headers = _entetes(membre["token"], organization["id"])

    liste = await client.get(CHEMIN_ROLES, headers=headers)
    assert liste.status_code == 403, liste.text

    role_id = await _id_role_proprietaire(organization["id"])
    detail = await client.get(f"{CHEMIN_ROLES}/{role_id}", headers=headers)
    assert detail.status_code == 403, detail.text


async def test_be016_ca3_ecritures_sur_les_routes_de_lecture_renvoient_405(client: AsyncClient, organization: dict, registered_user: dict):
    headers = _entetes(registered_user["accessToken"], organization["id"])
    role_id = await _id_role_proprietaire(organization["id"])
    for chemin in (CHEMIN_ROLES, f"{CHEMIN_ROLES}/{role_id}"):
        for methode in ("PUT", "PATCH", "DELETE"):
            reponse = await client.request(methode, chemin, headers=headers, json={})
            assert reponse.status_code == 405, f"{methode} {chemin} -> {reponse.status_code}"


async def test_be016_ca4_role_d_une_autre_organisation_renvoie_404(client: AsyncClient, organization: dict, registered_user: dict):
    # Deuxième organisation du même propriétaire : son rôle propriétaire ne doit pas
    # être visible sous le contexte de la première.
    seconde = await client.post(
        "/api/v1/organizations",
        json={"name": "Org BE-016 B", "slug": f"be016-{uuid.uuid4().hex[:10]}"},
        headers=_entetes(registered_user["accessToken"]),
    )
    assert seconde.status_code == 201, seconde.text
    role_o2 = await _id_role_proprietaire(seconde.json()["id"])

    reponse = await client.get(f"{CHEMIN_ROLES}/{role_o2}", headers=_entetes(registered_user["accessToken"], organization["id"]))
    assert reponse.status_code == 404, reponse.text


async def test_be016_documentation_routes_et_module(client: AsyncClient):
    # Documentation attendue : docstrings des routes et doc de module de app/rbac/.
    modules_routes = [importlib.import_module("app.rbac.roles_lecture")]
    for module in modules_routes:
        assert module.__doc__, f"doc de module {module.__name__} absente"
        for nom in ("lister_roles", "lire_role"):
            assert inspect.getdoc(getattr(module, nom)), f"{nom} sans docstring"
    assert importlib.import_module("app.rbac").__doc__, "doc de module app/rbac/ absente"
