"""BE-009 : garde serveur de contexte organisation et d'autorisation.

Tests écrits d'après la définition `### BE-009` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.

Décisions (CA ambigus dans la définition) :
- CA-2 écrit « refusée en 403 », mais la ligne Droits et CA-3 imposent 404 pour une
  organisation hors appartenance (décision T-010, docs/questions/rbac/code-http-acces-interdit.md).
  Le test CA-2 suit 404 ; le 403 est testé sur un membre sans permission.
- CA-4 (lecture de repository sans contexte, BE-002) n'est pas couvert ici : la
  définition BE-009 ne porte que sur les routes et dépendances. Le skip de BE-002 reste.
"""

import importlib
import inspect
import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.rbac.models import Role
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"


def _entetes(utilisateur: dict, organisation_id: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['token']}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _creer_utilisateur(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-009"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "token": token}


async def _creer_organisation(client: AsyncClient, proprietaire: dict, nom: str = "Org BE-009") -> str:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be009-{uuid.uuid4().hex[:10]}"},
        headers=_entetes(proprietaire),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _ajouter_membre(organisation_id: str, utilisateur_id: str) -> None:
    """Pas d'API d'ajout de membre avant BE-012 : insertion directe, comme dans
    tests/test_isolation_organisations.py."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(utilisateur_id)))
        await db.commit()


async def _id_role_proprietaire(client: AsyncClient, proprietaire: dict, organisation_id: str) -> str:
    async with AsyncSessionLocal() as db:
        role = (await db.execute(select(Role).where(Role.organizationId == uuid.UUID(organisation_id), Role.code == "owner"))).scalar_one()
        return str(role.id)


async def test_be009_module_guards_expose_la_garde_et_ses_docstrings():
    # Chemin prévu par la définition : app/rbac/guards.py. Chaque garde exposée porte une docstring.
    guards = importlib.import_module("app.rbac.guards")
    for nom in ("get_current_organization_id", "assert_active_membership", "organisation_cible", "organisation_introuvable"):
        fonction = getattr(guards, nom)
        assert inspect.getdoc(fonction), f"{nom} sans docstring"
    assert guards.__doc__, "doc de module app/rbac/guards.py absente"


async def test_be009_ca1_requete_d_organisation_sans_session_refusee_401(client: AsyncClient, organization: dict):
    headers = {"X-Organization-Id": organization["id"]}

    lecture = await client.get("/api/v1/rbac/organizations/" + organization["id"] + "/roles", headers=headers)
    courante = await client.get("/api/v1/organizations/current", headers=headers)

    assert lecture.status_code == 401, lecture.text
    assert courante.status_code == 401, courante.text


async def test_be009_ca2_membre_absent_refuse_en_404_et_membre_sans_permission_en_403(client: AsyncClient):
    proprietaire = await _creer_utilisateur(client)
    organisation_id = await _creer_organisation(client, proprietaire)
    etranger = await _creer_utilisateur(client)

    # Session valide, aucune appartenance à l'organisation demandée : refus uniforme 404.
    refus = await client.get(
        f"/api/v1/rbac/organizations/{organisation_id}/roles", headers=_entetes(etranger, organisation_id)
    )
    assert refus.status_code == 404, refus.text
    assert refus.json()["error"]["code"] == "organization_not_found"

    # Membre sans la permission requise : 403 permission_denied (refus de droit, pas d'appartenance).
    membre = await _creer_utilisateur(client)
    await _ajouter_membre(organisation_id, membre["id"])
    sans_droit = await client.post(
        f"/api/v1/rbac/organizations/{organisation_id}/roles",
        json={"code": "intrus", "name": "Intrus", "permissionCodes": []},
        headers=_entetes(membre, organisation_id),
    )
    assert sans_droit.status_code == 403, sans_droit.text
    assert sans_droit.json()["error"]["code"] == "permission_denied"


async def test_be009_ca3_organisation_etrangere_dans_l_en_tete_ou_le_chemin_refusee_404(client: AsyncClient):
    o1_proprietaire = await _creer_utilisateur(client)
    o1 = await _creer_organisation(client, o1_proprietaire, "Org O1")
    o2_proprietaire = await _creer_utilisateur(client)
    o2 = await _creer_organisation(client, o2_proprietaire, "Org O2")

    # Session de O1 (membre de O1 seulement) avec le sélecteur O2 : refusé.
    selecteur = await client.get("/api/v1/organizations/current", headers=_entetes(o1_proprietaire, o2))
    assert selecteur.status_code == 404, selecteur.text
    assert "Org O2" not in selecteur.text

    # Membre de O1 et O2 : le chemin (O2) et l'en-tête (O1) désignent deux organisations, refus.
    await _ajouter_membre(o2, o1_proprietaire["id"])
    incoherent = await client.get(f"/api/v1/rbac/organizations/{o2}/roles", headers=_entetes(o1_proprietaire, o1))
    assert incoherent.status_code == 404, incoherent.text


async def test_be009_ca4_identifiant_d_une_autre_organisation_repond_comme_un_inexistant(client: AsyncClient):
    o1_proprietaire = await _creer_utilisateur(client)
    o1 = await _creer_organisation(client, o1_proprietaire, "Org O1")
    o2_proprietaire = await _creer_utilisateur(client)
    o2 = await _creer_organisation(client, o2_proprietaire, "Org O2")
    role_o2 = await _id_role_proprietaire(client, o2_proprietaire, o2)
    role_inexistant = str(uuid.uuid4())

    headers = _entetes(o1_proprietaire, o1)
    # Contexte O1 légitime, identifiant de rôle deviné appartenant à O2.
    de_o2 = await client.get(f"/api/v1/rbac/organizations/{o1}/roles/{role_o2}", headers=headers)
    inexistant = await client.get(f"/api/v1/rbac/organizations/{o1}/roles/{role_inexistant}", headers=headers)

    assert de_o2.status_code == inexistant.status_code == 404
    assert de_o2.json() == inexistant.json()
    assert o2 not in de_o2.text


async def test_be009_ca5_changer_d_organisation_active_change_le_perimetre(client: AsyncClient):
    utilisateur = await _creer_utilisateur(client)
    o1 = await _creer_organisation(client, utilisateur, "Org active A")
    o2 = await _creer_organisation(client, utilisateur, "Org active B")

    avant = await client.get("/api/v1/organizations/current", headers=_entetes(utilisateur, o1))
    apres = await client.get("/api/v1/organizations/current", headers=_entetes(utilisateur, o2))

    assert avant.status_code == 200 and avant.json()["id"] == o1
    assert apres.status_code == 200 and apres.json()["id"] == o2
    assert "Org active A" not in apres.text

    roles_o2 = await client.get(f"/api/v1/rbac/organizations/{o2}/roles", headers=_entetes(utilisateur, o2))
    assert roles_o2.status_code == 200
    assert all(role["organizationId"] == o2 for role in roles_o2.json())
