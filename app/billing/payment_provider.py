from abc import ABC, abstractmethod


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
