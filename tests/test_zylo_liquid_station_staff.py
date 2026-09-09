"""Tests du module Personnel (mockup emalioration/personnel/) : création
d'un compte pour un employé (mot de passe temporaire généré côté serveur,
jamais choisi par la personne — aucune infrastructure d'invitation par
email, décision validée avec le commanditaire), profil de poste
(StationStaffProfile), désactivation d'accès, historique par auteur.
Couvre :
  - création → mot de passe temporaire retourné une seule fois → connexion
    avec ce mot de passe → mustChangePassword=true → changement de mot de
    passe → reconnexion sans le flag ;
  - email déjà utilisé → 409 (même code que l'auto-inscription) ;
  - rattachement d'un rôle à la création (réutilise assign_role existant) ;
  - désactivation d'accès → connexion bloquée (403 account_inactive, déjà
    existant, aucune logique nouvelle) ;
  - filtre `actorUserId` de l'historique d'audit ;
  - mise à jour du profil de poste, liste scopée station."""

import uuid

from httpx import AsyncClient


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_station(client: AsyncClient, headers: dict, suffix: str) -> str:
    res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station {suffix}", "code": f"ST{suffix}"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def test_create_station_staff_temporary_password_flow(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)
    email = f"paul.atangana-{suffix}@example.com"

    created = await client.post(
        "/api/v1/zylo-liquid/station-staff",
        json={
            "stationId": station_id, "firstName": "Paul", "lastName": "Atangana", "email": email,
            "phone": "+237600000000", "employeeNumber": "EMP-001",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    temp_password = body["temporaryPassword"]
    assert temp_password
    staff = body["staff"]
    assert staff["fullName"] == "Paul Atangana"
    assert staff["email"] == email
    assert staff["employeeNumber"] == "EMP-001"
    assert staff["status"] == "active"

    # Le mot de passe temporaire permet de se connecter, avec l'obligation
    # de le changer immédiatement.
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": temp_password})
    assert login.status_code == 200, login.text
    new_access = login.json()["accessToken"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200
    assert me.json()["mustChangePassword"] is True

    changed = await client.post(
        "/api/v1/auth/change-password",
        json={"currentPassword": temp_password, "newPassword": "NouveauMotDePasse123!"},
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["mustChangePassword"] is False

    # L'ancien mot de passe temporaire ne fonctionne plus, le nouveau oui,
    # et le flag reste levé.
    old_login = await client.post("/api/v1/auth/login", json={"email": email, "password": temp_password})
    assert old_login.status_code == 401

    relogin = await client.post("/api/v1/auth/login", json={"email": email, "password": "NouveauMotDePasse123!"})
    assert relogin.status_code == 200
    me2 = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {relogin.json()['accessToken']}"})
    assert me2.json()["mustChangePassword"] is False


async def test_create_station_staff_duplicate_email_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)

    first = await client.post(
        "/api/v1/zylo-liquid/station-staff",
        json={"stationId": station_id, "firstName": "A", "lastName": "B", "email": registered_user["email"]},
        headers=headers,
    )
    assert first.status_code == 409
    assert first.json()["error"]["code"] == "email_already_used"


async def test_create_station_staff_with_role_assignment(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)

    roles = await client.get(f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/roles", headers=headers)
    assert roles.status_code == 200
    pump_role = next(r for r in roles.json() if r["code"] == "zylo_liquid_pump_attendant")

    created = await client.post(
        "/api/v1/zylo-liquid/station-staff",
        json={
            "stationId": station_id, "firstName": "Jean", "lastName": "Pompiste",
            "email": f"jean.pompiste-{suffix}@example.com", "roleId": pump_role["id"],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["staff"]["userId"]

    members = await client.get(f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/members", headers=headers)
    member = next(m for m in members.json() if m["userId"] == user_id)
    assert any(r["id"] == pump_role["id"] and r["resourceId"] == station_id for r in member["roles"])


async def test_deactivate_station_staff_blocks_login(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)
    email = f"marie.ekedi-{suffix}@example.com"

    created = await client.post(
        "/api/v1/zylo-liquid/station-staff",
        json={"stationId": station_id, "firstName": "Marie", "lastName": "Ekedi", "email": email},
        headers=headers,
    )
    user_id = created.json()["staff"]["userId"]
    temp_password = created.json()["temporaryPassword"]

    ok_login = await client.post("/api/v1/auth/login", json={"email": email, "password": temp_password})
    assert ok_login.status_code == 200

    deactivate = await client.post(f"/api/v1/zylo-liquid/station-staff/{user_id}/deactivate", headers=headers)
    assert deactivate.status_code == 200, deactivate.text
    assert deactivate.json()["status"] == "suspended"

    blocked_login = await client.post("/api/v1/auth/login", json={"email": email, "password": temp_password})
    assert blocked_login.status_code == 403
    assert blocked_login.json()["error"]["code"] == "account_inactive"


async def test_update_station_staff_profile_and_list_scoped_by_station(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_a_id = await _create_station(client, headers, suffix)
    station_b_id = await _create_station(client, headers, f"{suffix}b")

    created = await client.post(
        "/api/v1/zylo-liquid/station-staff",
        json={"stationId": station_a_id, "firstName": "Old", "lastName": "Name", "email": f"staff-{suffix}@example.com"},
        headers=headers,
    )
    user_id = created.json()["staff"]["userId"]

    updated = await client.patch(
        f"/api/v1/zylo-liquid/station-staff/{user_id}",
        json={"firstName": "New", "contractType": "CDI", "employeeNumber": "EMP-042"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["firstName"] == "New"
    assert updated.json()["fullName"] == "New Name"
    assert updated.json()["contractType"] == "CDI"

    list_a = await client.get(f"/api/v1/zylo-liquid/station-staff?stationId={station_a_id}", headers=headers)
    assert list_a.status_code == 200
    assert any(s["userId"] == user_id for s in list_a.json())

    list_b = await client.get(f"/api/v1/zylo-liquid/station-staff?stationId={station_b_id}", headers=headers)
    assert list_b.status_code == 200
    assert not any(s["userId"] == user_id for s in list_b.json())


async def test_audit_history_filtered_by_actor(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)

    created = await client.post(
        "/api/v1/zylo-liquid/station-staff",
        json={"stationId": station_id, "firstName": "Audit", "lastName": "Test", "email": f"audit-{suffix}@example.com"},
        headers=headers,
    )
    user_id = created.json()["staff"]["userId"]

    me = await client.get("/api/v1/auth/me", headers=headers)
    actor_id = me.json()["id"]

    filtered = await client.get(
        f"/api/v1/audit/organizations/{zylo_liquid_organization['id']}?actorUserId={actor_id}",
        headers=headers,
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()["data"]
    assert any(r["action"] == "zyloLiquid.stationStaff.create" and r["entityId"] == user_id for r in rows)
