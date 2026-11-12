"""Catalogue des codes d'erreur du domaine facturation (BE-070).

Ce module est le catalogue unique, lisible d'un seul tenant, des 17 codes
métier de la facturation. Il ne redéfinit pas l'enveloppe : chaque erreur
est une `AppError` (app/core/errors.py, BE-001) rendue sous
`{"error": {"code", "message", "field_errors", "details"}, "request_id"}`.

Règles tenues par ce catalogue :

- `code` est un identifiant MAJUSCULES stable : un client peut s'y fier.
- Le statut HTTP vient de QE-FAC-02 et QE-FAC-19 (POINTS-OUVERTS.md). Les
  codes absents de ces recommandations (`REFUND_LIMIT_EXCEEDED`,
  `ENTITLEMENT_SYNC_PENDING`, `RECONCILIATION_REQUIRED`, `APPROVAL_REQUIRED`)
  reçoivent un statut déduit de leur famille (garde d'état : 409 ; règle
  métier sur une valeur : 422) ; à confirmer par QE-FAC-02.
- Un objet hors périmètre (autre payeur, autre tenant) n'a pas de code
  dédié : il est répondu comme un objet inexistant, sans fuite d'existence.
- `RESULT_UNKNOWN` n'est jamais un échec : l'issue d'un paiement ou d'un
  appel fournisseur peut être inconnue. Ne jamais le convertir en `failed`.
- Le message est une phrase française sans détail interne (pas de trace,
  pas de SQL, pas d'identifiant fournisseur).

Usage : `raise billing_error(BillingErrorCode.DUPLICATE)` ; le message par
défaut peut être remplacé par un message propre à l'appel, sans détail
interne.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.errors import AppError


class BillingErrorCode(str, Enum):
    """Les 17 codes métier de la facturation. La valeur est le code exposé à l'API."""

    FORBIDDEN = "FORBIDDEN"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    QUOTE_EXPIRED = "QUOTE_EXPIRED"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    PRICE_NOT_CONFIGURED = "PRICE_NOT_CONFIGURED"
    TAX_NOT_CONFIGURED = "TAX_NOT_CONFIGURED"
    CURRENCY_NOT_CONFIGURED = "CURRENCY_NOT_CONFIGURED"
    PAYMENT_DECLINED = "PAYMENT_DECLINED"
    RESULT_UNKNOWN = "RESULT_UNKNOWN"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    DUPLICATE = "DUPLICATE"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    REFUND_LIMIT_EXCEEDED = "REFUND_LIMIT_EXCEEDED"
    ENTITLEMENT_SYNC_PENDING = "ENTITLEMENT_SYNC_PENDING"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


@dataclass(frozen=True)
class BillingErrorSpec:
    """Fiche d'un code : statut HTTP, issue, message par défaut et description.

    `outcome` précise ce qui s'est passé côté effet de bord :
    - `rejected` : refusé avant tout effet de bord ;
    - `failed` : tentative réelle qui a échoué (ex. paiement décliné) ;
    - `unknown` : issue inconnue, à réconcilier (jamais un échec) ;
    - `pending` : l'opération est acceptée mais une étape reste à faire.
    """

    code: BillingErrorCode
    http_status: int
    outcome: str
    message: str
    description: str


BILLING_ERRORS: dict[BillingErrorCode, BillingErrorSpec] = {
    BillingErrorCode.FORBIDDEN: BillingErrorSpec(
        code=BillingErrorCode.FORBIDDEN,
        http_status=403,
        outcome="rejected",
        message="Vous n'êtes pas autorisé à effectuer cette action.",
        description="L'appelant n'a pas la permission requise, quel que soit l'objet visé (ACTF-04 à ACTF-12).",
    ),
    BillingErrorCode.SCOPE_MISMATCH: BillingErrorSpec(
        code=BillingErrorCode.SCOPE_MISMATCH,
        http_status=403,
        outcome="rejected",
        message="Cette action ne porte pas sur le périmètre demandé.",
        description="La cible existe dans un autre périmètre (payeur, tenant bénéficiaire) que celui de la requête.",
    ),
    BillingErrorCode.INVALID_TRANSITION: BillingErrorSpec(
        code=BillingErrorCode.INVALID_TRANSITION,
        http_status=422,
        outcome="rejected",
        message="Cette transition d'état n'est pas permise pour l'objet courant.",
        description="La machine d'état de l'objet ne permet pas ce passage depuis son état actuel.",
    ),
    BillingErrorCode.QUOTE_EXPIRED: BillingErrorSpec(
        code=BillingErrorCode.QUOTE_EXPIRED,
        http_status=422,
        outcome="rejected",
        message="Ce devis a expiré et ne peut plus être accepté.",
        description="Le devis a dépassé sa date de validité ; il faut en établir un nouveau.",
    ),
    BillingErrorCode.CONSENT_REQUIRED: BillingErrorSpec(
        code=BillingErrorCode.CONSENT_REQUIRED,
        http_status=422,
        outcome="rejected",
        message="Un consentement requis n'a pas été donné.",
        description="Une version de consentement obligatoire manque pour cette action (BE-076).",
    ),
    BillingErrorCode.PRICE_NOT_CONFIGURED: BillingErrorSpec(
        code=BillingErrorCode.PRICE_NOT_CONFIGURED,
        http_status=422,
        outcome="rejected",
        message="Le prix de cette offre n'est pas configuré.",
        description="Aucun prix n'est résolu pour l'offre et la devise ; blocage, aucun prix n'est deviné (BE-078).",
    ),
    BillingErrorCode.TAX_NOT_CONFIGURED: BillingErrorSpec(
        code=BillingErrorCode.TAX_NOT_CONFIGURED,
        http_status=422,
        outcome="rejected",
        message="La taxe applicable n'est pas configurée.",
        description="Aucune règle de taxe n'est résolue pour le pays ou le produit ; blocage (BE-078).",
    ),
    BillingErrorCode.CURRENCY_NOT_CONFIGURED: BillingErrorSpec(
        code=BillingErrorCode.CURRENCY_NOT_CONFIGURED,
        http_status=422,
        outcome="rejected",
        message="La devise demandée n'est pas configurée.",
        description="La devise n'est pas autorisée pour cette offre ou ce payeur ; blocage (BE-078).",
    ),
    BillingErrorCode.PAYMENT_DECLINED: BillingErrorSpec(
        code=BillingErrorCode.PAYMENT_DECLINED,
        http_status=402,
        outcome="failed",
        message="Le paiement a été refusé.",
        description="Le fournisseur a décliné la tentative de paiement ; aucun droit n'est accordé (BE-082).",
    ),
    BillingErrorCode.RESULT_UNKNOWN: BillingErrorSpec(
        code=BillingErrorCode.RESULT_UNKNOWN,
        http_status=202,
        outcome="unknown",
        message="Le résultat de l'opération n'est pas encore connu ; il sera réconcilié.",
        description="L'issue côté fournisseur est incertaine (perte de réponse). Ce n'est jamais un échec (BE-095).",
    ),
    BillingErrorCode.PROVIDER_UNAVAILABLE: BillingErrorSpec(
        code=BillingErrorCode.PROVIDER_UNAVAILABLE,
        http_status=503,
        outcome="rejected",
        message="Le service de paiement est momentanément indisponible.",
        description="Le fournisseur ne répond pas ou n'est pas configuré ; aucun effet de bord n'a eu lieu.",
    ),
    BillingErrorCode.DUPLICATE: BillingErrorSpec(
        code=BillingErrorCode.DUPLICATE,
        http_status=409,
        outcome="rejected",
        message="Cette demande a déjà été traitée avec une autre requête.",
        description="Même clé d'idempotence avec un contenu différent ; rien n'est modifié (BE-072, QE-FAC-19).",
    ),
    BillingErrorCode.VERSION_CONFLICT: BillingErrorSpec(
        code=BillingErrorCode.VERSION_CONFLICT,
        http_status=409,
        outcome="rejected",
        message="L'objet a été modifié entre-temps. Relisez-le puis réessayez.",
        description="La version attendue (verrou optimiste) n'est plus la version courante ; rien n'est modifié (BE-072).",
    ),
    BillingErrorCode.REFUND_LIMIT_EXCEEDED: BillingErrorSpec(
        code=BillingErrorCode.REFUND_LIMIT_EXCEEDED,
        http_status=422,
        outcome="rejected",
        message="Le montant demandé dépasse la limite de remboursement autorisée.",
        description="Le remboursement dépasse le seuil ou le reliquat remboursable (BE-093).",
    ),
    BillingErrorCode.ENTITLEMENT_SYNC_PENDING: BillingErrorSpec(
        code=BillingErrorCode.ENTITLEMENT_SYNC_PENDING,
        http_status=409,
        outcome="pending",
        message="La mise à jour des droits est en attente de synchronisation.",
        description="Le changement de droits est demandé mais non encore appliqué (BE-085).",
    ),
    BillingErrorCode.RECONCILIATION_REQUIRED: BillingErrorSpec(
        code=BillingErrorCode.RECONCILIATION_REQUIRED,
        http_status=409,
        outcome="unknown",
        message="Une réconciliation est nécessaire avant de poursuivre.",
        description="L'état du paiement ou de l'abonnement doit être réconcilié avant l'action (BE-092, BE-095).",
    ),
    BillingErrorCode.APPROVAL_REQUIRED: BillingErrorSpec(
        code=BillingErrorCode.APPROVAL_REQUIRED,
        http_status=409,
        outcome="rejected",
        message="Une approbation humaine est requise pour cette action.",
        description="Le geste sensible n'a pas l'approbation exigée (ACTF-08) ; rien n'est exécuté (BE-087, BE-093).",
    ),
}


def billing_error(code: BillingErrorCode, message: str | None = None) -> AppError:
    """Construit l'`AppError` du code, avec son statut HTTP et son message.

    Le message par défaut du catalogue est utilisé sauf `message` explicite.
    Aucun détail interne ne doit être passé dans `message`.
    """
    spec = BILLING_ERRORS[BillingErrorCode(code)]
    return AppError(
        code=spec.code.value,
        message=message or spec.message,
        status_code=spec.http_status,
    )
