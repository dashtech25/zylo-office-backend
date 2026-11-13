"""BE-083 : ingestion des évènements fournisseur (route d'entrée et signature).

Tests écrits d'après la définition `### BE-083` de
implementation-backend/tasks-abonnements-facturation.md, avant le code.

Couverture :
- CA-1 : un évènement à signature invalide est rejeté sans persistance ;
- CA-2 (refus) : un appelant sans signature reçoit `401` avec un code métier, pas une erreur interne ;
- CA-3 : un évènement à signature valide est transmis au service de BE-029, sans traitement
  métier dans la route (test de contrat : le service est remplacé par un espion).

Route visée : `POST /api/v1/billing/provider-events`. Authentification par la signature
fournisseur `verif-hash` (ACTF-11), comparée au secret `FLUTTERWAVE_WEBHOOK_SECRET`.
Aucun appel réseau. Aucune table propre à BE-083 : la persistance se lit dans
`paymentWebhookEvent` (table de BE-029) uniquement pour compter les lignes.
"""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.billing import router as billing_router_module
from app.billing.models import PaymentWebhookEvent
from app.billing.webhooks import ResultatWebhook
from app.core.database import AsyncSessionLocal

ROUTE = "/api/v1/billing/provider-events"
SECRET = "secret-be083-test-only"


@pytest.fixture(autouse=True)
def secret_webhook(monkeypatch):
    monkeypatch.setenv("FLUTTERWAVE_WEBHOOK_SECRET", SECRET)


def _corps() -> bytes:
    evenement = {
        "id": f"evt-{uuid.uuid4().hex}",
        "event": "charge.completed",
        "data": {"id": "fake", "tx_ref": str(uuid.uuid4()), "status": "successful"},
    }
    return json.dumps(evenement).encode()


async def _nombre_evenements() -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(PaymentWebhookEvent))


async def test_ca1_signature_invalide_rejetee_sans_persistance(client: AsyncClient):
    avant = await _nombre_evenements()

    reponse = await client.post(
        ROUTE, content=_corps(),
        headers={"content-type": "application/json", "verif-hash": "signature-fausse"},
    )

    assert reponse.status_code == 401
    assert reponse.json()["error"]["code"] == "webhook_signature_invalid"
    assert await _nombre_evenements() == avant


async def test_ca2_sans_signature_refus_401_et_non_erreur_interne(client: AsyncClient):
    reponse = await client.post(ROUTE, content=_corps(), headers={"content-type": "application/json"})

    assert reponse.status_code == 401
    assert reponse.status_code < 500
    assert reponse.json()["error"]["code"] == "webhook_signature_invalid"


async def test_ca3_signature_valide_transmise_au_service_sans_traitement_metier(
    client: AsyncClient, monkeypatch,
):
    appels = []

    async def espion_service(db, **kwargs):
        appels.append(kwargs)
        return ResultatWebhook(duplicate=False, outcome="applied", event_id="evt-espion")

    monkeypatch.setattr(billing_router_module, "traiter_evenement_webhook", espion_service)
    corps = _corps()

    reponse = await client.post(
        ROUTE, content=corps,
        headers={"content-type": "application/json", "verif-hash": SECRET},
    )

    assert reponse.status_code == 200
    assert reponse.json() == {"received": True, "duplicate": False}
    assert len(appels) == 1
    assert appels[0]["signature_verifiee"] is True
    assert appels[0]["corps"] == corps
