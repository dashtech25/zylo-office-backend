"""Suite transverse de refus et d'isolation des routes de modules (BE-060).

Intention : une seule suite qui couvre, route par route, les routes de module des
tâches BE-042 à BE-059, sans liste écrite à la main. Le périmètre est lu depuis
l'inventaire réel de l'application (`tests/route_inventory.py`) par familles de
chemins. Chaque route du périmètre produit un cas par critère :

- CA-1 (403) : un membre actif de l'organisation A, sans rôle, reçoit 403 sur
  chaque route du périmètre qui exige une permission. Les routes de lecture
  ouvertes à tout membre actif sont listées dans `LECTURE_OUVERTE_AUX_MEMBRES`
  avec leur justification, et ne sont pas testées en 403.
- CA-2 (404) : le propriétaire de A, qui a tous les droits sur A, appelle une
  route dont le chemin porte `{organization_id}` = organisation B. Réponse 404,
  sans révéler l'existence de B, et sans écriture.
- CA-3 (401) : chaque route de mutation (POST, PUT, PATCH, DELETE) répond 401
  sans jeton d'authentification.
- CA-4 (décompte) : la suite est lancée en un seul run ; `test_decompte_du_perimetre`
  fixe le nombre de routes par famille. Une route ajoutée au périmètre sans
  mise à jour de ce décompte fait échouer le test.

Hors périmètre, avec motif :
- routes publiques du catalogue (`GET /api/v1/modules`, `GET /api/v1/catalog/...`,
  BE-043) : lecture publique par décision produit, sans tenant ;
- routes de facturation `/api/v1/billing/organizations/{organization_id}` :
  couvertes par `tests/test_isolation_organisations.py` (BE-026, BE-088) ;
- routes d'affectation de rôles par module (`/api/v1/rbac/...`) : couvertes par
  `tests/test_module_assignment.py` et `tests/test_authorization_matrix.py` (T-018 à T-022) ;
- BE-057 et BE-059 : aucune route (notification et tâche planifiée).

Les refus attendus viennent de la définition (403 PERMISSION_DENIED ou
ACCESS_DENIED, 404 non révélateur, 401). Un écart n'est jamais corrigé ici en
affaiblissant l'assertion : il est signalé dans la documentation des QE.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.main import app
from tests.route_inventory import inventaire
from tests.test_module_assignment import _add_member, _h, _new_user

# Familles de chemins couvertes (BE-042 à BE-059 : routes de modules).
FAMILLES_DU_PERIMETRE = (
    "/api/v1/admin/modules",
    "/api/v1/organizations/{organization_id}/modules",
    "/api/v1/organizations/{organization_id}/entitlements",
    "/api/v1/organizations/{organization_id}/module-audit",
    "/api/v1/organizations/current/modules",
    "/api/v1/modules/organizations/{organization_id}",
)

# Routes dont la lecture est ouverte à tout membre actif, sans permission : un
# membre sans rôle y reçoit 200, donc pas de 403 attendu. Motif par route.
LECTURE_OUVERTE_AUX_MEMBRES: dict[str, str] = {
    "GET /api/v1/organizations/current/modules": "Liste des modules de l'organisation courante : portée membre actif (BE-053).",
    "GET /api/v1/organizations/current/modules/{module_id}/access": "Accès effectif de l'utilisateur courant à un module : portée membre actif (BE-053).",
}

# Chemins portant {organization_id} : sujets du CA-2.
TAG_ORGANISATION = "{organization_id}"


def _dans_le_perimetre(chemin: str) -> bool:
    return any(chemin == f or chemin.startswith(f + "/") for f in FAMILLES_DU_PERIMETRE)


def _routes_du_perimetre() -> list:
    return [i for i in inventaire(app) if _dans_le_perimetre(i.path)]


ROUTES = _routes_du_perimetre()
ROUTES_A_PERMISSION = [r for r in ROUTES if _identifiant(r) not in LECTURE_OUVERTE_AUX_MEMBRES]
ROUTES_AVEC_ORGANISATION = [r for r in ROUTES if TAG_ORGANISATION in r.path]
ROUTES_DE_MUTATION = [r for r in ROUTES if r.method in ("POST", "PUT", "PATCH", "DELETE")]


def _chemin_concret(chemin: str, organisation_id: str) -> str:
    """Remplace chaque paramètre de chemin : organisation donnée, codes de module
    lisibles, identifiants inconnus (uuid) pour le reste. Le contrôle d'accès
    s'exécute avant la recherche de l'objet ; un identifiant inconnu n'affaiblit
    donc pas le refus attendu."""
    sortie = chemin
    while "{" in sortie:
        debut = sortie.index("{")
        fin = sortie.index("}", debut)
        nom = sortie[debut + 1:fin]
        if nom == "organization_id":
            valeur = organisation_id
        elif nom == "module_code":
            valeur = "zylo_liquid"
        else:
            valeur = str(uuid.uuid4())
        sortie = sortie[:debut] + valeur + sortie[fin + 1:]
    return sortie


def _identifiant(route) -> str:
    return f"{route.method} {route.path}"


@pytest.fixture
async def mondes_be060(client: AsyncClient, registered_user: dict, organization: dict) -> dict:
    """Deux organisations (A, B) et deux acteurs.

    - propriétaire de A : tous les droits sur A, aucun sur B ;
    - sans_droit : membre actif de A, sans aucun rôle, non membre de B.
    Aucun module n'est activé : les refus attendus ne dépendent pas de l'état du module."""
    proprietaire_a = {"token": registered_user["accessToken"]}
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {proprietaire_a['token']}"})
    proprietaire_a["id"] = me.json()["id"]

    proprietaire_b = await _new_user(client, "Propriétaire B BE-060")
    org_b = (
        await client.post(
            "/api/v1/organizations",
            json={"name": "Org B BE-060", "slug": f"org-b-be060-{uuid.uuid4().hex[:8]}"},
            headers={"Authorization": f"Bearer {proprietaire_b['token']}"},
        )
    ).json()["id"]

    sans_droit = await _new_user(client, "Sans droit BE-060")
    await _add_member(organization["id"], sans_droit["id"])

    return {
        "org_a": organization["id"],
        "org_b": org_b,
        "proprietaire_a": proprietaire_a,
        "sans_droit": sans_droit,
    }


# ---------------------------------------------------------------------------
# CA-1 : 403 pour un membre sans rôle, sur chaque route du périmètre à permission
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("route", [pytest.param(r, id=_identifiant(r)) for r in ROUTES_A_PERMISSION])
async def test_ca1_membre_sans_role_refuse_403(client: AsyncClient, mondes_be060: dict, route):
    """Un membre actif sans rôle n'exécute aucune route du périmètre à permission."""
    acteur = mondes_be060["sans_droit"]
    chemin = _chemin_concret(route.path, mondes_be060["org_a"])
    res = await client.request(
        route.method,
        chemin,
        headers=_h(acteur["token"], mondes_be060["org_a"]),
        json={},
    )
    assert res.status_code == 403, f"{route.method} {chemin} -> {res.status_code} {res.text}"


# ---------------------------------------------------------------------------
# CA-2 : isolation tenant, acteur de A sur B = 404
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("route", [pytest.param(r, id=_identifiant(r)) for r in ROUTES_AVEC_ORGANISATION])
async def test_ca2_acteur_de_a_sur_b_obtient_404(client: AsyncClient, mondes_be060: dict, route):
    """Le propriétaire de A ne voit ni n'écrit rien sur B : 404 (organisation non trouvée
    pour cet acteur), y compris avec un en-tête X-Organization-Id de A (incohérence)."""
    acteur = mondes_be060["proprietaire_a"]
    chemin = _chemin_concret(route.path, mondes_be060["org_b"])
    res = await client.request(
        route.method,
        chemin,
        headers=_h(acteur["token"], mondes_be060["org_a"]),
        json={},
    )
    assert res.status_code == 404, f"{route.method} {chemin} -> {res.status_code} {res.text}"


# ---------------------------------------------------------------------------
# CA-3 : 401 sans authentification, sur chaque route de mutation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("route", [pytest.param(r, id=_identifiant(r)) for r in ROUTES_DE_MUTATION])
async def test_ca3_mutation_sans_authentification_401(client: AsyncClient, mondes_be060: dict, route):
    """Une mutation sans jeton d'authentification répond 401, avant toute lecture de la cible."""
    chemin = _chemin_concret(route.path, mondes_be060["org_a"])
    res = await client.request(route.method, chemin, json={})
    assert res.status_code == 401, f"{route.method} {chemin} -> {res.status_code} {res.text}"


# ---------------------------------------------------------------------------
# CA-4 : décompte exact du périmètre (tripwire)
# ---------------------------------------------------------------------------

def test_decompte_du_perimetre():
    """Le décompte par catégorie est figé : toute route ajoutée à ces familles fait
    échouer ce test jusqu'à mise à jour explicite du décompte et de la suite."""
    par_methode: dict[str, int] = {}
    for route in ROUTES:
        par_methode[route.method] = par_methode.get(route.method, 0) + 1
    assert len(ROUTES) == 28, par_methode
    assert len(ROUTES_AVEC_ORGANISATION) == 19, len(ROUTES_AVEC_ORGANISATION)
    assert len(ROUTES_DE_MUTATION) == 17, len(ROUTES_DE_MUTATION)
