"""Scénario A4 (personnel et rôles) : création du personnel en lot tout-ou-rien
(compte + fiche + rôle scopé station dans UNE transaction, PC-18), hiérarchie
des postes côté serveur (PC-19), garde du dernier gérant / auto-désactivation
(PC-24), réactivation, station d'affectation immuable (PC-20), unicité du N°
d'employé par station, rôle « Responsable de tour » (droits + rattrapage dans
une organisation existante), portée station."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid import roles_seed
from app.modules.zylo_liquid.permissions import (
    DECLARATION_LOCK,
    PRICE_HISTORY_CREATE,
    PUMP_MANAGE,
    SALE_CREATE,
    SHIFT_DEFINITION_MANAGE,
    STATION_STAFF_MANAGE,
    STATION_STAFF_READ,
)
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.service import get_role_permission_codes


BASE = "/api/v1/zylo-liquid"


# T-021 : un membre du personnel n'a pas de mot de passe temporaire. Son compte est activé
# par le lien reçu par e-mail (boîte mémoire du test), comme pour tout compte créé par une organisation.
import re as _re
from app.core.config import settings as _settings
from app.shared.email import memory_outbox as _memory_outbox

_REGEX_JETON = _re.compile(r"#token=([A-Za-z0-9_\-]+)")
MOT_DE_PASSE_MEMBRE = "NouveauMotDePasse-42"


@pytest.fixture(autouse=True)
def _boite_de_test(monkeypatch):
    monkeypatch.setattr(_settings, "EMAIL_BACKEND", "memory")
    _memory_outbox().clear()
    yield
    _memory_outbox().clear()


async def _activer_membre(client, email: str, mot_de_passe: str = MOT_DE_PASSE_MEMBRE):
    message = [m for m in _memory_outbox() if m.to == email][-1]
    jeton = _REGEX_JETON.search(message.body).group(1)
    res = await client.post("/api/v1/auth/activate", json={"token": jeton, "password": mot_de_passe})
    assert res.status_code == 200, res.text
    return res


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _station(client: AsyncClient, headers: dict) -> str:
    suffix = uuid.uuid4().hex[:6]
    res = await client.post(f"{BASE}/stations", json={"name": f"Station A4 {suffix}", "code": f"A{suffix}"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _roles(client: AsyncClient, headers: dict, organization: dict) -> dict:
    res = await client.get(f"/api/v1/rbac/organizations/{organization['id']}/roles", headers=headers)
    assert res.status_code == 200, res.text
    return {r["code"]: r["id"] for r in res.json()}


def _email(tag: str = "p") -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}@example.com"


def _row(n: int, role_id: str | None, email: str | None = None, **extra) -> dict:
    return {"rowNumber": n, "firstName": f"Prenom{n}", "lastName": f"Nom{n}", "email": email or _email(f"r{n}"), "roleId": role_id, **extra}


async def _bulk(client: AsyncClient, headers: dict, station: str, rows: list[dict]):
    return await client.post(f"{BASE}/station-staff/bulk", json={"stationId": station, "rows": rows}, headers=headers)


async def _list(client: AsyncClient, headers: dict, station: str) -> list[dict]:
    res = await client.get(f"{BASE}/station-staff?stationId={station}", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _pairs(res) -> set:
    return {(d["rowNumber"], d["field"], d["code"]) for d in res.json()["error"]["details"]}


async def _login(client: AsyncClient, organization: dict, email: str, password: str) -> dict:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_as(client, owner_headers, organization, station, role_id) -> dict:
    """Crée une personne par la direction et retourne ses en-têtes + id + e-mail."""
    email = _email("who")
    res = await _bulk(client, owner_headers, station, [_row(1, role_id, email)])
    assert res.status_code == 201, res.text
    item = res.json()["data"][0]
    await _activer_membre(client, email)
    headers = await _login(client, organization, email, MOT_DE_PASSE_MEMBRE)
    return {"headers": headers, "userId": item["staff"]["userId"], "email": email}


async def test_bulk_success_writes_roles_and_invitations_without_secret(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    roles = await _roles(client, h, zylo_liquid_organization)
    station = await _station(client, h)
    assert "zylo_liquid_shift_manager" in roles
    res = await _bulk(client, h, station, [
        _row(1, roles["zylo_liquid_pump_attendant"], employeeNumber="E-3", contractType="CDD"),
        _row(2, roles["zylo_liquid_shift_manager"], employeeNumber="E-1"),
        _row(3, roles["zylo_liquid_team_lead"], phone="650000000"),
    ])
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["createdCount"] == 3 and [d["rowNumber"] for d in body["data"]] == [1, 2, 3]
    # T-021 : aucun mot de passe dans la réponse, seulement l'échéance du lien d'activation.
    assert all("temporaryPassword" not in d and d["invitationExpiresAt"] for d in body["data"])

    # L'activation par le lien reçu ouvre la session (le titulaire a choisi son mot de passe).
    first = body["data"][0]
    await _activer_membre(client, first["staff"]["email"])
    login = await client.post("/api/v1/auth/login", json={"email": first["staff"]["email"], "password": MOT_DE_PASSE_MEMBRE})
    assert login.status_code == 200
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['accessToken']}"})
    assert me.json()["mustChangePassword"] is False

    # Liste : libellé fourni par le backend, tri par niveau hiérarchique, jamais le mot de passe.
    listing = await _list(client, h, station)
    assert [(i["positionLabel"], i["hierarchyLevel"]) for i in listing] == [("Responsable de tour", 3), ("Chef d'équipe", 4), ("Pompiste", 5)]
    assert all(i["hasProfile"] and i["status"] == "active" and "temporaryPassword" not in i for i in listing)
    assert listing[0]["employeeNumber"] == "E-1" and listing[2]["contractType"] == "CDD"

    # Attribution de rôle réellement scopée à la station (jamais organisation entière).
    async with AsyncSessionLocal() as db:
        user_id = uuid.UUID(first["staff"]["userId"])
        assignments = (await db.execute(select(UserRole).where(UserRole.userId == user_id))).scalars().all()
        assert [(a.resourceType, str(a.resourceId)) for a in assignments] == [("station", station)]


async def test_bulk_all_or_nothing_no_orphan_account(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    roles = await _roles(client, h, zylo_liquid_organization)
    station = await _station(client, h)
    good_email = _email("good")
    res = await _bulk(client, h, station, [
        _row(1, roles["zylo_liquid_pump_attendant"], good_email),
        {"rowNumber": 2, "firstName": "", "lastName": "X", "email": "jean@x", "roleId": None},
        _row(3, str(uuid.uuid4())),
    ])
    assert res.status_code == 422
    error = res.json()["error"]
    assert error["code"] == "staff_bulk_invalid" and "Rien n'a été enregistré" in error["message"]
    assert _pairs(res) == {
        (2, "firstName", "first_name_required"), (2, "email", "email_invalid"), (2, "roleId", "role_required"),
        (3, "roleId", "role_not_found"),
    }
    assert all(d["message"] for d in error["details"])
    assert await _list(client, h, station) == []
    # L'e-mail de la ligne valide n'est PAS consommé (pas de compte orphelin).
    again = await _bulk(client, h, station, [_row(1, roles["zylo_liquid_pump_attendant"], good_email)])
    assert again.status_code == 201, again.text


async def test_bulk_duplicate_email_in_batch_and_in_database(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    roles = await _roles(client, h, zylo_liquid_organization)
    station = await _station(client, h)
    pump = roles["zylo_liquid_pump_attendant"]
    dup = _email("dup")
    res = await _bulk(client, h, station, [
        _row(1, pump, dup), _row(2, pump, dup.upper()), _row(3, pump, registered_user["email"]), _row(4, pump),
    ])
    assert res.status_code == 422
    assert _pairs(res) == {(1, "email", "email_duplicate_in_batch"), (2, "email", "email_duplicate_in_batch"), (3, "email", "email_taken")}
    taken = next(d for d in res.json()["error"]["details"] if d["code"] == "email_taken")
    assert registered_user["email"] not in taken["message"]


async def test_bulk_employee_number_unique_per_station(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    roles = await _roles(client, h, zylo_liquid_organization)
    station_a, station_b = await _station(client, h), await _station(client, h)
    pump = roles["zylo_liquid_pump_attendant"]
    ok = await _bulk(client, h, station_a, [_row(1, pump, employeeNumber="E-001")])
    assert ok.status_code == 201, ok.text
    res = await _bulk(client, h, station_a, [_row(1, pump, employeeNumber="E-001"), _row(2, pump, employeeNumber="E-002"), _row(3, pump, employeeNumber="E-002")])
    assert _pairs(res) == {(1, "employeeNumber", "employee_number_taken"), (2, "employeeNumber", "employee_number_duplicate_in_batch"), (3, "employeeNumber", "employee_number_duplicate_in_batch")}
    # Autre station : le même numéro est libre. Sans numéro : jamais bloqué.
    other = await _bulk(client, h, station_b, [_row(1, pump, employeeNumber="E-001"), _row(2, pump), _row(3, pump)])
    assert other.status_code == 201, other.text
    # Mise à jour d'une fiche vers un numéro déjà pris : 409.
    staff_a = (await _list(client, h, station_a))[0]
    second = await _bulk(client, h, station_a, [_row(1, pump, employeeNumber="E-777")])
    uid = second.json()["data"][0]["staff"]["userId"]
    clash = await client.patch(f"{BASE}/station-staff/{uid}", json={"employeeNumber": staff_a["employeeNumber"]}, headers=h)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "employee_number_taken"


async def test_bulk_limit_50_rows(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    roles = await _roles(client, h, zylo_liquid_organization)
    station = await _station(client, h)
    res = await _bulk(client, h, station, [_row(i, roles["zylo_liquid_pump_attendant"]) for i in range(1, 52)])
    assert res.status_code == 422 and res.json()["error"]["code"] == "staff_bulk_too_many_rows"
    assert await _list(client, h, station) == []


async def test_hierarchy_manager_cannot_name_manager_but_direction_can(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    roles = await _roles(client, h, zylo_liquid_organization)
    station = await _station(client, h)
    # La direction nomme un gérant.
    manager = await _create_as(client, h, zylo_liquid_organization, station, roles["zylo_liquid_station_admin"])
    mh = manager["headers"]

    # Le gérant ne nomme pas de gérant (lot) : erreur sur la cellule Poste, rien d'écrit.
    email = _email("g2")
    res = await _bulk(client, mh, station, [_row(1, roles["zylo_liquid_pump_attendant"]), _row(2, roles["zylo_liquid_station_admin"], email)])
    assert res.status_code == 422
    assert _pairs(res) == {(2, "roleId", "role_not_assignable")}
    assert len(await _list(client, mh, station)) == 1
    # Ni la direction (rôle owner), ni via l'endpoint à une personne.
    owner_try = await _bulk(client, mh, station, [_row(1, roles["owner"])])
    assert _pairs(owner_try) == {(1, "roleId", "role_not_assignable")}
    single = await client.post(f"{BASE}/station-staff", json={"stationId": station, "firstName": "A", "lastName": "B", "email": email, "roleId": roles["zylo_liquid_station_admin"]}, headers=mh)
    assert single.status_code == 403 and single.json()["error"]["code"] == "role_not_assignable"
    # PC-18 : le refus n'a pas laissé de compte orphelin (l'e-mail reste libre).
    retry = await client.post(f"{BASE}/station-staff", json={"stationId": station, "firstName": "A", "lastName": "B", "email": email, "roleId": roles["zylo_liquid_team_lead"]}, headers=mh)
    assert retry.status_code == 201, retry.text
    assert retry.json()["staff"]["positionLabel"] == "Chef d'équipe"

    # Le gérant nomme RT / CE / pompiste.
    ok = await _bulk(client, mh, station, [_row(1, roles["zylo_liquid_shift_manager"]), _row(2, roles["zylo_liquid_pump_attendant"])])
    assert ok.status_code == 201, ok.text

    # Il ne peut ni changer le poste, ni réinitialiser le mot de passe, ni désactiver un autre gérant.
    peer = await _create_as(client, h, zylo_liquid_organization, station, roles["zylo_liquid_station_admin"])
    change = await client.put(f"{BASE}/station-staff/{peer['userId']}/role", json={"roleId": roles["zylo_liquid_pump_attendant"]}, headers=mh)
    assert change.status_code == 403 and change.json()["error"]["code"] == "staff_hierarchy_denied"
    reset = await client.post(f"{BASE}/station-staff/{peer['userId']}/reset-password", headers=mh)
    assert reset.status_code == 403
    deact = await client.post(f"{BASE}/station-staff/{peer['userId']}/deactivate", headers=mh)
    assert deact.status_code == 403
    # Ni promouvoir un pompiste au rang de gérant par changement de poste.
    pump_uid = ok.json()["data"][1]["staff"]["userId"]
    promote = await client.put(f"{BASE}/station-staff/{pump_uid}/role", json={"roleId": roles["zylo_liquid_station_admin"]}, headers=mh)
    assert promote.status_code == 403 and promote.json()["error"]["code"] == "role_not_assignable"
    # Mais il change un pompiste en chef d'équipe (remplacement atomique d'un seul poste).
    demote = await client.put(f"{BASE}/station-staff/{pump_uid}/role", json={"roleId": roles["zylo_liquid_team_lead"]}, headers=mh)
    assert demote.status_code == 200 and demote.json()["roleCode"] == "zylo_liquid_team_lead"
    async with AsyncSessionLocal() as db:
        count = len((await db.execute(select(UserRole).where(UserRole.userId == uuid.UUID(pump_uid)))).scalars().all())
        assert count == 1


async def test_last_manager_guard_self_deactivation_and_reactivation(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    roles = await _roles(client, h, zylo_liquid_organization)
    station = await _station(client, h)
    admin = roles["zylo_liquid_station_admin"]
    first = await _create_as(client, h, zylo_liquid_organization, station, admin)

    # Dernier gérant : refusé, même par la direction, et auto-désactivation refusée.
    blocked = await client.post(f"{BASE}/station-staff/{first['userId']}/deactivate", headers=h)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "last_manager_guard"
    selfie = await client.post(f"{BASE}/station-staff/{first['userId']}/deactivate", headers=first["headers"])
    assert selfie.status_code == 409 and selfie.json()["error"]["code"] == "cannot_deactivate_self"
    assert "propre accès" in selfie.json()["error"]["message"]
    # Idem pour le retrait de son poste de gérant.
    demote = await client.put(f"{BASE}/station-staff/{first['userId']}/role", json={"roleId": roles["zylo_liquid_pump_attendant"]}, headers=h)
    assert demote.status_code == 409 and demote.json()["error"]["code"] == "last_manager_guard"

    # Avec un second gérant actif, la désactivation de l'autre devient possible.
    second = await _create_as(client, h, zylo_liquid_organization, station, admin)
    done = await client.post(f"{BASE}/station-staff/{first['userId']}/deactivate", headers=h)
    assert done.status_code == 200 and done.json()["status"] == "suspended"
    # Le second est maintenant le dernier gérant actif.
    again = await client.post(f"{BASE}/station-staff/{second['userId']}/deactivate", headers=h)
    assert again.status_code == 409

    # Compte suspendu : plus de connexion ; réactivation : connexion de nouveau possible, audité.
    login = await client.post("/api/v1/auth/login", json={"email": first["email"], "password": "x"})
    assert login.status_code in (401, 403)
    back = await client.post(f"{BASE}/station-staff/{first['userId']}/reactivate", headers=h)
    assert back.status_code == 200 and back.json()["status"] == "active"
    idem = await client.post(f"{BASE}/station-staff/{first['userId']}/reactivate", headers=h)
    assert idem.status_code == 200 and idem.json()["status"] == "active"
    me = await client.get("/api/v1/auth/me", headers=first["headers"])
    assert me.status_code == 200
    audit = await client.get(f"/api/v1/audit/organizations/{zylo_liquid_organization['id']}?limit=100", headers=h)
    assert "zyloLiquid.stationStaff.reactivate" in audit.text


async def test_shift_manager_role_rights_and_manager_superset(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    roles = await _roles(client, h, zylo_liquid_organization)
    async with AsyncSessionLocal() as db:
        rt = set(await get_role_permission_codes(db, uuid.UUID(roles["zylo_liquid_shift_manager"])))
        admin = set(await get_role_permission_codes(db, uuid.UUID(roles["zylo_liquid_station_admin"])))
        team = set(await get_role_permission_codes(db, uuid.UUID(roles["zylo_liquid_team_lead"])))
    assert {STATION_STAFF_READ, DECLARATION_LOCK} <= rt
    assert set(roles_seed._DECLARATION_CREATE_PERMISSIONS) <= rt and set(roles_seed._DECLARATION_READ_PERMISSIONS) <= rt
    # Jamais accordé au RT.
    assert not ({STATION_STAFF_MANAGE, SHIFT_DEFINITION_MANAGE, PUMP_MANAGE, SALE_CREATE, PRICE_HISTORY_CREATE} & rt)
    # Le RT gère uniquement ce qui relève de la conduite d'un tour (B1 à B5) : jamais les référentiels ni le personnel.
    tour_manage = {c for c in rt if c.endswith(".manage")}
    assert all(
        any(k in c for k in ("shiftAttendance", "shiftHandover", "shiftReport", "pumpAssignment", "shiftReplacement", "shiftPlanning"))
        for c in tour_manage
    ), tour_manage
    # Le gérant possède TOUT ce que possède le RT (sinon il ne pourrait pas le nommer).
    assert rt <= admin
    assert team != rt

    # Fonctionnel : un RT lit le personnel de SA station, ne gère rien.
    station, other = await _station(client, h), await _station(client, h)
    rt_user = await _create_as(client, h, zylo_liquid_organization, station, roles["zylo_liquid_shift_manager"])
    rh = rt_user["headers"]
    assert (await client.get(f"{BASE}/station-staff?stationId={station}", headers=rh)).status_code == 200
    assert (await client.get(f"{BASE}/station-staff?stationId={other}", headers=rh)).status_code == 403
    denied = await _bulk(client, rh, station, [_row(1, roles["zylo_liquid_pump_attendant"])])
    assert denied.status_code == 403
    assert (await client.post(f"{BASE}/station-staff/{rt_user['userId']}/deactivate", headers=rh)).status_code == 403
    assert (await client.post(f"{BASE}/shift-definitions/bulk", json={"stationId": station, "rows": [{"rowNumber": 1, "shiftNumber": 1, "name": "M", "startTime": "06:00", "endTime": "14:00", "active": True}]}, headers=rh)).status_code == 403
    assert (await client.get(f"{BASE}/shift-definitions?stationId={station}", headers=rh)).status_code == 200


async def test_station_scope_and_immutable_station(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    roles = await _roles(client, h, zylo_liquid_organization)
    station_a, station_b = await _station(client, h), await _station(client, h)
    manager = await _create_as(client, h, zylo_liquid_organization, station_a, roles["zylo_liquid_station_admin"])
    mh = manager["headers"]

    # Le gérant de A ne crée ni ne liste pour B (la station vient de la requête, jamais d'un champ de ligne).
    assert (await _bulk(client, mh, station_b, [_row(1, roles["zylo_liquid_pump_attendant"])])).status_code == 403
    assert (await client.get(f"{BASE}/station-staff?stationId={station_b}", headers=mh)).status_code == 403
    created = await _bulk(client, mh, station_a, [_row(1, roles["zylo_liquid_pump_attendant"])])
    assert created.status_code == 201, created.text
    uid = created.json()["data"][0]["staff"]["userId"]
    assert created.json()["data"][0]["staff"]["assignedStationId"] == station_a

    # La station d'affectation ne peut pas être changée (PC-20) ; la renvoyer inchangée est toléré.
    moved = await client.patch(f"{BASE}/station-staff/{uid}", json={"assignedStationId": station_b}, headers=h)
    assert moved.status_code == 422 and moved.json()["error"]["code"] == "station_change_not_allowed"
    same = await client.patch(f"{BASE}/station-staff/{uid}", json={"assignedStationId": station_a, "contractType": "CDI"}, headers=h)
    assert same.status_code == 200 and same.json()["contractType"] == "CDI" and same.json()["assignedStationId"] == station_a

    # Responsable direct : une personne de la même station, de niveau supérieur.
    ok = await client.patch(f"{BASE}/station-staff/{uid}", json={"directManagerUserId": manager["userId"]}, headers=h)
    assert ok.status_code == 200 and ok.json()["directManagerName"]
    bad = await client.patch(f"{BASE}/station-staff/{uid}", json={"directManagerUserId": uid}, headers=h)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "direct_manager_invalid"
    listing = await _list(client, h, station_a)
    assert [i["hierarchyLevel"] for i in listing] == [2, 5] and listing[1]["directManagerUserId"] == manager["userId"]


async def test_list_includes_role_holders_without_profile(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    roles = await _roles(client, h, zylo_liquid_organization)
    station = await _station(client, h)
    email = _email("noprof")
    reg = await client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!", "fullName": "Sans Fiche"})
    assert reg.status_code in (200, 201), reg.text
    from app.identity.models import OrganizationUser, User

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        db.add(OrganizationUser(organizationId=zylo_liquid_organization["id"], userId=user.id))
        await db.commit()
        user_id = str(user.id)
    res = await client.post(
        f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/user-roles",
        json={"userId": user_id, "roleId": roles["zylo_liquid_shift_manager"], "resourceType": "station", "resourceId": station},
        headers=h,
    )
    assert res.status_code == 201, res.text
    items = await _list(client, h, station)
    assert len(items) == 1
    item = items[0]
    assert item["hasProfile"] is False and item["id"] is None and item["employeeNumber"] is None
    assert item["positionLabel"] == "Responsable de tour" and item["userId"] == user_id
