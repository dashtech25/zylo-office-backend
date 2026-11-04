from abc import ABC, abstractmethod
from dataclasses import dataclass
import os

from app.core.errors import AppError


@dataclass(frozen=True)
class CheckoutIntent:
    provider: str
    mode: str
    reference: str
    checkout_url: str | None = None


class PaymentProvider(ABC):
    """Interface abstraite — aucune implémentation réelle dans cette phase
    (grande_phases.md §10 : pas nécessaire d'intégrer un vrai prestataire de
    paiement maintenant). Un futur prestataire (Stripe, Mobile Money...)
    implémentera cette interface et sera branché dans billing/service.py au
    moment de la création/du renouvellement d'un Subscription, sans changer
    le modèle de données ni les endpoints existants."""

    @abstractmethod
    async def charge(self, amount_cents: int, currency: str, reference: str) -> bool:
        raise NotImplementedError

    async def create_checkout(self, amount_minor: int, currency: str, reference: str) -> CheckoutIntent:
        raise NotImplementedError


class FlutterwaveTestProvider(PaymentProvider):
    """Safe adapter boundary for a future Flutterwave sandbox integration.

    It intentionally performs no network request and never charges. Checkout
    remains unavailable until a reviewed sandbox client and server-side
    transaction verification are implemented.
    """

    provider = "flutterwave"
    mode = "test"

    async def charge(self, amount_cents: int, currency: str, reference: str) -> bool:
        raise AppError(code="provider_not_configured", message="Aucune transaction ne peut être initiée.", status_code=503)

    async def create_checkout(self, amount_minor: int, currency: str, reference: str) -> CheckoutIntent:
        # A live key can never silently enable checkout from this stub.
        sandbox_is_explicit = os.getenv("FLUTTERWAVE_MODE", "test").lower() == "test"
        sandbox_key_present = bool(os.getenv("FLUTTERWAVE_TEST_SECRET_KEY"))
        if not sandbox_is_explicit or not sandbox_key_present:
            raise AppError(code="provider_not_configured", message="Le paiement Flutterwave sandbox n'est pas configuré.", status_code=503)
        raise AppError(code="provider_not_configured", message="Le checkout sandbox n'est pas encore disponible; aucun paiement n'a été initié.", status_code=503)
