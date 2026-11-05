"""BE-054 : application du moteur d'accessibilité effective aux routes de module.

Couvre les critères d'acceptation de la définition BE-054
(implementation-backend/tasks-modules-droits.md, section BE-054) :
- CA-1 : une route de module sans la dépendance `require_module_action` est détectée par
  un test d'inventaire (liste des routes `/organizations/{organization_id}/modules/{module_id}`) ;
- CA-2 : un identifiant de tenant injecté dans le corps ou un en-tête est ignoré ;
- CA-3 : une route de module appelée sans session renvoie 401 avant tout accès aux données ;
- CA-4 : une route appelée par un membre sans permission renvoie 403 ACCESS_DENIED sans effet
  de bord (aucune ligne modifiée) ;
- tenant absent : 404 ; capacité non déclarée : refus fail closed (QE-MOD-14).

Les tests de dépendance utilisent une petite application FastAPI qui ne porte que la garde :
la question testée est celle de la garde, pas d'une route métier. Les tests de route réelle
utilisent l'application complète. Aucun test n'est sauté.
"""

import uuid

import pytest
from fastapi import Body, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, engine
from app.core.errors import register_exception_handlers
from app.identity.models import OrganizationUser, User
from app.main import app as application_complete
from app.modules_registry.models import Module, OrganizationModule
from app.modules_registry.service import get_or_create_module, grant_module_permissions_to_owner
from app.rbac import garde_acces_module
from app.rbac.garde_acces_module import require_module_action
from app.rbac.service import get_or_create_permission
from tests.route_inventory import _dependances, _iter_routes

NOM_GARDE = "require_module_action"

# Routes de module qui portent leur tenant dans le chemin : toutes doivent porter la garde.
PREFIXE_ROUTES_MODULE = "/api/v1/organizations/{organization_id}/modules/{module_id}"

# Exceptions explicites (pas de saut silencieux) : routes de module dont le tenant ou le module
# n'est pas dans le chemin. La règle « tenant lu uniquement dans le chemin » ne peut pas s'y
# appliquer telle quelle. Chaque entrée renvoie à une question ouverte à trancher.
ROUTES_HORS_CHEMIN: dict[str, str] = {
    "GET /api/v1/organizations/current/modules/{module_id}/access": "Tenant lu dans X-Organization-Id (BE-009). QE-BE054-01.",
    "PUT /api/v1/organizations/current/modules/{module_id}/activation": "Tenant lu dans X-Organization-Id (BE-009). QE-BE054-01.",
    "POST /api/v1/modules/organizations/{organization_id}/activate": "Module désigné dans le corps (moduleCode). QE-BE054-02.",
    "POST /api/v1/modules/organizations/{organization_id}/deactivate": "Module désigné dans le corps (moduleCode). QE-BE054-02.",
}


class _CodesConnusDeTest:
    """Liste des codes de module reconnus, étendue aux seuls modules synthétiques de ce test.

    Même mécanisme que BE-053 : un code `be054...` absent de `CODES_MODULES_CONNUS` serait
    classé inconnu et refusé avant toute évaluation. Seul le préfixe `be054` est ouvert.
    """

    def __init__(self, reels: frozenset[str]):
        self._reels = reels

    def __contains__(self, code: object) -> bool:
        return code in self._reels or (isinstance(code, str) and code.startswith("be054"))


@pytest.fixture(autouse=True)
def _modules_de_test_reconnus(monkeypatch):
    from app.modules_registry import etats

    monkeypatch.setattr(etats, "CODES_MODULES_CONNUS", _CodesConnusDeTest(etats.CODES_MODULES_CONNUS))


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    await engine.dispose()
    yield
    await engine.dispose()


# ---------------------------------------------------------------------------
# Données : module, permission, activation, propriétaire, membre sans rôle.
# ---------------------------------------------------------------------------


async def _module_actif(organisation_id: str, *, avec_permission: bool = True) -> tuple[str, str]:
    """Crée un module synthétique actif pour l'organisation ; renvoie (code, permission)."""
    suffixe = uuid.uuid4().hex[:10]
    code = f"be054{suffixe}"
    permission = f"be054{suffixe}.dossier.read"
    async with AsyncSessionLocal() as db:
        await get_or_create_module(db, code=code, name="Module BE-054", description="Application du moteur")
        await get_or_create_permission(db, code=permission, module_code=code, description="BE-054")
        db.add(OrganizationModule(organizationId=uuid.UUID(organisation_id), moduleCode=code, status="active"))
        await db.flush()
        if avec_permission:
            await grant_module_permissions_to_owner(db, uuid.UUID(organisation_id), code)
        await db.commit()
    return code, permission


async def _id_module_catalogue(code: str) -> str:
    async with AsyncSessionLocal() as db:
        return str((await db.execute(select(Module.id).where(Module.code == code))).scalar_one())


async def _utilisateur(client: AsyncClient) -> dict:
    email = f"be054-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "BE-054"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return {"email": email, "accessToken": login.json()["accessToken"]}


async def _rattacher_sans_role(email: str, organisation_id: str) -> None:
    """Rattache l'utilisateur à l'organisation sans aucun rôle (membre sans permission)."""
    async with AsyncSessionLocal() as db:
        utilisateur = (await db.execute(select(User).where(User.email == email))).scalar_one()
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=utilisateur.id))
        await db.commit()


async def _organisation(client: AsyncClient, utilisateur: dict) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['accessToken']}"}
    res = await client.post(
        "/api/v1/organizations", json={"name": "Org BE-054", "slug": f"be054-{uuid.uuid4().hex[:8]}"}, headers=entetes
    )
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _compter(table) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(func.count()).select_from(table))).scalar_one()


# ---------------------------------------------------------------------------
# Application de test : une seule route par verbe, protégée par la garde seule.
# ---------------------------------------------------------------------------


def _application_de_test(action: str, *, exige_entitlement: bool | None) -> FastAPI:
    garde = require_module_action(action, exige_entitlement=exige_entitlement)
    mini = FastAPI()
    # Sans ces gestionnaires, AppError remonte au client de test au lieu de produire 403/404.
    register_exception_handlers(mini)

    @mini.get("/t/{organization_id}/modules/{module_id}", dependencies=[Depends(garde)])
    async def lire(organization_id: uuid.UUID, module_id: uuid.UUID) -> dict:
        return {"ok": True}

    @mini.post("/t/{organization_id}/modules/{module_id}", dependencies=[Depends(garde)])
    async def ecrire(organization_id: uuid.UUID, module_id: uuid.UUID, corps: dict = Body(default={})) -> dict:
        return {"ok": True, "corps": corps}

    return mini


async def _appeler(mini: FastAPI, methode: str, chemin: str, **kwargs) -> object:
    async with AsyncClient(transport=ASGITransport(app=mini), base_url="http://test") as ac:
        return await ac.request(methode, chemin, **kwargs)


# ---------------------------------------------------------------------------
# CA-1 : inventaire des routes de module.
# ---------------------------------------------------------------------------


def _porte_la_garde(route) -> bool:
    return any(getattr(appel, "__qualname__", "").startswith(NOM_GARDE) for appel in _dependances(route.dependant, []))


def test_ca1_toutes_les_routes_de_module_portent_la_garde():
    """Toute route `/organizations/{organization_id}/modules/{module_id}` porte la garde ;
    les seules routes de module sans garde sont celles de ROUTES_HORS_CHEMIN (exceptions datées)."""
    manquantes = []
    vues = set()
    for chemin, route, _ctx_deps in _iter_routes(application_complete.router):
        for methode in sorted(route.methods):
            cle = f"{methode} {chemin}"
            if cle in ROUTES_HORS_CHEMIN:
                vues.add(cle)
                continue
            if PREFIXE_ROUTES_MODULE in chemin and not _porte_la_garde(route):
                manquantes.append(cle)
            if "/current/modules/{module_id}" in chemin and not _porte_la_garde(route):
                manquantes.append(cle)
    assert manquantes == [], f"Routes de module sans {NOM_GARDE} : {manquantes}"
    assert vues == set(ROUTES_HORS_CHEMIN), "Une exception de ROUTES_HORS_CHEMIN ne correspond plus à une route réelle"


# ---------------------------------------------------------------------------
# CA-2 : le tenant vient du chemin, jamais du corps ni d'un en-tête.
# ---------------------------------------------------------------------------


async def test_ca2_tenant_injecte_dans_le_corps_ou_l_en_tete_est_ignore(client: AsyncClient):
    proprietaire = await _utilisateur(client)
    org_a = await _organisation(client, proprietaire)
    org_b = await _organisation(client, proprietaire)
    code, permission = await _module_actif(org_a["id"])
    module_id = await _id_module_catalogue(code)
    mini = _application_de_test(permission, exige_entitlement=False)
    chemin = f"/t/{org_a['id']}/modules/{module_id}"
    entetes = {"Authorization": f"Bearer {proprietaire['accessToken']}"}

    # En-tête désignant org_b (où le propriétaire est aussi membre) : ignoré, le périmètre reste org_a.
    res = await _appeler(mini, "GET", chemin, headers={**entetes, "X-Organization-Id": org_b["id"]})
    assert res.status_code == 200, res.text

    # Corps désignant org_b : ignoré, le corps est rendu tel quel sans effet sur le périmètre.
    res = await _appeler(
        mini, "POST", chemin, headers=entetes, json={"organizationId": org_b["id"], "tenantId": org_b["id"]}
    )
    assert res.status_code == 200, res.text


async def test_ca2_un_corps_qui_designe_un_autre_tenant_n_accorde_rien(client: AsyncClient):
    """Membre de org_b seulement, mais org_a dans le chemin : le corps ne lui ouvre pas org_a."""
    autre = await _utilisateur(client)
    org_b = await _organisation(client, autre)
    proprietaire = await _utilisateur(client)
    org_a = await _organisation(client, proprietaire)
    code, permission = await _module_actif(org_a["id"])
    module_id = await _id_module_catalogue(code)
    mini = _application_de_test(permission, exige_entitlement=False)

    res = await _appeler(
        mini,
        "POST",
        f"/t/{org_a['id']}/modules/{module_id}",
        headers={"Authorization": f"Bearer {autre['accessToken']}", "X-Organization-Id": org_b["id"]},
        json={"organizationId": org_b["id"]},
    )
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "organization_not_found", res.text


# ---------------------------------------------------------------------------
# CA-3 : sans session, 401 avant tout accès aux données.
# ---------------------------------------------------------------------------


async def test_ca3_sans_session_401_avant_tout_acces_aux_donnees(client: AsyncClient, monkeypatch):
    proprietaire = await _utilisateur(client)
    org = await _organisation(client, proprietaire)
    code, permission = await _module_actif(org["id"])
    module_id = await _id_module_catalogue(code)

    appels = []

    async def espion(*args, **kwargs):
        appels.append(1)
        raise AssertionError("le moteur ne doit pas être appelé sans session")

    monkeypatch.setattr(garde_acces_module, "evaluer_acces_effectif", espion)
    mini = _application_de_test(permission, exige_entitlement=False)
    res = await _appeler(mini, "GET", f"/t/{org['id']}/modules/{module_id}")
    assert res.status_code == 401, res.text
    assert appels == []


# ---------------------------------------------------------------------------
# Tenant absent et refus : 404, puis 403 ACCESS_DENIED sans écriture.
# ---------------------------------------------------------------------------


async def test_tenant_absent_renvoie_404(client: AsyncClient):
    proprietaire = await _utilisateur(client)
    org = await _organisation(client, proprietaire)
    code, permission = await _module_actif(org["id"])
    module_id = await _id_module_catalogue(code)
    etranger = await _utilisateur(client)

    mini = _application_de_test(permission, exige_entitlement=False)
    res = await _appeler(
        mini, "GET", f"/t/{org['id']}/modules/{module_id}", headers={"Authorization": f"Bearer {etranger['accessToken']}"}
    )
    assert res.status_code == 404, res.text


async def test_ca4_membre_sans_permission_403_access_denied_sans_ecriture(client: AsyncClient):
    proprietaire = await _utilisateur(client)
    org = await _organisation(client, proprietaire)
    code, permission = await _module_actif(org["id"])
    module_id = await _id_module_catalogue(code)
    membre = await _utilisateur(client)
    await _rattacher_sans_role(membre["email"], org["id"])

    lignes_avant = (await _compter(OrganizationModule.__table__), await _compter(OrganizationUser.__table__))
    mini = _application_de_test(permission, exige_entitlement=False)
    res = await _appeler(
        mini,
        "POST",
        f"/t/{org['id']}/modules/{module_id}",
        headers={"Authorization": f"Bearer {membre['accessToken']}"},
        json={"moduleCode": code},
    )
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "ACCESS_DENIED", res.text
    lignes_apres = (await _compter(OrganizationModule.__table__), await _compter(OrganizationUser.__table__))
    assert lignes_apres == lignes_avant


async def test_capacite_non_declaree_est_refusee_sans_entitlement_fail_closed(client: AsyncClient):
    """QE-MOD-14 : sans déclaration, la garde exige un entitlement ; l'organisation de test n'en a pas."""
    proprietaire = await _utilisateur(client)
    org = await _organisation(client, proprietaire)
    code, permission = await _module_actif(org["id"])
    module_id = await _id_module_catalogue(code)

    mini = _application_de_test(permission, exige_entitlement=None)
    res = await _appeler(
        mini, "GET", f"/t/{org['id']}/modules/{module_id}", headers={"Authorization": f"Bearer {proprietaire['accessToken']}"}
    )
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "ACCESS_DENIED", res.text


# ---------------------------------------------------------------------------
# Route réelle : la garde est appliquée à une route de module du registre.
# ---------------------------------------------------------------------------


async def test_route_reelle_membre_sans_permission_403_access_denied(client: AsyncClient, zylo_liquid_organization: dict):
    proprietaire = await _utilisateur(client)
    org = await _organisation(client, proprietaire)
    module_id = await _id_module_catalogue("zylo_liquid")
    membre = await _utilisateur(client)
    await _rattacher_sans_role(membre["email"], org["id"])

    res = await client.get(
        f"/api/v1/organizations/{org['id']}/modules/{module_id}/permissions",
        headers={"Authorization": f"Bearer {membre['accessToken']}", "X-Organization-Id": org["id"]},
    )
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "ACCESS_DENIED", res.text
