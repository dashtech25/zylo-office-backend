"""Matrice d'autorisation par module (T-023) : utilisateur x organisation x module x niveau.

Intention : la matrice est ÉCRITE À LA MAIN. Seules les autorisations attendues
sont listées (ALLOWED) ; toute autre combinaison doit être refusée (refus par
défaut). Un changement de règle casse un cas explicite, pas un générateur.

Mondes de test :
- org A : modules zylo_liquid, zylo_tanker et crm actifs ;
- org B : modules zylo_liquid et crm actifs, zylo_tanker INACTIF ;
- org C : aucun module actif.
Utilisateurs :
- lecteur : membre de A, rôle lecture sur zylo_liquid ;
- gestionnaire : membre de A, rôle gestion sur zylo_tanker, lecture sur crm ;
- externe : membre de B seulement, rôle lecture+gestion sur zylo_liquid (dans B) ;
- sans_droit : membre de A et de B, aucun rôle.
Niveaux : read et manage, par module (permission de référence du module).
"""

import uuid

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.permissions import STATION_MANAGE, STATION_READ
from app.modules.zylo_tanker.permissions import VESSEL_MANAGE, VESSEL_READ
from app.rbac.module_rights import user_has_module_permission
from tests.test_module_assignment import (
    CRM,
    CRM_MANAGE,
    CRM_READ,
    LIQUID,
    TANKER,
    _activate,
    _add_member,
    _deactivate,
    _ensure_crm,
    _h,
    _new_user,
    _put,
    _role,
)

PERMISSIONS = {
    LIQUID: {"read": STATION_READ, "manage": STATION_MANAGE},
    TANKER: {"read": VESSEL_READ, "manage": VESSEL_MANAGE},
    CRM: {"read": CRM_READ, "manage": CRM_MANAGE},
}

# Cas autorisés, écrits à la main : (utilisateur, organisation, module, niveau).
ALLOWED = {
    ("lecteur", "A", LIQUID, "read"),
    ("gestionnaire", "A", TANKER, "read"),
    ("gestionnaire", "A", TANKER, "manage"),
    ("gestionnaire", "A", CRM, "read"),
    ("externe", "B", LIQUID, "read"),
    ("externe", "B", LIQUID, "manage"),
}

USERS = ["lecteur", "gestionnaire", "externe", "sans_droit"]
ORGS = ["A", "B", "C"]
MODULES = [LIQUID, TANKER, CRM]
LEVELS = ["read", "manage"]


@pytest.fixture
async def monde(client: AsyncClient, registered_user: dict, organization: dict):
    """Construit les trois organisations, les modules activés et les utilisateurs."""
    await _ensure_crm()
    owner_a = {"id": None, "token": registered_user["accessToken"]}
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {owner_a['token']}"})
    owner_a["id"] = me.json()["id"]
    org_a = organization["id"]

    owner_b = await _new_user(client, "Propriétaire B")
    org_b = (
        await client.post("/api/v1/organizations", json={"name": "Org B", "slug": f"org-b-{uuid.uuid4().hex[:8]}"},
                          headers={"Authorization": f"Bearer {owner_b['token']}"})
    ).json()["id"]
    owner_c = await _new_user(client, "Propriétaire C")
    org_c = (
        await client.post("/api/v1/organizations", json={"name": "Org C", "slug": f"org-c-{uuid.uuid4().hex[:8]}"},
                          headers={"Authorization": f"Bearer {owner_c['token']}"})
    ).json()["id"]

    for module_code in (LIQUID, TANKER, CRM):
        await _activate(client, owner_a, org_a, module_code)
    await _activate(client, {"id": owner_b["id"], "token": owner_b["token"]}, org_b, LIQUID)
    await _activate(client, {"id": owner_b["id"], "token": owner_b["token"]}, org_b, CRM)
    # Le module tanker est activé puis désactivé dans B : aucun droit ne doit y survivre.
    await _activate(client, {"id": owner_b["id"], "token": owner_b["token"]}, org_b, TANKER)
    await _deactivate(client, {"id": owner_b["id"], "token": owner_b["token"]}, org_b, TANKER)

    orgs = {"A": (owner_a, org_a), "B": (owner_b, org_b), "C": (owner_c, org_c)}
    users = {name: await _new_user(client, name) for name in USERS}

    # Appartenances : lecteur, gestionnaire, sans_droit dans A ; externe dans B seulement ; sans_droit aussi dans B.
    for name in ("lecteur", "gestionnaire", "sans_droit"):
        await _add_member(org_a, users[name]["id"])
    await _add_member(org_b, users["externe"]["id"])
    await _add_member(org_b, users["sans_droit"]["id"])

    lecteur_a = await _role(client, owner_a, org_a, LIQUID, "lecteur_liquid", [STATION_READ])
    await _put(client, owner_a, org_a, LIQUID, users["lecteur"]["id"], lecteur_a["id"])
    gestion_tanker_a = await _role(client, owner_a, org_a, TANKER, "gestion_tanker", [VESSEL_READ, VESSEL_MANAGE])
    await _put(client, owner_a, org_a, TANKER, users["gestionnaire"]["id"], gestion_tanker_a["id"])
    lecture_crm_a = await _role(client, owner_a, org_a, CRM, "lecture_crm", [CRM_READ])
    await _put(client, owner_a, org_a, CRM, users["gestionnaire"]["id"], lecture_crm_a["id"])
    tout_liquid_b = await _role(client, owner_b, org_b, LIQUID, "tout_liquid", [STATION_READ, STATION_MANAGE])
    await _put(client, owner_b, org_b, LIQUID, users["externe"]["id"], tout_liquid_b["id"])

    return {"users": users, "orgs": orgs}


async def test_matrice_complete(monde: dict):
    """Un seul monde construit (la mise en place est coûteuse), toutes les combinaisons.
    Les échecs sont rassemblés pour montrer l'ensemble des écarts d'un coup."""
    ecarts = []
    cas = 0
    async with AsyncSessionLocal() as db:
        for user in USERS:
            for org in ORGS:
                for module in MODULES:
                    for level in LEVELS:
                        cas += 1
                        user_id = uuid.UUID(monde["users"][user]["id"])
                        org_id = uuid.UUID(monde["orgs"][org][1])
                        effective = await user_has_module_permission(db, user_id, org_id, module, PERMISSIONS[module][level])
                        attendu = (user, org, module, level) in ALLOWED
                        if effective is not attendu:
                            ecarts.append(f"{user} / org {org} / {module} / {level} : attendu {attendu}")
    assert cas == len(USERS) * len(ORGS) * len(MODULES) * len(LEVELS) == 72
    assert ecarts == [], ecarts


async def test_permission_d_un_autre_module_jamais_accordee(monde: dict):
    """Un droit de zylo_liquid n'ouvre jamais une permission de tanker, même si le rôle existe."""
    user_id = monde["users"]["lecteur"]["id"]
    org_id = monde["orgs"]["A"][1]
    async with AsyncSessionLocal() as db:
        assert await user_has_module_permission(db, uuid.UUID(user_id), uuid.UUID(org_id), TANKER, STATION_READ) is False
