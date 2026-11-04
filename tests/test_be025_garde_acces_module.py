"""BE-025 : garde d'accès module fail-closed (projection canOpen / canActivate).

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-socle-tenant-identite.md,
section BE-025) :

- GET /api/v1/organizations/current/modules/{moduleId}/access : projection `accessState`,
  `canActivate` et `canOpen` calculée côté serveur pour l'organisation courante ;
- CA-1 (non-régression) : sans entitlement, l'accès legacy reste autorisé ;
- CA-2, CA-3, CA-4 (refus) : les états `inactive`, `expired` et `blocked` refusent `canOpen`
  et `canActivate`. La projection le déclare (false) et les points d'application refusent
  l'accès en 403 : la route gardée par le module et l'activation du module ;
- CA-5 (isolation) : un entitlement de O1 n'ouvre aucun module pour O2.

CA-6 (la suite complète du module passe) n'est pas un test unitaire : il se vérifie par la
suite complète, pas par ce fichier.

Chaque test crée ses propres organisations et abonnements ; les entitlements sont insérés
directement en base (le calcul depuis l'offre est couvert par BE-024).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.billing import service as billing_service
from app.billing.models import Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal
from app.identity.models import Organization

URL_CATALOGUE = "/api/v1/organizations/current/modules"
MODULE = "zylo_liquid"


def _url_acces(module_id: str) -> str:
    return f"/api/v1/organizations/current/modules/{module_id}/access"


def _url_activation(module_id: str) -> str:
    return f"/api/v1/organizations/current/modules/{module_id}/activation"


def _url_route_gardee(organization_id: str) -> str:
    """Route protégée par `require_module_active("zylo_liquid")` (permission organisation.manage)."""
    return f"/api/v1/modules/organizations/{organization_id}/zylo-liquid/protected-demo"


def _entetes(user: dict, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization_id}


async def _module_id(client: AsyncClient, headers: dict) -> str:
    res = await client.get(URL_CATALOGUE, headers=headers)
    assert res.status_code == 200, res.text
    return next(m["moduleId"] for m in res.json() if m["moduleCode"] == MODULE)


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = f"be025-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Be025"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    tokens = login.json()
    return {"email": email, "accessToken": tokens["accessToken"], "refreshToken": tokens["refreshToken"]}


async def _nouvelle_organisation(client: AsyncClient, user: dict) -> dict:
    headers = {"Authorization": f"Bearer {user['accessToken']}"}
    res = await client.post(
        "/api/v1/organizations", json={"name": "Org BE-025", "slug": f"be025-{uuid.uuid4().hex[:8]}"}, headers=headers
    )
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _ajoute_entitlement(
    organization_id: str,
    *,
    status: str,
    ends_at: datetime | None = None,
    subscription_status: str = "active",
) -> None:
    """Insère un abonnement et un entitlement de `zylo_liquid` pour l'organisation donnée."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await billing_service.get_or_create_plan(
            db, MODULE, f"be025-{uuid.uuid4().hex[:10]}", "Plan BE-025", 0, "XAF", 30
        )
        version = await billing_service.ensure_initial_plan_version(db, plan)
        abonnement = Subscription(
            organizationId=uuid.UUID(organization_id),
            planId=plan.id,
            planVersionId=version.id,
            status=subscription_status,
            startDate=maintenant - timedelta(days=1),
            endDate=maintenant + timedelta(days=30),
        )
        db.add(abonnement)
        await db.flush()
        db.add(
            SubscriptionEntitlement(
                organizationId=uuid.UUID(organization_id),
                subscriptionId=abonnement.id,
                moduleCode=MODULE,
                entitlementCode=f"be025.{uuid.uuid4().hex[:12]}",
                status=status,
                startsAt=maintenant - timedelta(days=1),
                endsAt=ends_at,
                sourceAttribution="offre",
                niveauApplication="organisation",
            )
        )
        await db.commit()


async def _projection(client: AsyncClient, headers: dict, module_id: str) -> dict:
    res = await client.get(_url_acces(module_id), headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


# --- CA-1 : non-régression, accès legacy sans entitlement ----------------------------------


@pytest.mark.asyncio
async def test_ca1_sans_entitlement_l_acces_legacy_reste_autorise(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _entetes(registered_user, organization["id"])
    module_id = await _module_id(client, headers)
    res = await client.put(_url_activation(module_id), json={"active": True}, headers=headers)
    assert res.status_code == 200, res.text

    projection = await _projection(client, headers, module_id)
    assert projection["accessState"] == "not_configured"
    assert projection["canActivate"] is True
    assert projection["canOpen"] is True

    acces = await client.get(_url_route_gardee(organization["id"]), headers=headers)
    assert acces.status_code == 200, acces.text


@pytest.mark.asyncio
async def test_entitlement_actif_sans_activation_ouvre_l_activation_mais_pas_l_acces(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """Un droit actif permet d'activer le module, mais tant qu'il n'est pas activé, rien ne s'ouvre."""
    headers = _entetes(registered_user, organization["id"])
    module_id = await _module_id(client, headers)
    await _ajoute_entitlement(organization["id"], status="active")

    projection = await _projection(client, headers, module_id)
    assert projection["accessState"] == "active"
    assert projection["canActivate"] is True
    assert projection["canOpen"] is False


# --- CA-2, CA-3, CA-4 : refus 403 pour inactive, expired, blocked --------------------------

CAS_REFUS = [
    pytest.param({"status": "inactive"}, "inactive", id="inactive"),
    pytest.param({"status": "expired"}, "expired", id="expired-statut"),
    pytest.param({"status": "blocked"}, "blocked", id="blocked"),
    pytest.param({"status": "active", "ends_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}, "expired", id="expired-date"),
    pytest.param({"status": "active", "subscription_status": "cancelled"}, "expired", id="abonnement-resilie"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("entitlement, etat_attendu", CAS_REFUS)
async def test_ca2_ca3_ca4_etat_refuse_canopen_et_canactivate_en_403(
    client: AsyncClient, registered_user: dict, organization: dict, entitlement: dict, etat_attendu: str
):
    headers = _entetes(registered_user, organization["id"])
    module_id = await _module_id(client, headers)

    # Le module est activé d'abord (organisation sans entitlement : accès legacy), puis le droit se dégrade.
    res = await client.put(_url_activation(module_id), json={"active": True}, headers=headers)
    assert res.status_code == 200, res.text
    await _ajoute_entitlement(organization["id"], **entitlement)

    projection = await _projection(client, headers, module_id)
    assert projection["accessState"] == etat_attendu
    assert projection["canOpen"] is False
    assert projection["canActivate"] is False

    # canOpen : la route gardée par le module refuse l'accès en 403.
    acces = await client.get(_url_route_gardee(organization["id"]), headers=headers)
    assert acces.status_code == 403, acces.text

    # canActivate : une réactivation est refusée en 403 (la désactivation reste possible).
    res = await client.put(_url_activation(module_id), json={"active": False}, headers=headers)
    assert res.status_code == 200, res.text
    res = await client.put(_url_activation(module_id), json={"active": True}, headers=headers)
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "module_entitlement_unavailable", res.text


# --- CA-5 : isolation entre organisations ---------------------------------------------------


@pytest.mark.asyncio
async def test_ca5_entitlement_de_o1_n_ouvre_aucun_module_pour_o2(client: AsyncClient, registered_user: dict, organization: dict):
    headers_o1 = _entetes(registered_user, organization["id"])
    module_id = await _module_id(client, headers_o1)
    await _ajoute_entitlement(organization["id"], status="active")

    autre = await _nouvel_utilisateur(client)
    org_o2 = await _nouvelle_organisation(client, autre)
    headers_o2 = _entetes(autre, org_o2["id"])
    # O2 reçoit un refus explicite : si le droit de O1 fuyait, O2 paraîtrait ouvert.
    res = await client.put(_url_activation(module_id), json={"active": True}, headers=headers_o2)
    assert res.status_code == 200, res.text
    await _ajoute_entitlement(org_o2["id"], status="blocked")

    projection_o1 = await _projection(client, headers_o1, module_id)
    assert projection_o1["canOpen"] is False  # O1 n'a pas activé le module dans ce test

    projection_o2 = await _projection(client, headers_o2, module_id)
    assert projection_o2["accessState"] == "blocked"
    assert projection_o2["canOpen"] is False
    assert projection_o2["canActivate"] is False

    acces_o2 = await client.get(_url_route_gardee(org_o2["id"]), headers=headers_o2)
    assert acces_o2.status_code == 403, acces_o2.text


@pytest.mark.asyncio
async def test_ca5_droit_actif_de_o1_visible_seulement_dans_o1(client: AsyncClient, registered_user: dict, organization: dict):
    headers_o1 = _entetes(registered_user, organization["id"])
    module_id = await _module_id(client, headers_o1)
    res = await client.put(_url_activation(module_id), json={"active": True}, headers=headers_o1)
    assert res.status_code == 200, res.text
    await _ajoute_entitlement(organization["id"], status="active")

    autre = await _nouvel_utilisateur(client)
    org_o2 = await _nouvelle_organisation(client, autre)
    projection_o2 = await _projection(client, _entetes(autre, org_o2["id"]), module_id)
    assert projection_o2["accessState"] != "active"
    assert projection_o2["canActivate"] is True  # aucune restriction propre à O2 : accès legacy seulement

    projection_o1 = await _projection(client, headers_o1, module_id)
    assert projection_o1["accessState"] == "active"
    assert projection_o1["canOpen"] is True


# --- Contrat de la projection ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_projection_module_inconnu_renvoie_404(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _entetes(registered_user, organization["id"])
    res = await client.get(_url_acces(str(uuid.uuid4())), headers=headers)
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_projection_expose_les_champs_attendus(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _entetes(registered_user, organization["id"])
    module_id = await _module_id(client, headers)
    projection = await _projection(client, headers, module_id)
    assert set(projection) >= {"moduleId", "moduleCode", "status", "accessState", "canActivate", "canOpen"}
    assert projection["moduleId"] == module_id
    assert projection["moduleCode"] == MODULE
