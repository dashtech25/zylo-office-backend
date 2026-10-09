"""Contrôle d'accès des routes de module (T-019, achèvement de T-023).

Intention : prouver, sur la vraie base de test et via HTTP, que
- toute route de module gardée refuse un membre sans rôle (403 permission_denied),
  et que le propriétaire passe toutes les gardes ;
- chaque rôle par défaut garde l'accès à ses parcours principaux, et ne reçoit
  pas les accès qu'il n'a jamais eus (refus explicite) ;
- une affectation limitée à une station passe les gardes de liste (le service
  filtre par station) sans recevoir les routes org-entière.

Les parcours appellent la route avec un corps vide : la garde de route s'exécute
avant la validation du corps. Ces tests vérifient donc l'AUTORISATION (garde et
portée), pas la logique métier, couverte par les tests de chaque module.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.rbac.models import Role, UserRole
from tests.route_inventory import inventaire
from tests.test_module_assignment import LIQUID, TANKER, _activate, _add_member, _h, _new_user

# Routes qui ouvrent un flux infini (SSE) : le test du propriétaire les exclut,
# le test du membre sans rôle les couvre (la garde répond avant le flux).
ROUTES_FLUX = ("live-positions",)


def _chemin_concret(chemin: str) -> str:
    """Remplace chaque paramètre de chemin par un identifiant inconnu (404 attendu après garde)."""
    out = chemin
    while "{" in out:
        debut = out.index("{")
        fin = out.index("}", debut)
        out = out[:debut] + str(uuid.uuid4()) + out[fin + 1:]
    return out


def _gardees() -> list:
    return [i for i in inventaire(app) if i.module_routes and i.permissions]


def _est_refus_permission(res) -> bool:
    return res.status_code == 403 and res.json().get("error", {}).get("code") == "permission_denied"


async def _role_par_defaut(org_id: str, code: str) -> str:
    async with AsyncSessionLocal() as db:
        role = (
            await db.execute(select(Role).where(Role.organizationId == uuid.UUID(org_id), Role.code == code))
        ).scalar_one()
        return str(role.id)


async def _membre(client: AsyncClient, owner: dict, org_id: str, module: str, role_code: str | None) -> dict:
    """Membre de l'organisation, avec (ou sans) le rôle par défaut donné, en portée organisation.

    Affectation directe en base : le rôle `zylo_tanker_operator` contient GPS_DEVICE_READ, dont le
    `permission.moduleCode` vaut `zylo_liquid` ; le contrôle d'affectation par module (T-018) refuse
    alors l'affectation par API. Cette limite est documentée dans roles-par-module.md (§7).
    """
    membre = await _new_user(client, f"Membre {role_code or 'sans rôle'}")
    await _add_member(org_id, membre["id"])
    if role_code:
        role_id = await _role_par_defaut(org_id, role_code)
        async with AsyncSessionLocal() as db:
            db.add(UserRole(userId=uuid.UUID(membre["id"]), organizationId=uuid.UUID(org_id), roleId=uuid.UUID(role_id)))
            await db.commit()
    return membre


@pytest.fixture
async def organisation_modules(client: AsyncClient, registered_user: dict, organization: dict) -> dict:
    """Organisation propriétaire avec les modules zylo_liquid et zylo_tanker activés."""
    owner = {"id": None, "token": registered_user["accessToken"]}
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {owner['token']}"})
    owner["id"] = me.json()["id"]
    org_id = organization["id"]
    await _activate(client, owner, org_id, LIQUID)
    await _activate(client, owner, org_id, TANKER)
    return {"owner": owner, "org_id": org_id}


async def test_membre_sans_role_refuse_toute_route_gardee(client: AsyncClient, organisation_modules: dict):
    """Aucune route gardée ne répond à un membre sans rôle autrement que par 403 permission_denied."""
    org_id = organisation_modules["org_id"]
    membre = await _membre(client, organisation_modules["owner"], org_id, LIQUID, None)
    fautives = []
    for info in _gardees():
        res = await client.request(
            info.method, _chemin_concret(info.path), headers=_h(membre["token"], org_id), json={} if info.method != "GET" else None
        )
        # Une route à identifiant de ressource résout d'abord la ressource (404 si inconnue) :
        # le critère est « aucun succès », pas « 403 permission_denied » sur un identifiant inventé.
        if res.status_code < 400:
            fautives.append(f"{info.cle} -> {res.status_code}")
    assert fautives == [], f"Routes gardées accessibles sans permission : {fautives}"


async def test_proprietaire_passe_toutes_les_gardes(client: AsyncClient, organisation_modules: dict):
    """Le propriétaire détient les permissions de chaque module activé : aucune garde ne le refuse."""
    org_id = organisation_modules["org_id"]
    owner = organisation_modules["owner"]
    refus = []
    for info in _gardees():
        if any(fragment in info.path for fragment in ROUTES_FLUX):
            continue
        res = await client.request(
            info.method, _chemin_concret(info.path), headers=_h(owner["token"], org_id), json={} if info.method != "GET" else None
        )
        if _est_refus_permission(res):
            refus.append(f"{info.cle} -> {res.json()['error']['message']}")
    assert refus == [], f"Le propriétaire est refusé par une garde : {refus}"


# Parcours principaux par rôle par défaut (roles_seed.py). Chaque entrée : (méthode, chemin).
PARCOURS = {
    "zylo_liquid_network_read": (
        LIQUID,
        [("GET", "/api/v1/zylo-liquid/suppliers"), ("GET", "/api/v1/zylo-liquid/carriers"), ("GET", "/api/v1/zylo-liquid/trucks"),
         ("GET", "/api/v1/zylo-liquid/gps-devices"), ("GET", "/api/v1/zylo-liquid/tracking-locations")],
        [("POST", "/api/v1/zylo-liquid/suppliers"), ("GET", "/api/v1/zylo-liquid/sales")],
    ),
    "zylo_liquid_station_admin": (
        LIQUID,
        [("GET", "/api/v1/zylo-liquid/stations"), ("GET", "/api/v1/zylo-liquid/pumps"), ("GET", "/api/v1/zylo-liquid/delivery-declarations"),
         ("POST", "/api/v1/zylo-liquid/sales"), ("POST", "/api/v1/zylo-liquid/purchase-orders"), ("GET", "/api/v1/zylo-liquid/interventions")],
        [("POST", "/api/v1/zylo-liquid/suppliers")],
    ),
    "zylo_liquid_team_lead": (
        LIQUID,
        [("GET", "/api/v1/zylo-liquid/deliveries"), ("GET", "/api/v1/zylo-liquid/delivery-declarations"),
         ("POST", "/api/v1/zylo-liquid/interventions"), ("GET", "/api/v1/zylo-liquid/leak-events"),
         ("GET", "/api/v1/zylo-liquid/shift-cash-declarations"), ("GET", "/api/v1/zylo-liquid/alerts")],
        [("POST", "/api/v1/zylo-liquid/shift-cash-declarations"), ("POST", "/api/v1/zylo-liquid/sales")],
    ),
    "zylo_liquid_cashier": (
        LIQUID,
        [("GET", "/api/v1/zylo-liquid/sales"), ("POST", "/api/v1/zylo-liquid/sales"), ("POST", "/api/v1/zylo-liquid/payments"),
         ("POST", "/api/v1/zylo-liquid/product-sales"), ("GET", "/api/v1/zylo-liquid/tanks"), ("GET", "/api/v1/zylo-liquid/pumps")],
        [("POST", "/api/v1/zylo-liquid/suppliers"), ("POST", "/api/v1/zylo-liquid/shift-cash-declarations")],
    ),
    "zylo_liquid_pump_attendant": (
        LIQUID,
        [("GET", "/api/v1/zylo-liquid/alerts"), ("GET", "/api/v1/zylo-liquid/shift-cash-declarations"),
         ("POST", "/api/v1/zylo-liquid/shift-cash-declarations")],
        [("POST", "/api/v1/zylo-liquid/sales"), ("GET", "/api/v1/zylo-liquid/tanks"), ("GET", "/api/v1/zylo-liquid/deliveries")],
    ),
    "zylo_liquid_fleet_coordinator": (
        LIQUID,
        [("GET", "/api/v1/zylo-liquid/deliveries"), ("GET", "/api/v1/zylo-liquid/alerts")],
        [("GET", "/api/v1/zylo-liquid/tanks"), ("POST", "/api/v1/zylo-liquid/trucks")],
    ),
    "zylo_liquid_technician": (
        LIQUID,
        [("GET", "/api/v1/zylo-liquid/equipment"), ("POST", "/api/v1/zylo-liquid/interventions"),
         ("POST", "/api/v1/zylo-liquid/interventions/{id}/close"), ("GET", "/api/v1/zylo-liquid/technicians"),
         ("GET", "/api/v1/zylo-liquid/documents/by-entity")],
        [("POST", "/api/v1/zylo-liquid/sales"), ("POST", "/api/v1/zylo-liquid/suppliers")],
    ),
    "zylo_liquid_auditor": (
        LIQUID,
        [("GET", "/api/v1/zylo-liquid/sales"), ("GET", "/api/v1/zylo-liquid/receivables"), ("GET", "/api/v1/zylo-liquid/payments"),
         ("GET", "/api/v1/zylo-liquid/delivery-declarations"), ("GET", "/api/v1/zylo-liquid/regulatory-declarations"),
         ("GET", "/api/v1/zylo-liquid/reconciliation-records")],
        [("POST", "/api/v1/zylo-liquid/sales"), ("POST", "/api/v1/zylo-liquid/payments")],
    ),
    "zylo_liquid_hse": (
        LIQUID,
        [("GET", "/api/v1/zylo-liquid/incident-declarations"), ("POST", "/api/v1/zylo-liquid/incident-declarations"),
         ("POST", "/api/v1/zylo-liquid/regulatory-documents"), ("GET", "/api/v1/zylo-liquid/security-equipment"),
         ("POST", "/api/v1/zylo-liquid/security-equipment"), ("GET", "/api/v1/zylo-liquid/alerts")],
        [("POST", "/api/v1/zylo-liquid/sales"), ("GET", "/api/v1/zylo-liquid/deliveries")],
    ),
    "zylo_tanker_operator": (
        TANKER,
        [("GET", "/api/v1/zylo-tanker/vessels"), ("GET", "/api/v1/zylo-tanker/vessels/current-positions"),
         ("GET", "/api/v1/zylo-tanker/gps-devices"), ("GET", "/api/v1/zylo-tanker/tracking-locations"),
         ("GET", "/api/v1/zylo-tanker/tracking-settings")],
        [("POST", "/api/v1/zylo-tanker/vessels"), ("GET", "/api/v1/zylo-tanker/traccar-connection")],
    ),
}


@pytest.mark.parametrize("role_code", sorted(PARCOURS))
async def test_role_par_defaut_garde_ses_parcours(client: AsyncClient, organisation_modules: dict, role_code: str):
    module, autorises, refuses = PARCOURS[role_code]
    org_id = organisation_modules["org_id"]
    membre = await _membre(client, organisation_modules["owner"], org_id, module, role_code)
    manques, accessibles_a_tort = [], []
    for methode, chemin in autorises:
        res = await client.request(methode, _chemin_concret(chemin), headers=_h(membre["token"], org_id), json={} if methode != "GET" else None)
        if _est_refus_permission(res):
            manques.append(f"{methode} {chemin}")
    for methode, chemin in refuses:
        res = await client.request(methode, _chemin_concret(chemin), headers=_h(membre["token"], org_id), json={} if methode != "GET" else None)
        if not _est_refus_permission(res):
            accessibles_a_tort.append(f"{methode} {chemin} -> {res.status_code}")
    assert manques == [], f"{role_code} perd l'accès à un parcours principal : {manques}"
    assert accessibles_a_tort == [], f"{role_code} accède à une route qui ne lui revient pas : {accessibles_a_tort}"


async def test_affectation_station_passe_la_garde_de_liste(client: AsyncClient, organisation_modules: dict):
    """Un chef d'équipe limité à SA station passe la garde de liste (le service
    filtre par station) mais ne passe pas une route org-entière (fournisseurs)."""
    org_id = organisation_modules["org_id"]
    owner = organisation_modules["owner"]
    membre = await _membre(client, owner, org_id, LIQUID, None)
    role_id = await _role_par_defaut(org_id, "zylo_liquid_team_lead")
    async with AsyncSessionLocal() as db:
        db.add(UserRole(userId=uuid.UUID(membre["id"]), organizationId=uuid.UUID(org_id), roleId=uuid.UUID(role_id),
                        resourceType="station", resourceId=uuid.uuid4()))
        await db.commit()

    liste = await client.get("/api/v1/zylo-liquid/deliveries", headers=_h(membre["token"], org_id))
    assert liste.status_code == 200, liste.text

    org_entiere = await client.get("/api/v1/zylo-liquid/suppliers", headers=_h(membre["token"], org_id))
    assert _est_refus_permission(org_entiere)
