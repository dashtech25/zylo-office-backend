"""Adaptateur de paiement neutre du domaine facturation (BE-028).

Ce module ne contient aucun appel réseau et aucun débit réel : il définit
l'interface `PaymentProvider`, le résultat `CheckoutIntent` et l'adaptateur
sandbox `FlutterwaveTestProvider` à l'état de stub. Le fournisseur définitif
n'est pas choisi (QE-SOC-12) ; un vrai client viendra derrière la même interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import os

from app.core.errors import AppError


@dataclass(frozen=True)
class CheckoutIntent:
    """Résultat neutre d'une demande de checkout auprès d'un prestataire.

    `reference` est la référence INTERNE transmise à l'adaptateur (identifiant de
    la tentative de paiement côté Zylo), renvoyée telle quelle. Aucun champ ne
    porte l'identifiant d'une tentative issu du SDK du prestataire : celui-ci
    est stocké à part, dans `paymentAttempt.providerReference` (BE-028, CA-3).
    """

    provider: str
    mode: str
    reference: str
    checkout_url: str | None = None


class PaymentProvider(ABC):
    """Interface neutre d'un prestataire de paiement (BE-028).

    Contrat : le domaine facturation ne parle qu'à cette interface. Tout
    prestataire réel (Flutterwave, Stripe, Mobile Money...) s'y branche par un
    adaptateur ; le modèle `paymentAttempt` et les routes ne changent pas.

    Règles communes à tous les adaptateurs :
    - aucun débit réel : `charge` ne doit jamais créer de transaction en mode
      stub ou sandbox non configuré ;
    - aucun appel réseau pendant les tests (CA-1) ;
    - le mode live n'est accepté que si une configuration validée est présente ;
      sinon l'adaptateur lève `AppError` code `PROVIDER_UNAVAILABLE` (HTTP 503) ;
    - les identifiants internes de tentative sont générés par Zylo et passés en
      `reference` ; ils ne dépendent jamais du SDK du prestataire.

    Les méthodes lèvent `NotImplementedError` par défaut ; `charge` est abstraite
    et doit être implémentée par tout adaptateur concret.
    """

    @abstractmethod
    async def charge(self, amount_cents: int, currency: str, reference: str) -> bool:
        """Tente un débit de `amount_cents` (unités mineures) pour la référence interne `reference`.

        Retourne True si le prestataire confirme le débit. Un adaptateur sans
        configuration validée lève `AppError` (PROVIDER_UNAVAILABLE) au lieu de
        retourner False, pour qu'un échec de configuration ne soit jamais
        confondu avec un refus de paiement.
        """
        raise NotImplementedError

    async def rembourser(self, amount_minor: int, currency: str, reference: str) -> bool:
        """Demande au prestataire le remboursement de `amount_minor` pour la référence interne `reference`.

        Retourne True si le prestataire confirme le remboursement, False s'il le refuse. Un délai
        dépassé ou une erreur inattendue remonte en exception : l'issue est alors inconnue
        (BE-093, `pending`). Non implémenté par défaut : tout adaptateur qui rembourse le redéfinit.
        """
        raise NotImplementedError

    async def create_checkout(self, amount_minor: int, currency: str, reference: str) -> CheckoutIntent:
        """Ouvre un checkout chez le prestataire et renvoie un `CheckoutIntent`.

        Optionnel tant qu'aucun prestataire réel n'est branché. Un adaptateur
        qui ne sait pas ouvrir de checkout doit refuser avec `AppError`, jamais
        renvoyer une URL factice.
        """
        raise NotImplementedError


class FlutterwaveTestProvider(PaymentProvider):
    """Adaptateur Flutterwave en mode sandbox, à l'état de stub (BE-028).

    Frontière sûre pour une future intégration sandbox Flutterwave :
    - aucune requête réseau, jamais de débit ;
    - checkout refusé tant qu'un client sandbox relu et la vérification
      serveur de transaction ne sont pas implémentés ;
    - configuration lue dans l'environnement : `FLUTTERWAVE_MODE` (défaut
      `test`) et `FLUTTERWAVE_TEST_SECRET_KEY`. Tout mode autre que `test`
      (par exemple `live`) ou une clé sandbox absente est refusé en 503 : une
      clé live ne peut jamais activer le checkout depuis ce stub.
    """

    provider = "flutterwave"
    mode = "test"

    provider = "flutterwave"
    mode = "test"

    async def charge(self, amount_cents: int, currency: str, reference: str) -> bool:
        raise AppError(code="PROVIDER_UNAVAILABLE", message="Aucune transaction ne peut être initiée.", status_code=503)

    async def rembourser(self, amount_minor: int, currency: str, reference: str) -> bool:
        # Stub sandbox (BE-093) : aucun remboursement n'est initié, comme pour `charge`.
        raise AppError(code="PROVIDER_UNAVAILABLE", message="Aucun remboursement ne peut être initié.", status_code=503)

    async def create_checkout(self, amount_minor: int, currency: str, reference: str) -> CheckoutIntent:
        # A live key can never silently enable checkout from this stub.
        sandbox_is_explicit = os.getenv("FLUTTERWAVE_MODE", "test").lower() == "test"
        sandbox_key_present = bool(os.getenv("FLUTTERWAVE_TEST_SECRET_KEY"))
        if not sandbox_is_explicit or not sandbox_key_present:
            raise AppError(code="PROVIDER_UNAVAILABLE", message="Le paiement Flutterwave sandbox n'est pas configuré.", status_code=503)
        raise AppError(code="PROVIDER_UNAVAILABLE", message="Le checkout sandbox n'est pas encore disponible; aucun paiement n'a été initié.", status_code=503)
