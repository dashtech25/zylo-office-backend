"""BE-147 : garde transversale anti cross-tenant sur les routes d'administration.

Tests écrits d'après la définition `### BE-147` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Couverture :
- CA-1 (isolation tenant) : deux tenants ; l'affectation du tenant A ne donne
  accès à aucune ressource du tenant B. Testé sur la route d'administration qui
  porte un identifiant d'organisation dans son chemin.
- CA-2 (refus de droit) : un sujet sans affectation reçoit 403 sur toutes les
  routes `/api/v1/admin` (test de couverture de l'ensemble des routes).
- CA-3 (portée déclarée) : toute route `/api/v1/admin` déclare la dépendance
  `require_admin_scope` ; une route sans portée déclarée fait échouer le test.
- CA-4 (audit du refus) : chaque refus cross-tenant produit une entrée
  d'audit `result = refused` (test de présence).

Décision de chemin : routes opérateur sous `/api/v1/admin` (définition, décision).
Aucune fixture métier lourde : les ressources sont créées par les API existantes
(organisations) ; une ressource métier complexe non montable est consignée en QE.
"""

import re
import uuid

from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.main import app
from app.operator.scope import require_admin_scope

PREFIXE_ADMIN = "/api/v1/admin"
ACTION_REFUS_CROSS_TENANT = "admin.scope.cross_tenant_refused"
MOT_DP_CHEMIN = re.compile(r"\{[^}]+\}")


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


def _routes_admin():
    """Couples (méthode, chemin, dépendances) de toutes les routes `/api/v1/admin`.

    Parcours récursif des routeurs imbriqués (FastAPI `_IncludedRouter`), comme
    `tests/route_inventory.py`.
    """
    def _parcours(routes, prefixe="", deps_montage=()):
        # Les dépendances de montage (`include_router(..., dependencies=...)`) font
        # partie de la chaîne réelle de chaque route, comme dans tests/route_inventory.py.
        for route in routes:
            if isinstance(route, APIRoute):
                yield route, prefixe + route.path, deps_montage
            elif type(route).__name__ == "_IncludedRouter":
                ctx = route.include_context
                montage = tuple(getattr(d, "dependency", None) for d in (ctx.dependencies or []))
                yield from _parcours(ctx.included_router.routes, prefixe + ctx.prefix, deps_montage + montage)

    trouvees = []
    for route, chemin, deps_montage in _parcours(app.router.routes):
        if not chemin.startswith(PREFIXE_ADMIN):
            continue
        appels = list(deps_montage)

        def _collecte(dependant):
            for sous in dependant.dependencies:
                appels.append(sous.call)
                _collecte(sous)

        _collecte(route.dependant)
        for methode in sorted(route.methods):
            trouvees.append((methode, chemin, appels))
    return trouvees


async def _moi(client: AsyncClient, utilisateur: dict) -> str:
    res = await client.get("/api/v1/auth/me", headers=_entetes(utilisateur))
    return res.json()["id"]


async def _autre_organisation(client: AsyncClient) -> str:
    """Crée un second tenant (B) avec un autre compte qui en est propriétaire."""
    email = f"be147-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    mot_de_passe = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": mot_de_passe, "fullName": "Tenant B"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": mot_de_passe})
    proprietaire = {"accessToken": login.json()["accessToken"]}
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"tenant-b-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    return res.json()["id"]


async def _nombre_refus_cross_tenant(organization_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            text(
                'SELECT count(*) FROM audit_event WHERE action = :action AND result = :result AND "organizationId" = :org'
            ).bindparams(action=ACTION_REFUS_CROSS_TENANT, result="refused", org=uuid.UUID(organization_id))
        ) or 0


def test_be147_ca3_chaque_route_admin_declare_sa_portee():
    """CA-3 : toute route `/api/v1/admin` déclare `require_admin_scope`.

    Une route sans portée déclarée échoue ce test (test de build).
    """
    sans_portee = [
        f"{methode} {chemin}"
        for methode, chemin, appels in _routes_admin()
        if require_admin_scope not in appels
    ]

    assert sans_portee == []


async def test_be147_ca2_sujet_sans_affectation_403_sur_toutes_les_routes_admin(client: AsyncClient, registered_user: dict, monkeypatch):
    """CA-2 : un sujet sans affectation reçoit 403 sur chaque route `/api/v1/admin`.

    Les identifiants de chemin sont des UUID aléatoires : le refus doit venir de
    la garde, avant toute lecture de ressource.
    """
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(uuid.uuid4()))

    echecs = []
    for methode, chemin, _ in _routes_admin():
        url = MOT_DP_CHEMIN.sub(lambda _m: str(uuid.uuid4()), chemin)
        res = await client.request(methode, url, json={}, headers=_entetes(registered_user))
        if res.status_code != 403:
            echecs.append(f"{methode} {chemin} -> {res.status_code}")

    assert echecs == []


async def test_be147_ca1_affectation_tenant_a_sur_ressource_tenant_b_403(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    """CA-1 : l'opérateur de portée `tenant:A` ne lit pas le tenant B (403).

    Route testée : `GET /api/v1/admin/organizations/{organization_id}`, la seule
    route d'administration portant un identifiant de tenant dans son chemin.
    """
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", await _moi(client, registered_user))
    tenant_b = await _autre_organisation(client)

    res = await client.get(
        f"/api/v1/admin/organizations/{tenant_b}",
        headers={**_entetes(registered_user), "X-Admin-Scope": f"tenant:{organization['id']}"},
    )

    assert res.status_code == 403


async def test_be147_ca4_refus_cross_tenant_produit_une_entree_d_audit(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    """CA-4 : le refus cross-tenant de CA-1 laisse une entrée `refused` dans `audit_event`.

    Le tenant de l'entrée est le tenant ciblé (B), l'acteur est l'appelant.
    """
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", await _moi(client, registered_user))
    tenant_b = await _autre_organisation(client)
    avant = await _nombre_refus_cross_tenant(tenant_b)

    res = await client.get(
        f"/api/v1/admin/organizations/{tenant_b}",
        headers={**_entetes(registered_user), "X-Admin-Scope": f"tenant:{organization['id']}"},
    )

    assert res.status_code == 403
    assert await _nombre_refus_cross_tenant(tenant_b) == avant + 1
