"""BE-028 : adaptateur de paiement neutre (stub, sandbox, aucun débit).

Intention : prouver les critères d'acceptation de BE-028
(implementation-backend/tasks-socle-tenant-identite.md, section BE-028) :
- CA-1 : aucun appel réseau vers un fournisseur pendant les tests (adaptateur factice) ;
- CA-2 (refus) : passer en mode live sans configuration validée est refusé ;
- CA-3 : les identifiants internes de tentative ne dépendent pas du SDK du fournisseur
  (test de contrat sur l'adaptateur et sur le modèle `PaymentAttempt`) ;
- CA-4 : aucun débit réel n'est créé (zéro `paymentAttempt` au statut réussi, et aucune
  ligne créée lorsque le checkout est refusé).

Routes touchées : `POST/GET /api/v1/billing/organizations/{org}/invoices/{invoice}/payment-attempts`
et `GET /api/v1/billing/payment-provider`. Le sandbox n'est jamais joint : toute tentative
de connexion réseau pendant les tests fait échouer le test.
"""

import dataclasses
import socket
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.billing import service
from app.billing.models import PaymentAttempt
from app.billing.payment_provider import CheckoutIntent, FlutterwaveTestProvider, PaymentProvider
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from tests.test_be027_factures_lecture import creer_facture, _entetes

STATUTS_REUSSIS = ("succeeded", "successful", "paid", "success", "reussi")


@pytest.fixture
def aucun_reseau(monkeypatch):
    """Fait échouer toute connexion socket : l'adaptateur ne doit jamais joindre un fournisseur."""
    def connexion_interdite(*args, **kwargs):
        raise AssertionError("BE-028 CA-1 : appel réseau vers un fournisseur pendant les tests")

    monkeypatch.setattr(socket.socket, "connect", connexion_interdite)
    monkeypatch.setattr(socket, "getaddrinfo", connexion_interdite)
    return connexion_interdite


# CA-1 : aucun appel réseau pendant les tests (adaptateur factice).
async def test_ca1_adaptateur_sans_appel_reseau(aucun_reseau, monkeypatch):
    monkeypatch.setenv("FLUTTERWAVE_MODE", "test")
    monkeypatch.setenv("FLUTTERWAVE_TEST_SECRET_KEY", "cle-de-test-factice")
    adaptateur = FlutterwaveTestProvider()

    with pytest.raises(AppError) as checkout:
        await adaptateur.create_checkout(1000, "XAF", "ref-interne-1")
    assert checkout.value.code == "PROVIDER_UNAVAILABLE"

    with pytest.raises(AppError) as debit:
        await adaptateur.charge(1000, "XAF", "ref-interne-1")
    assert debit.value.code == "PROVIDER_UNAVAILABLE"


# CA-2 (refus) : le mode live sans configuration validée est refusé.
@pytest.mark.parametrize("mode", ["live", "production", "LIVE", ""])
async def test_ca2_mode_live_refuse_sans_configuration_validee(aucun_reseau, monkeypatch, mode):
    monkeypatch.setenv("FLUTTERWAVE_MODE", mode)
    monkeypatch.setenv("FLUTTERWAVE_TEST_SECRET_KEY", "cle-de-test-factice")
    with pytest.raises(AppError) as refus:
        await FlutterwaveTestProvider().create_checkout(1000, "XAF", "ref-interne-2")
    assert refus.value.code == "PROVIDER_UNAVAILABLE"
    assert refus.value.status_code == 503


async def test_ca2_mode_test_sans_cle_sandbox_refuse(aucun_reseau, monkeypatch):
    monkeypatch.setenv("FLUTTERWAVE_MODE", "test")
    monkeypatch.delenv("FLUTTERWAVE_TEST_SECRET_KEY", raising=False)
    with pytest.raises(AppError) as refus:
        await FlutterwaveTestProvider().create_checkout(1000, "XAF", "ref-interne-3")
    assert refus.value.code == "PROVIDER_UNAVAILABLE"
    assert "pas configuré" in refus.value.message


# CA-3 : contrat de l'adaptateur. Le checkout ne porte aucun identifiant de tentative
# issu du SDK, et l'identifiant interne de `PaymentAttempt` est distinct de la référence
# fournisseur, générée localement.
def test_ca3_resultat_checkout_sans_identifiant_sdk():
    noms_de_champs = {champ.name for champ in dataclasses.fields(CheckoutIntent)}
    assert not noms_de_champs & {"id", "attemptId", "attempt_id", "paymentAttemptId"}
    assert "reference" in noms_de_champs


def test_ca3_identifiant_interne_distinct_de_la_reference_fournisseur():
    colonnes = PaymentAttempt.__table__.c
    assert colonnes.id.primary_key
    assert colonnes.providerReference.nullable is True
    assert colonnes.id.name != colonnes.providerReference.name
    # L'identifiant interne est généré localement (uuid4), pas fourni par le fournisseur.
    assert colonnes.id.default is not None
    generated = colonnes.id.default.arg
    assert callable(generated)
    assert isinstance(generated(None), uuid.UUID)


def test_ca3_interface_neutre_implementable_sans_sdk():
    class FournisseurFactice(PaymentProvider):
        async def charge(self, amount_cents: int, currency: str, reference: str) -> bool:
            return False

    intention = CheckoutIntent(provider="factice", mode="test", reference="interne-1")
    assert intention.reference == "interne-1"
    with pytest.raises(TypeError):
        PaymentProvider()  # l'interface est abstraite
    assert FournisseurFactice().__class__.__mro__[1] is PaymentProvider


# CA-4 : aucun débit réel. Le checkout refusé ne crée aucune tentative, et aucune
# tentative au statut réussi n'existe après les appels.
async def test_ca4_checkout_refuse_ne_cree_aucune_tentative(
    client: AsyncClient, registered_user: dict, organization: dict, aucun_reseau, monkeypatch,
):
    monkeypatch.setenv("FLUTTERWAVE_MODE", "test")
    monkeypatch.setenv("FLUTTERWAVE_TEST_SECRET_KEY", "cle-de-test-factice")
    headers = _entetes(registered_user["accessToken"], organization["id"])
    facture_id = await creer_facture(client, registered_user["accessToken"], organization["id"])

    async def compter() -> int:
        async with AsyncSessionLocal() as db:
            return await db.scalar(select(func.count()).select_from(PaymentAttempt)) or 0

    avant = await compter()
    tentative = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/invoices/{facture_id}/payment-attempts",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert tentative.status_code == 503, tentative.text
    assert await compter() == avant

    liste = await client.get(
        f"/api/v1/billing/organizations/{organization['id']}/invoices/{facture_id}/payment-attempts",
        headers=headers,
    )
    assert liste.status_code == 200
    assert all(item["status"] not in STATUTS_REUSSIS for item in liste.json())


async def test_ca4_aucune_tentative_reussie_en_base():
    # Pool neuf lié à la boucle courante (les connexions d'un test précédent sont liées à une boucle fermée).
    await engine.dispose()
    async with AsyncSessionLocal() as db:
        reussies = await db.scalar(
            select(func.count()).select_from(PaymentAttempt).where(PaymentAttempt.status.in_(STATUTS_REUSSIS))
        )
    assert reussies == 0


async def test_ca4_statut_provider_ne_signale_aucun_checkout(client: AsyncClient):
    response = await client.get("/api/v1/billing/payment-provider")
    assert response.status_code == 200
    assert response.json()["checkoutAvailable"] is False
    assert response.json()["mode"] == "test"
