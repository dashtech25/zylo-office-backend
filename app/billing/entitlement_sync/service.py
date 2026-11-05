"""Service de synchronisation des droits (BE-085).

Trois fonctions publiques, toutes scopées par le tenant bénéficiaire de l'abonnement :

- `demander_synchronisation` : crée une ligne `requested` pour l'abonnement. Verrou de ligne
  sur l'abonnement pour sérialiser les demandes concurrentes. Aucun droit n'est modifié ici :
  PH-09 reste la seule autorité.
- `enregistrer_resultat` : enregistre l'issue (`applied`, `failed` ou `retry_pending`) d'une
  synchronisation, selon `TRANSITIONS_SYNCHRONISATION`. Une transition absente renvoie
  `INVALID_TRANSITION` (409) sans écriture. `failed` et `applied` sont terminaux.
- `verifier_droits_confirmes` : lit la dernière demande de l'abonnement ; tant qu'elle n'est
  pas `applied` (ou qu'il n'y en a aucune), renvoie `ENTITLEMENT_SYNC_PENDING` (409).

Écarts consignés :
- La recommandation de QE-FAC-30 prévoit un appel interne à BE-024. Ce contrat n'est pas
  décrit ; l'issue d'application est donc fournie par l'appelant (`enregistrer_resultat`).
  Aucune route, aucune écriture sur `subscription_entitlement` dans cette tâche.
- Le critère « succeeded » de BE-085 correspond au statut `applied` de la table
  `entitlement_sync` tel que défini dans la fiche (requested | applied | failed | retry_pending).

Aucun fournisseur de paiement n'est appelé ici : une synchronisation n'est jamais un
paiement, et un échec de synchronisation ne relance aucune capture.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import EntitlementSync, Subscription
from app.billing.subscriptions.etats import charger_abonnement_du_tenant
from app.core.errors import AppError

STATUT_DEMANDEE = "requested"
STATUT_APPLIQUEE = "applied"
STATUT_ECHEC = "failed"
STATUT_NOUVELLE_TENTATIVE = "retry_pending"

# Statut courant -> issues permises. `applied` et `failed` sont terminaux.
TRANSITIONS_SYNCHRONISATION: dict[str, frozenset[str]] = {
    STATUT_DEMANDEE: frozenset({STATUT_APPLIQUEE, STATUT_ECHEC, STATUT_NOUVELLE_TENTATIVE}),
    STATUT_NOUVELLE_TENTATIVE: frozenset({STATUT_APPLIQUEE, STATUT_ECHEC}),
    STATUT_APPLIQUEE: frozenset(),
    STATUT_ECHEC: frozenset(),
}
ISSUES_POSSIBLES = frozenset({STATUT_APPLIQUEE, STATUT_ECHEC, STATUT_NOUVELLE_TENTATIVE})


async def demander_synchronisation(
    db: AsyncSession, *, tenant_id: uuid.UUID, subscription_id: uuid.UUID
) -> EntitlementSync:
    """Crée une demande `requested` pour l'abonnement du tenant, et la committe.

    Un abonnement d'un autre tenant ou inexistant renvoie `subscription_not_found` (404) :
    aucune information n'est révélée sur les autres tenants (CA-4).
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, tenant_id, verrou=True)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    demande = EntitlementSync(
        subscriptionId=abonnement.id,
        status=STATUT_DEMANDEE,
        attempts=0,
        lastErrorCode=None,
        requestedAt=datetime.now(timezone.utc),
    )
    db.add(demande)
    await db.commit()
    await db.refresh(demande)
    return demande


async def enregistrer_resultat(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    synchronisation_id: uuid.UUID,
    issue: str,
    code: str | None = None,
) -> EntitlementSync:
    """Enregistre l'issue d'une synchronisation du tenant, et la committe.

    `code` est le code d'erreur de synchronisation ; il est gardé pour `failed` et
    `retry_pending`, et effacé pour `applied`. Une synchronisation hors tenant ou inexistante
    renvoie `entitlement_sync_not_found` (404). Une issue non permise par la table renvoie
    `INVALID_TRANSITION` (409), sans écriture.
    """
    demande = await _charger_synchronisation(db, synchronisation_id, tenant_id)
    if demande is None:
        raise AppError(code="entitlement_sync_not_found", message="Synchronisation introuvable.", status_code=404)
    if issue not in ISSUES_POSSIBLES or issue not in TRANSITIONS_SYNCHRONISATION[demande.status]:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    demande.status = issue
    demande.attempts += 1
    demande.lastErrorCode = None if issue == STATUT_APPLIQUEE else code
    await db.commit()
    await db.refresh(demande)
    return demande


async def verifier_droits_confirmes(
    db: AsyncSession, *, tenant_id: uuid.UUID, subscription_id: uuid.UUID
) -> None:
    """Lève `ENTITLEMENT_SYNC_PENDING` tant que la dernière demande n'est pas `applied`.

    Aucune demande pour l'abonnement compte comme non confirmé : rien n'a été appliqué.
    Un abonnement hors tenant renvoie `subscription_not_found` (404). Ne modifie rien.
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, tenant_id)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)

    derniere = await db.scalar(
        select(EntitlementSync)
        .where(EntitlementSync.subscriptionId == abonnement.id)
        .order_by(EntitlementSync.requestedAt.desc())
        .limit(1)
    )
    if derniere is None or derniere.status != STATUT_APPLIQUEE:
        raise billing_error(BillingErrorCode.ENTITLEMENT_SYNC_PENDING)


async def _charger_synchronisation(
    db: AsyncSession, synchronisation_id: uuid.UUID, tenant_id: uuid.UUID
) -> EntitlementSync | None:
    """Ligne de synchronisation dont l'abonnement appartient au tenant, verrouillée, ou `None`."""
    return await db.scalar(
        select(EntitlementSync)
        .join(Subscription, Subscription.id == EntitlementSync.subscriptionId)
        .where(
            EntitlementSync.id == synchronisation_id,
            func.coalesce(Subscription.beneficiaryTenantId, Subscription.organizationId) == tenant_id,
        )
        .with_for_update(of=EntitlementSync)
    )
