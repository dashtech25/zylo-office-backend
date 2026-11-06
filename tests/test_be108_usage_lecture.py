"""BE-108 : lecture de l'usage (agrégats et limites) du portail organisation.

Intention : prouver par des tests les critères d'acceptation de BE-108
(implementation-backend/tasks-portail-organisation.md, section BE-108) :
- CA-1 : la réponse contient la date de mesure et la granularité ;
- CA-2 : la réponse ne contient aucun identifiant d'identité individuelle ;
- CA-3 : sans la permission `organization.usage.read`, 403 ; organisation hors portée, 404 ;
- CA-4 : le snapshot de l'organisation B n'est jamais retourné sous l'organisation A.

Route testée : GET /api/v1/organizations/{organization_id}/usage.
Source : table `usage_snapshot` (lecture seule ici ; l'écriture appartient à PH-09, non livré).
Écart : la permission est `organization.usage.read` (format `domaine.entite.action`, comme BE-107),
et non `usage:read` écrit dans la fiche.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.billing.models import UsageSnapshot
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser

MOT_DE_PASSE = "TestPassword123!"
CLES_ATTENDUES = {"measuredAt", "granularity", "aggregates", "limits"}
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _url(organization_id: str) -> str:
    return f"/api/v1/organizations/{organization_id}/usage"


async def _snapshot(organization_id: uuid.UUID, granularity: str, mesure: datetime | None = None) -> uuid.UUID:
    """Ligne de snapshot d'usage pour une organisation ; retourne son identifiant."""
    async with AsyncSessionLocal() as db:
        ligne = UsageSnapshot(
            organizationId=organization_id,
            measuredAt=mesure or datetime.now(timezone.utc),
            granularity=granularity,
            aggregates={"sitesActifs": 3, "volumeTotal": 1250},
            limits={"sitesMax": 5},
        )
        db.add(ligne)
        await db.commit()
        return ligne.id


async def _membre_sans_droit(client: AsyncClient, organization_id: uuid.UUID) -> str:
    """Utilisateur rattaché à l'organisation sans rôle ; retourne son jeton d'accès."""
    membre = await client.post("/api/v1/auth/register", json={
        "email": f"be108-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-108",
    })
    login = await client.post("/api/v1/auth/login", json={"email": membre.json()["email"], "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=uuid.UUID(membre.json()["id"])))
        await db.commit()
    return login.json()["accessToken"]


async def _organisation_etrangere(client: AsyncClient) -> dict:
    """Organisation d'un autre utilisateur, hors de portée de l'utilisateur de test."""
    autre = await client.post("/api/v1/auth/register", json={
        "email": f"be108-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Autre BE-108",
    })
    login = await client.post("/api/v1/auth/login", json={"email": autre.json()["email"], "password": MOT_DE_PASSE})
    res = await client.post(
        "/api/v1/organizations", json={"name": "Org B BE-108", "slug": f"be108-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {login.json()['accessToken']}"},
    )
    return res.json()


async def test_reponse_contient_date_de_mesure_et_granularite(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : la réponse porte la date de mesure et la granularité du snapshot, avec agrégats et limites."""
    org_id = uuid.UUID(organization["id"])
    mesure = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    await _snapshot(org_id, "mensuelle", mesure)

    reponse = await client.get(_url(organization["id"]),
                               headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["granularity"] == "mensuelle"
    assert datetime.fromisoformat(corps["measuredAt"].replace("Z", "+00:00")) == mesure
    assert corps["aggregates"] == {"sitesActifs": 3, "volumeTotal": 1250}
    assert corps["limits"] == {"sitesMax": 5}


async def test_reponse_sans_identifiant_individuel(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : seules les clés attendues sont présentes, et aucun identifiant d'utilisateur n'apparaît."""
    org_id = uuid.UUID(organization["id"])
    await _snapshot(org_id, "mensuelle")

    reponse = await client.get(_url(organization["id"]),
                               headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 200, reponse.text
    assert set(reponse.json().keys()) == CLES_ATTENDUES
    # Aucun UUID dans la réponse : l'organisation et l'utilisateur ne sont pas exposés.
    assert UUID_RE.search(reponse.text) is None


async def test_sans_permission_usage_read_retourne_403(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 (refus de droit) : un membre sans permission de lecture de l'usage reçoit 403."""
    org_id = uuid.UUID(organization["id"])
    await _snapshot(org_id, "mensuelle")
    jeton = await _membre_sans_droit(client, org_id)

    reponse = await client.get(_url(organization["id"]), headers=_entete(jeton, organization["id"]))

    assert reponse.status_code == 403
    assert reponse.json()["code"] == "permission_denied"


async def test_organisation_hors_portee_retourne_404(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 (isolation) : une organisation dont l'utilisateur n'est pas membre répond 404."""
    autre = await _organisation_etrangere(client)
    await _snapshot(uuid.UUID(autre["id"]), "horaire")

    reponse = await client.get(_url(autre["id"]),
                               headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 404
    assert "horaire" not in reponse.text


async def test_snapshot_de_l_autre_organisation_jamais_retourne(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : le snapshot de l'organisation B n'apparaît jamais dans la réponse de l'organisation A."""
    org_a = uuid.UUID(organization["id"])
    autre = await _organisation_etrangere(client)
    await _snapshot(org_a, "mensuelle")
    await _snapshot(uuid.UUID(autre["id"]), "horaire-org-b")

    reponse = await client.get(_url(organization["id"]),
                               headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["granularity"] == "mensuelle"
    assert "horaire-org-b" not in reponse.text


async def test_snapshot_le_plus_recent_retenu(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """Plusieurs snapshots : la réponse porte le plus récent (date de mesure la plus tardive)."""
    org_id = uuid.UUID(organization["id"])
    maintenant = datetime.now(timezone.utc)
    await _snapshot(org_id, "ancien", maintenant - timedelta(days=2))
    await _snapshot(org_id, "recent", maintenant)

    reponse = await client.get(_url(organization["id"]),
                               headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["granularity"] == "recent"


async def test_sans_session_retourne_401(client: AsyncClient, organization: dict):
    """Sans jeton d'accès, la route refuse la requête (401)."""
    reponse = await client.get(_url(organization["id"]))

    assert reponse.status_code == 401


async def test_aucun_snapshot_renvoie_des_valeurs_vides(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """Organisation sans snapshot : 200 avec date de mesure et granularité nulles, agrégats et limites vides."""
    reponse = await client.get(_url(organization["id"]),
                               headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 200, reponse.text
    assert reponse.json() == {"measuredAt": None, "granularity": None, "aggregates": {}, "limits": {}}
