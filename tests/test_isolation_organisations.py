"""Isolation inter-organisations (T-010 : IAM-001, IAM-004, IAM-018).

Intention : l'en-tête `X-Organization-Id` est un sélecteur, jamais une
autorité. Un administrateur de l'organisation A ne doit rien pouvoir faire sur
l'organisation B, quelle que soit la route, et rien ne doit être écrit en base.

Règles testées :
- réponse uniforme 404 (`organization_not_found`) pour « inexistant » et
  « interdit » entre organisations (docs/questions/rbac/code-http-acces-interdit.md,
  option A) ;
- un refus de droit au sein d'une même organisation reste un 403
  (`permission_denied`) ;
- l'attribution d'un rôle ou d'un grant exige que l'utilisateur ciblé soit
  membre actif de l'organisation (IAM-004).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.rbac.models import Role, UserRole
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entetes(utilisateur: dict, organisation_id: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['token']}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _creer_utilisateur(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur test"}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "token": token}


async def _creer_organisation(client: AsyncClient, proprietaire: dict) -> str:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": f"Org {uuid.uuid4().hex[:6]}", "slug": f"org-{uuid.uuid4().hex[:10]}"},
        headers=_entetes(proprietaire),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _activer_module(client: AsyncClient, proprietaire: dict, organisation_id: str, module: str) -> None:
    res = await client.post(
        f"/api/v1/modules/organizations/{organisation_id}/activate",
        json={"moduleCode": module},
        headers=_entetes(proprietaire, organisation_id),
    )
    assert res.status_code == 200, res.text


async def _ajouter_membre(organisation_id: str, utilisateur_id: str) -> None:
    """Le socle n'expose pas encore d'ajout de membre (IAM-006) : insertion
    directe, comme dans les fixtures existantes."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(utilisateur_id)))
        await db.commit()


async def _ajouter_attribution_sans_appartenance(organisation_id: str, utilisateur_id: str, role_id: str) -> None:
    """État que la version défectueuse laissait possible (IAM-004) : une
    attribution de rôle dans B sans appartenance à B. Insertion directe car
    l'API ne le permet plus après correctif."""
    async with AsyncSessionLocal() as db:
        db.add(
            UserRole(
                userId=uuid.UUID(utilisateur_id),
                organizationId=uuid.UUID(organisation_id),
                roleId=uuid.UUID(role_id),
            )
        )
        await db.commit()


async def _id_role_proprietaire(client: AsyncClient, proprietaire: dict, organisation_id: str) -> str:
    res = await client.get(f"/api/v1/rbac/organizations/{organisation_id}/roles", headers=_entetes(proprietaire, organisation_id))
    return next(r["id"] for r in res.json() if r["code"] == "owner")


async def _etat_organisation_b(client: AsyncClient, ctx: dict) -> dict:
    """Photographie de ce que l'administrateur de B voit : toute écriture
    cross-organisation qui réussit modifie au moins un de ces champs."""
    org_b = ctx["org_b"]
    entetes = _entetes(ctx["owner_b"], org_b)
    organisations = await client.get("/api/v1/organizations", headers=_entetes(ctx["owner_b"]))
    modules = await client.get(f"/api/v1/modules/organizations/{org_b}", headers=entetes)
    roles = await client.get(f"/api/v1/rbac/organizations/{org_b}/roles", headers=entetes)
    membres = await client.get(f"/api/v1/rbac/organizations/{org_b}/members", headers=entetes)
    grants = await client.get(
        f"/api/v1/rbac/organizations/{org_b}/users/{ctx['membre_b']['id']}/grants", headers=entetes
    )
    for res in (organisations, modules, roles, membres, grants):
        assert res.status_code == 200, res.text
    return {
        "organisations": organisations.json(),
        "modules": modules.json(),
        "roles": roles.json(),
        "membres": membres.json(),
        "grants": grants.json(),
    }


@pytest.fixture
async def contexte(client: AsyncClient) -> dict:
    """Deux organisations. A : `admin_a` est propriétaire, tous droits sur A.
    B : `owner_b` est propriétaire ; `membre_b` est membre de B sans droit ; B
    contient un rôle « gerant », un grant individuel (deny) pour `membre_b`."""
    admin_a = await _creer_utilisateur(client)
    org_a = await _creer_organisation(client, admin_a)
    await _activer_module(client, admin_a, org_a, "zylo_liquid")

    owner_b = await _creer_utilisateur(client)
    org_b = await _creer_organisation(client, owner_b)
    await _activer_module(client, owner_b, org_b, "zylo_liquid")

    membre_b = await _creer_utilisateur(client)
    await _ajouter_membre(org_b, membre_b["id"])

    role = await client.post(
        f"/api/v1/rbac/organizations/{org_b}/roles",
        json={"code": "gerant", "name": "Gérant", "permissionCodes": ["zyloLiquid.station.read"]},
        headers=_entetes(owner_b, org_b),
    )
    assert role.status_code == 201, role.text

    grant = await client.post(
        f"/api/v1/rbac/organizations/{org_b}/grants",
        json={"userId": membre_b["id"], "permissionCode": "zyloLiquid.station.read", "effect": "deny"},
        headers=_entetes(owner_b, org_b),
    )
    assert grant.status_code == 201, grant.text

    ctx = {
        "admin_a": admin_a,
        "org_a": org_a,
        "owner_b": owner_b,
        "org_b": org_b,
        "membre_b": membre_b,
        "role_gerant_b": role.json()["id"],
        "grant_b": grant.json()["id"],
    }
    ctx["role_proprietaire_b"] = await _id_role_proprietaire(client, owner_b, org_b)
    return ctx


# ---------------------------------------------------------------------------
# 1. Les 13 routes d'organisation à chemin : admin de A sur B -> 404, rien écrit
# ---------------------------------------------------------------------------

CAS_CHEMIN_ORGANISATION = [
    pytest.param(
        "billing_souscription",
        lambda c: "POST",
        lambda c: f"/api/v1/billing/organizations/{c['org_b']}/subscriptions",
        lambda c: {"planCode": c["plan_code"]},
        id="billing-POST-subscriptions",
    ),
    pytest.param(
        "identity_patch_organisation",
        lambda c: "PATCH",
        lambda c: f"/api/v1/organizations/{c['org_b']}",
        lambda c: {"name": "Renommée par A"},
        id="identity-PATCH-organization",
    ),
    pytest.param(
        "identity_protected_demo",
        lambda c: "GET",
        lambda c: f"/api/v1/organizations/{c['org_b']}/protected-demo",
        lambda c: None,
        id="identity-GET-protected-demo",
    ),
    pytest.param(
        "modules_activate",
        lambda c: "POST",
        lambda c: f"/api/v1/modules/organizations/{c['org_b']}/activate",
        lambda c: {"moduleCode": "zylo_tanker"},
        id="modules-POST-activate",
    ),
    pytest.param(
        "modules_deactivate",
        lambda c: "POST",
        lambda c: f"/api/v1/modules/organizations/{c['org_b']}/deactivate",
        lambda c: {"moduleCode": "zylo_liquid"},
        id="modules-POST-deactivate",
    ),
    pytest.param(
        "modules_protected_demo",
        lambda c: "GET",
        lambda c: f"/api/v1/modules/organizations/{c['org_b']}/zylo-liquid/protected-demo",
        lambda c: None,
        id="modules-GET-zylo-liquid-protected-demo",
    ),
    pytest.param(
        "rbac_create_role",
        lambda c: "POST",
        lambda c: f"/api/v1/rbac/organizations/{c['org_b']}/roles",
        lambda c: {"code": "pirate", "name": "Pirate", "permissionCodes": []},
        id="rbac-POST-roles",
    ),
    pytest.param(
        "rbac_update_role_permissions",
        lambda c: "PUT",
        lambda c: f"/api/v1/rbac/organizations/{c['org_b']}/roles/{c['role_gerant_b']}/permissions",
        # Liste vide : aucune élévation possible à contrôler, seul le contrôle
        # d'organisation protège B (le rôle « gerant » perd sa permission).
        lambda c: {"permissionCodes": []},
        id="rbac-PUT-role-permissions",
    ),
    pytest.param(
        "rbac_assign_role",
        lambda c: "POST",
        lambda c: f"/api/v1/rbac/organizations/{c['org_b']}/user-roles",
        lambda c: {"userId": c["membre_b"]["id"], "roleId": c["role_gerant_b"], "resourceType": None, "resourceId": None},
        id="rbac-POST-user-roles",
    ),
    pytest.param(
        "rbac_unassign_role",
        lambda c: "DELETE",
        lambda c: f"/api/v1/rbac/organizations/{c['org_b']}/user-roles/{c['attribution_proprietaire_b']}",
        lambda c: None,
        id="rbac-DELETE-user-roles",
    ),
    pytest.param(
        "rbac_list_user_grants",
        lambda c: "GET",
        lambda c: f"/api/v1/rbac/organizations/{c['org_b']}/users/{c['membre_b']['id']}/grants",
        lambda c: None,
        id="rbac-GET-user-grants",
    ),
    pytest.param(
        "rbac_create_grant",
        lambda c: "POST",
        lambda c: f"/api/v1/rbac/organizations/{c['org_b']}/grants",
        # Effet deny : le contrôle de non-élévation ne porte que sur les allow (IAM-012).
        lambda c: {"userId": c["membre_b"]["id"], "permissionCode": "rbac.role.manage", "effect": "deny"},
        id="rbac-POST-grants",
    ),
    pytest.param(
        "rbac_revoke_grant",
        lambda c: "DELETE",
        lambda c: f"/api/v1/rbac/organizations/{c['org_b']}/grants/{c['grant_b']}",
        lambda c: None,
        id="rbac-DELETE-grants",
    ),
]


@pytest.fixture
async def contexte_attaque(client: AsyncClient, contexte: dict, test_city: dict) -> dict:
    """Ajoute à `contexte` ce qu'il faut pour les cas d'attaque : un plan
    d'abonnement et l'attribution de propriétaire de B (cible de la révocation)."""
    plan_code = f"plan-{uuid.uuid4().hex[:8]}"
    # Catalogue seedé hors API (T-019) : plus de création de plan par HTTP.
    from tests.test_billing import creer_plan_catalogue

    await creer_plan_catalogue(plan_code)
    membres = await client.get(
        f"/api/v1/rbac/organizations/{contexte['org_b']}/members", headers=_entetes(contexte["owner_b"], contexte["org_b"])
    )
    proprietaire = next(m for m in membres.json() if m["userId"] == contexte["owner_b"]["id"])
    return {**contexte, "plan_code": plan_code, "attribution_proprietaire_b": proprietaire["roles"][0]["assignmentId"]}


@pytest.mark.parametrize("nom, methode, url, corps", CAS_CHEMIN_ORGANISATION)
async def test_admin_de_a_ne_peut_rien_faire_sur_b_par_chemin(client: AsyncClient, contexte_attaque: dict, nom, methode, url, corps):
    avant = await _etat_organisation_b(client, contexte_attaque)

    res = await client.request(
        methode(contexte_attaque),
        url(contexte_attaque),
        json=corps(contexte_attaque),
        headers=_entetes(contexte_attaque["admin_a"], contexte_attaque["org_a"]),
    )

    assert res.status_code == 404, f"{nom} : {res.status_code} {res.text}"
    assert res.json()["error"]["code"] == "organization_not_found"
    assert await _etat_organisation_b(client, contexte_attaque) == avant, f"{nom} a modifié B"


# ---------------------------------------------------------------------------
# 2. Sélecteur incohérent : en-tête != chemin, même pour un membre des deux
# ---------------------------------------------------------------------------


async def test_en_tete_different_du_chemin_est_refuse_meme_pour_un_membre_des_deux(client: AsyncClient, contexte: dict):
    """admin_a est membre de A (propriétaire) ET de B (sans droit). Avec le
    chemin B et l'en-tête A, la requête est incohérente : 404, pas 403."""
    await _ajouter_membre(contexte["org_b"], contexte["admin_a"]["id"])

    res = await client.get(
        f"/api/v1/organizations/{contexte['org_b']}/protected-demo",
        headers=_entetes(contexte["admin_a"], contexte["org_a"]),
    )

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "organization_not_found"


async def test_membre_de_a_et_de_b_est_autorise_selon_ses_droits_sur_chacune(client: AsyncClient, contexte: dict):
    await _ajouter_membre(contexte["org_b"], contexte["admin_a"]["id"])

    sur_a = await client.get(
        f"/api/v1/organizations/{contexte['org_a']}/protected-demo",
        headers=_entetes(contexte["admin_a"], contexte["org_a"]),
    )
    sur_b = await client.get(
        f"/api/v1/organizations/{contexte['org_b']}/protected-demo",
        headers=_entetes(contexte["admin_a"], contexte["org_b"]),
    )

    assert sur_a.status_code == 200
    # Membre de B sans droit de gestion : refus de droit au sein de B = 403.
    assert sur_b.status_code == 403
    assert sur_b.json()["error"]["code"] == "permission_denied"


# ---------------------------------------------------------------------------
# 3. Routes sans chemin d'organisation : l'en-tête seul ne suffit pas
# ---------------------------------------------------------------------------


async def test_attribution_sans_appartenance_ne_donne_pas_acces_aux_routes_sans_chemin(
    client: AsyncClient, contexte: dict, test_city: dict
):
    """Cas IAM-004 : admin_a a un rôle propriétaire dans B sans être membre de
    B. Route sans chemin (`zylo-liquid/stations`) : l'en-tête B doit être
    refusé, en lecture comme en écriture, et rien ne doit être créé dans B."""
    role_owner_b = await _id_role_proprietaire(client, contexte["owner_b"], contexte["org_b"])
    await _ajouter_attribution_sans_appartenance(contexte["org_b"], contexte["admin_a"]["id"], role_owner_b)

    station = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station de B", "code": f"B-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=_entetes(contexte["owner_b"], contexte["org_b"]),
    )
    assert station.status_code == 201, station.text
    avant = await client.get("/api/v1/zylo-liquid/stations", headers=_entetes(contexte["owner_b"], contexte["org_b"]))

    lecture = await client.get("/api/v1/zylo-liquid/stations", headers=_entetes(contexte["admin_a"], contexte["org_b"]))
    ecriture = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station injectée", "code": f"X-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=_entetes(contexte["admin_a"], contexte["org_b"]),
    )

    assert lecture.status_code == 404, lecture.text
    assert lecture.json()["error"]["code"] == "organization_not_found"
    assert ecriture.status_code == 404, ecriture.text
    apres = await client.get("/api/v1/zylo-liquid/stations", headers=_entetes(contexte["owner_b"], contexte["org_b"]))
    assert apres.json() == avant.json()


async def test_membre_sans_droit_sur_route_sans_chemin_reste_refuse_par_permission(client: AsyncClient, contexte: dict, test_city: dict):
    """Refus de droit au sein de la même organisation : 403, pas 404."""
    res = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station refusée", "code": f"R-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=_entetes(contexte["membre_b"], contexte["org_b"]),
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "permission_denied"


async def test_non_membre_sur_route_sans_chemin_recoit_404_uniforme(client: AsyncClient, contexte: dict, test_city: dict):
    """Un utilisateur sans aucun lien avec B ne doit pas savoir si B existe :
    même réponse qu'une organisation inexistante."""
    res_existante = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "x", "code": f"N-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=_entetes(contexte["admin_a"], contexte["org_b"]),
    )
    res_inexistante = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "x", "code": f"N-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=_entetes(contexte["admin_a"], str(uuid.uuid4())),
    )
    assert res_existante.status_code == 404
    assert res_inexistante.status_code == 404
    assert res_existante.json() == res_inexistante.json()


# ---------------------------------------------------------------------------
# 4. Attribution et grants : la cible doit être membre (IAM-004)
# ---------------------------------------------------------------------------


async def test_attribution_de_role_a_un_non_membre_est_refusee(client: AsyncClient, contexte: dict):
    non_membre = await _creer_utilisateur(client)

    res = await client.post(
        f"/api/v1/rbac/organizations/{contexte['org_b']}/user-roles",
        json={"userId": non_membre["id"], "roleId": contexte["role_gerant_b"], "resourceType": None, "resourceId": None},
        headers=_entetes(contexte["owner_b"], contexte["org_b"]),
    )
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "user_not_found"

    membres = await client.get(
        f"/api/v1/rbac/organizations/{contexte['org_b']}/members", headers=_entetes(contexte["owner_b"], contexte["org_b"])
    )
    cible = [m for m in membres.json() if m["userId"] == non_membre["id"]]
    assert cible == []


async def test_grant_a_un_non_membre_est_refuse(client: AsyncClient, contexte: dict):
    non_membre = await _creer_utilisateur(client)

    res = await client.post(
        f"/api/v1/rbac/organizations/{contexte['org_b']}/grants",
        json={"userId": non_membre["id"], "permissionCode": "zyloLiquid.station.read", "effect": "deny"},
        headers=_entetes(contexte["owner_b"], contexte["org_b"]),
    )
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "user_not_found"


async def test_attribution_a_un_membre_reste_autorisee(client: AsyncClient, contexte: dict):
    res = await client.post(
        f"/api/v1/rbac/organizations/{contexte['org_b']}/user-roles",
        json={"userId": contexte["membre_b"]["id"], "roleId": contexte["role_gerant_b"], "resourceType": None, "resourceId": None},
        headers=_entetes(contexte["owner_b"], contexte["org_b"]),
    )
    assert res.status_code == 201, res.text


# ---------------------------------------------------------------------------
# 5. Élévation de privilèges au sein d'une même organisation (403)
# ---------------------------------------------------------------------------


async def test_membre_sans_droit_ne_peut_pas_s_octroyer_le_role_proprietaire(client: AsyncClient, contexte: dict):
    attribution = await client.post(
        f"/api/v1/rbac/organizations/{contexte['org_b']}/user-roles",
        json={"userId": contexte["membre_b"]["id"], "roleId": contexte["role_gerant_b"], "resourceType": None, "resourceId": None},
        headers=_entetes(contexte["owner_b"], contexte["org_b"]),
    )
    assert attribution.status_code == 201, attribution.text

    escalade_role = await client.post(
        f"/api/v1/rbac/organizations/{contexte['org_b']}/user-roles",
        json={"userId": contexte["membre_b"]["id"], "roleId": contexte["role_proprietaire_b"], "resourceType": None, "resourceId": None},
        headers=_entetes(contexte["membre_b"], contexte["org_b"]),
    )
    assert escalade_role.status_code == 403
    assert escalade_role.json()["error"]["code"] == "permission_denied"

    escalade_grant = await client.post(
        f"/api/v1/rbac/organizations/{contexte['org_b']}/grants",
        json={"userId": contexte["membre_b"]["id"], "permissionCode": "zyloLiquid.station.read", "effect": "allow"},
        headers=_entetes(contexte["membre_b"], contexte["org_b"]),
    )
    assert escalade_grant.status_code == 403
    assert escalade_grant.json()["error"]["code"] == "permission_denied"


async def test_membre_sans_droit_ne_peut_pas_lire_les_grants_de_b(client: AsyncClient, contexte: dict):
    res = await client.get(
        f"/api/v1/rbac/organizations/{contexte['org_b']}/users/{contexte['owner_b']['id']}/grants",
        headers=_entetes(contexte["membre_b"], contexte["org_b"]),
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "permission_denied"
