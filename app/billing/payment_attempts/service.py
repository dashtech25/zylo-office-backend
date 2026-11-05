"""Service des tentatives de paiement d'un checkout (BE-082).

Seule porte d'écriture de `paymentAttempt` pour un checkout. Il réutilise, sans les redéfinir :
- `billing.idempotency` (BE-072) : portée, empreinte de commande, rejeu et `write_versioned` ;
- `billing.errors` (BE-070) : codes du catalogue ;
- `billing.payment_provider.PaymentProvider` (BE-028) : interface de l'adaptateur fournisseur.

Ordre des contrôles et des écritures d'une soumission :
1. Permission `billing.subscription.manage` (acheteur, ACTF-04) : sinon `FORBIDDEN`. Aucun
   appel fournisseur, aucune écriture.
2. Checkout du tenant courant (jointure sur `quote.beneficiaryTenantId`) : sinon
   `checkout_not_found` (404), identique à un identifiant inconnu (CA-4).
3. Rejeu idempotent (BE-072) : même clé et même commande renvoient la tentative initiale, sans
   second appel fournisseur. Même clé et commande différente : `DUPLICATE`.
4. Commande (décorée) :
   a. checkout `open` requis, sinon `INVALID_TRANSITION` (409) ;
   b. montant et devise lus dans le snapshot de prix du devis (BE-078), sinon
      `PRICE_NOT_CONFIGURED` ;
   c. tentative insérée à `created` et committée (CA-1) ;
   d. transitions `created -> submitted` (horodatée) et checkout `open -> pending`, committées
      AVANT tout appel fournisseur (CA-1) ;
   e. appel `charge` du fournisseur, borné par `DELAI_FOURNISSEUR_SECONDES`.

Issues de l'appel fournisseur :
- débit confirmé : tentative `pending` (la confirmation définitive vient du webhook, BE-083/084) ;
  le checkout reste `pending` ; jamais `succeeded` ni `completed` ici (CA-1 de BE-081) ;
- débit refusé (`False`) : tentative `failed`, checkout remis `open` pour une nouvelle tentative,
  erreur `PAYMENT_DECLINED` (402) ;
- délai dépassé : tentative `unknown`, checkout `pending`. Renvoyée sans erreur : la route répond
  202 (CA-2). Ce n'est JAMAIS un échec : l'issue réelle reste à réconcilier ;
- adaptateur indisponible (`PROVIDER_UNAVAILABLE`, aucune transaction initiée) : tentative
  `failed` sans référence fournisseur, checkout remis `open`, erreur 503 relancée ;
- autre exception inattendue : tentative `unknown` (une transaction a pu partir), puis l'exception
  est relancée. Aucune exception n'est avalée.

Décision (QE-FAC-02 et choix de remise à `open` après refus) : un refus ne consomme pas le
checkout, pour permettre une nouvelle tentative. Le statut `failed` du checkout n'est pas utilisé
par ce service.
"""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.idempotency import empreinte_portee, idempotent_command, portee_idempotence, write_versioned
from app.billing.models import Checkout, PaymentAttempt, Quote
from app.billing.payment_provider import PaymentProvider
from app.billing.permissions import SUBSCRIPTION_MANAGE
from app.core.errors import AppError
from app.rbac.service import user_has_permission

ROUTE_TENTATIVE_PAIEMENT = "billing.checkout.payment_attempt.create"
DELAI_FOURNISSEUR_SECONDES = 30.0

STATUT_CHECKOUT_OUVERT = "open"
STATUT_CHECKOUT_EN_ATTENTE = "pending"
STATUT_TENTATIVE_CREEE = "created"
STATUT_TENTATIVE_SOUMISE = "submitted"
STATUT_TENTATIVE_EN_ATTENTE = "pending"
STATUT_TENTATIVE_INCONNUE = "unknown"
STATUT_TENTATIVE_ECHOUEE = "failed"


async def soumettre_tentative(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    checkout_id: uuid.UUID,
    idempotency_key: str,
    fournisseur: PaymentProvider,
) -> PaymentAttempt:
    """Soumet un checkout `open` au fournisseur et renvoie la tentative dans son état final.

    Point d'entrée public. Les contrôles de permission et de tenant précèdent toute écriture et
    tout appel fournisseur (CA-3, CA-4). Les erreurs sont décrites dans la docstring du module.
    Le retour peut être une tentative `unknown` (délai) : la route la rend en 202.
    """
    if not await user_has_permission(db, actor_user_id, organization_id, SUBSCRIPTION_MANAGE):
        raise billing_error(BillingErrorCode.FORBIDDEN)

    checkout = await db.scalar(
        select(Checkout.id)
        .join(Quote, Quote.id == Checkout.quoteId)
        .where(Checkout.id == checkout_id, Quote.beneficiaryTenantId == organization_id)
    )
    if checkout is None:
        raise AppError(code="checkout_not_found", message="Checkout introuvable.", status_code=404)

    # Le fournisseur n'est pas un argument de la commande décorée : son empreinte (hachage du JSON
    # des arguments) ne doit dépendre que de la demande, pas de l'adresse mémoire de l'adaptateur.
    # Il est donc capturé par la fermeture, et la commande ne reçoit que des valeurs stables.
    @idempotent_command(route=ROUTE_TENTATIVE_PAIEMENT, result_model=PaymentAttempt, principal_arg="actor_user_id")
    async def commande(db: AsyncSession, *, actor_user_id: uuid.UUID, checkout_id: uuid.UUID, idempotency_key: str):
        return await _executer_tentative(
            db,
            actor_user_id=actor_user_id,
            checkout_id=checkout_id,
            idempotency_key=idempotency_key,
            fournisseur=fournisseur,
        )

    return await commande(db, actor_user_id=actor_user_id, checkout_id=checkout_id, idempotency_key=idempotency_key)


async def _executer_tentative(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    checkout_id: uuid.UUID,
    idempotency_key: str,
    fournisseur: PaymentProvider,
) -> PaymentAttempt:
    """Corps de la commande : transitions committées avant l'appel, puis issue de l'appel.

    Appelée uniquement par `soumettre_tentative`, sous `idempotent_command`. Une exception levée ici
    retire la réservation d'idempotence (la clé redevient utilisable), sauf après une tentative
    enregistrée, dont la ligne reste dans son état final.
    """
    checkout = await db.get(Checkout, checkout_id)
    if checkout is None or checkout.status != STATUT_CHECKOUT_OUVERT:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)
    devis = await db.get(Quote, checkout.quoteId)
    snapshot = devis.pricingSnapshotJson
    if not snapshot or snapshot.get("amountMinor") is None or not snapshot.get("currency"):
        raise billing_error(BillingErrorCode.PRICE_NOT_CONFIGURED)

    tentative = PaymentAttempt(
        checkoutId=checkout.id,
        invoiceId=None,
        provider=fournisseur.provider,
        mode=fournisseur.mode,
        idempotencyKey=empreinte_portee(portee_idempotence(actor_user_id, ROUTE_TENTATIVE_PAIEMENT, idempotency_key)),
        amountMinor=int(snapshot["amountMinor"]),
        currency=str(snapshot["currency"]),
        status=STATUT_TENTATIVE_CREEE,
        requestedAt=datetime.now(timezone.utc),
        version=1,
    )
    db.add(tentative)
    await db.commit()
    await db.refresh(tentative)

    # CA-1 : la tentative est `submitted` et le checkout `pending` AVANT l'appel fournisseur.
    tentative = await write_versioned(
        db, PaymentAttempt, tentative.id, expected_version=tentative.version,
        changes={"status": STATUT_TENTATIVE_SOUMISE, "submittedAt": datetime.now(timezone.utc)},
    )
    await write_versioned(
        db, Checkout, checkout.id, expected_version=checkout.version,
        changes={"status": STATUT_CHECKOUT_EN_ATTENTE},
    )

    try:
        confirme = await asyncio.wait_for(
            fournisseur.charge(tentative.amountMinor, tentative.currency, str(tentative.id)),
            timeout=DELAI_FOURNISSEUR_SECONDES,
        )
    except AppError as exc:
        if exc.code != BillingErrorCode.PROVIDER_UNAVAILABLE.value:
            await _marquer_inconnue(db, tentative)
            raise
        # Aucune transaction n'a été initiée : l'échec est certain, il n'y a rien à réconcilier.
        await _marquer_echec_et_rouvrir(db, tentative, checkout)
        raise
    except (TimeoutError, asyncio.TimeoutError):
        # CA-2 : pas de réponse à temps. L'issue est inconnue, jamais un échec.
        await _marquer_inconnue(db, tentative)
        return await db.get(PaymentAttempt, tentative.id)
    except Exception:
        await _marquer_inconnue(db, tentative)
        raise

    if confirme:
        return await write_versioned(
            db, PaymentAttempt, tentative.id, expected_version=tentative.version,
            changes={"status": STATUT_TENTATIVE_EN_ATTENTE},
        )
    await _marquer_echec_et_rouvrir(db, tentative, checkout)
    raise billing_error(BillingErrorCode.PAYMENT_DECLINED)


async def _marquer_inconnue(db: AsyncSession, tentative: PaymentAttempt) -> None:
    """Passe la tentative à `unknown` (version relue pour le verrou optimiste)."""
    actuelle = await db.get(PaymentAttempt, tentative.id)
    await db.refresh(actuelle)
    await write_versioned(
        db, PaymentAttempt, actuelle.id, expected_version=actuelle.version,
        changes={"status": STATUT_TENTATIVE_INCONNUE},
    )


async def _marquer_echec_et_rouvrir(db: AsyncSession, tentative: PaymentAttempt, checkout: Checkout) -> None:
    """Tentative `failed`, checkout de nouveau `open` pour permettre une nouvelle tentative."""
    actuelle = await db.get(PaymentAttempt, tentative.id)
    await db.refresh(actuelle)
    await write_versioned(
        db, PaymentAttempt, actuelle.id, expected_version=actuelle.version,
        changes={"status": STATUT_TENTATIVE_ECHOUEE},
    )
    ouvert = await db.get(Checkout, checkout.id)
    await db.refresh(ouvert)
    await write_versioned(
        db, Checkout, ouvert.id, expected_version=ouvert.version,
        changes={"status": STATUT_CHECKOUT_OUVERT},
    )
