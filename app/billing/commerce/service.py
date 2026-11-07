"""Service BE-202 : devis, checkout et consentement d'essai.

Ce module est la seule porte d'écriture des trois commandes de BE-202. Chacune est décorée
par `idempotent_command` (app/billing/idempotency.py) : un rejeu avec la même `Idempotency-Key`
et les mêmes arguments renvoie le résultat initial sans second effet (CA-4) ; une clé réutilisée
avec d'autres arguments est refusée (`DUPLICATE`). Une commande refusée ne consomme pas sa clé.

Règles communes :
- Permission `billing.operate` revalidée à chaque commande (CA-1) : sans elle, `FORBIDDEN` (403).
  Ni le payeur ni un délégué n'ont cette autorité par eux-mêmes.
- Le tenant courant vient de l'en-tête `X-Organization-Id` ; un devis d'un autre tenant est
  traité comme inexistant (`quote_not_found`, 404, CA-3).

Règles par commande :
- Devis : la version de plan doit être `active` (publiée, BE-200) ; sinon
  `PLAN_VERSION_NOT_PUBLISHED` (422, CA-5). La version figée est capturée par BE-075. Un devis
  d'essai porte `isTrial`. Aucun prix n'est résolu ici (BE-078 hors périmètre de la fiche).
- Checkout : le devis doit être dans un état ouvert (`created`, `priced`, `accepted`). Un devis
  expiré renvoie `QUOTE_EXPIRED` (422) ; un autre état `INVALID_TRANSITION` (409). Un devis
  d'essai exige un consentement `trial` du payeur, sinon `TRIAL_CONSENT_REQUIRED` (422, CA-2).
  Le checkout s'ouvre à `open`. Il n'écrit aucun entitlement : la conséquence d'accès d'un
  paiement passe par BE-201 (CA-6).
- Consentement : le payeur doit exister (`payer_not_found`, 404). Le type est `trial` (seul
  type défini par la fiche ; les autres types restent NON DÉFINI).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import catalog_snapshot
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.idempotency import idempotent_command
from app.billing.models import BillingPayer, Checkout, Consent, Plan, PlanVersion, Quote
from app.billing.permissions import BILLING_OPERATE
from app.core.errors import AppError
from app.rbac.service import user_has_permission

ROUTE_DEVIS = "commerce.quote.create"
ROUTE_CHECKOUT = "commerce.checkout.create"
ROUTE_CONSENTEMENT = "commerce.consent.create"

STATUT_DEVIS_CREE = "created"
STATUT_DEVIS_EXPIRE = "expired"
ETATS_DEVIS_OUVERTS = frozenset({"created", "priced", "accepted"})
STATUT_VERSION_PUBLIEE = "active"
STATUT_CHECKOUT_OUVERT = "open"
TYPE_CONSENTEMENT_ESSAI = "trial"


async def _exiger_operateur(db: AsyncSession, actor_user_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    """Refuse 403 `FORBIDDEN` sans `billing.operate` sur le tenant (CA-1)."""
    if not await user_has_permission(db, actor_user_id, organization_id, BILLING_OPERATE):
        raise billing_error(BillingErrorCode.FORBIDDEN)


async def _exiger_payeur(db: AsyncSession, payer_id: uuid.UUID) -> None:
    """Refuse 404 `payer_not_found` si le compte payeur n'existe pas."""
    if await db.get(BillingPayer, payer_id) is None:
        raise AppError(code="payer_not_found", message="Compte payeur introuvable.", status_code=404)


@idempotent_command(route=ROUTE_DEVIS, result_model=Quote)
async def creer_devis(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    plan_version_id: uuid.UUID,
    payer_id: uuid.UUID,
    beneficiary_id: uuid.UUID | None,
    trial: bool,
    idempotency_key: str,
) -> Quote:
    """Crée un devis `created` pour le tenant, sur une version de plan publiée (CA-1, CA-5).

    Ordre des contrôles : permission (403) ; payeur (404) ; version de plan (404 si inconnue,
    422 `PLAN_VERSION_NOT_PUBLISHED` si son statut n'est pas `active`) ; capture de l'offre
    (BE-075) ; insertion. Rien n'est écrit en cas d'erreur.
    """
    await _exiger_operateur(db, actor_user_id, organization_id)
    await _exiger_payeur(db, payer_id)

    version = await db.get(PlanVersion, plan_version_id)
    if version is None:
        raise AppError(code="plan_version_not_found", message="Version de plan introuvable.", status_code=404)
    if version.status != STATUT_VERSION_PUBLIEE:
        raise AppError(
            code="PLAN_VERSION_NOT_PUBLISHED",
            message="Cette version de plan n'est pas publiée : un devis ne peut pas la référencer.",
            status_code=422,
        )
    plan = await db.get(Plan, version.planId)

    instantane = await catalog_snapshot.capturer_version_offre(
        db, organization_id=organization_id, plan_code=plan.code, actor_user_id=actor_user_id,
    )
    devis = Quote(
        payerId=payer_id,
        beneficiaryTenantId=organization_id,
        beneficiaryId=beneficiary_id,
        planVersionSnapshotId=instantane.id,
        status=STATUT_DEVIS_CREE,
        version=1,
        expiresAt=None,
        isTrial=trial,
    )
    db.add(devis)
    await db.commit()
    await db.refresh(devis)
    return devis


@idempotent_command(route=ROUTE_CHECKOUT, result_model=Checkout)
async def ouvrir_checkout(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    quote_id: uuid.UUID,
    idempotency_key: str,
) -> Checkout:
    """Ouvre un checkout `open` depuis un devis du tenant (CA-1, CA-2, CA-3).

    Ordre des contrôles : permission (403) ; devis du tenant (404 hors tenant ou inconnu) ;
    devis expiré (422 `QUOTE_EXPIRED`) ; état non ouvert (409 `INVALID_TRANSITION`) ;
    consentement d'essai si le devis est un essai (422 `TRIAL_CONSENT_REQUIRED`).
    """
    await _exiger_operateur(db, actor_user_id, organization_id)

    devis = await db.scalar(select(Quote).where(Quote.id == quote_id, Quote.beneficiaryTenantId == organization_id))
    if devis is None:
        raise AppError(code="quote_not_found", message="Devis introuvable.", status_code=404)

    expire_par_date = devis.expiresAt is not None and devis.expiresAt <= datetime.now(timezone.utc)
    if devis.status == STATUT_DEVIS_EXPIRE or expire_par_date:
        raise billing_error(BillingErrorCode.QUOTE_EXPIRED)
    if devis.status not in ETATS_DEVIS_OUVERTS:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    if devis.isTrial:
        consentement = await db.scalar(
            select(Consent.consentId).where(Consent.payerId == devis.payerId, Consent.kind == TYPE_CONSENTEMENT_ESSAI).limit(1)
        )
        if consentement is None:
            raise AppError(
                code="TRIAL_CONSENT_REQUIRED",
                message="Un essai exige le consentement explicite du payeur.",
                status_code=422,
            )

    checkout = Checkout(quoteId=devis.id, status=STATUT_CHECKOUT_OUVERT, version=1)
    db.add(checkout)
    await db.commit()
    await db.refresh(checkout)
    return checkout


@idempotent_command(route=ROUTE_CONSENTEMENT, result_model=Consent)
async def enregistrer_consentement(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payer_id: uuid.UUID,
    kind: str,
    idempotency_key: str,
) -> Consent:
    """Enregistre un consentement explicite du payeur (append-only, CA-1 pour le refus 403)."""
    await _exiger_operateur(db, actor_user_id, organization_id)
    await _exiger_payeur(db, payer_id)

    consentement = Consent(payerId=payer_id, kind=kind)
    db.add(consentement)
    await db.commit()
    await db.refresh(consentement)
    return consentement
