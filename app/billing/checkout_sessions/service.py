"""Service des sessions de paiement du portail (BE-110) : création idempotente et lecture d'état.

Une « session de paiement » est, dans ce code, un checkout de la table `checkout` (BE-081,
table propriétaire BE-202 selon QE-POR-29). Ce module n'ajoute aucune colonne ni aucune
migration : il enchaîne les services existants, sans les redéfinir.

Enchaînement d'une création (`creer_session_paiement`) :
1. `quotes.creer_devis` (BE-077) fige l'offre (BE-075) et résout le prix (BE-078) ;
2. `quotes.accepter_devis` accepte le devis ;
3. le consentement versionné est enregistré (`consent_record`, BE-076) pour le compte payeur,
   avec la personne qui agit et la version du texte reçue ;
4. `checkouts.creer_checkout` (BE-081) ouvre le checkout à `open` ;
5. l'événement `CheckoutSessionCreated` est écrit dans l'outbox, puis validé.

Idempotence (CA-1) : la commande est décorée par `idempotent_command` (BE-072). Un rejeu avec
la même clé et la même charge renvoie le checkout initial ; une charge différente renvoie 409.

Lecture (CA-3, CA-5) : seul l'état durable en base fait foi ; la query string du retour
navigateur n'est jamais lue. Une session dont le devis n'appartient pas au tenant est
`checkout_session_not_found` (404), identique à un identifiant inconnu.

Écart consigné : les services existants commit à chaque étape, donc la création n'est pas une
transaction unique. Si `creer_checkout` échoue après l'acceptation du devis, le devis reste
`accepted` sans checkout, et la clé d'idempotence est libérée : une nouvelle tentative crée un
nouveau devis. Ce cas ne produit aucun droit d'accès (BE-201 n'est pas appelé ici).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.checkouts.service import creer_checkout
from app.billing.events.emission import emettre_evenement_facturation
from app.billing.idempotency import idempotent_command
from app.billing.models import Checkout, ConsentRecord, PlanVersionSnapshot, Quote
from app.billing.quotes.service import accepter_devis, creer_devis
from app.core.errors import AppError

# Route logique entrée dans la portée d'idempotence (principal | route | clé).
ROUTE_IDEMPOTENCE = "portail.session_paiement.creer"
# Portée du consentement versionné enregistré avec la session (valeur de `consent_record.scope`).
PORTEE_CONSENTEMENT = "payeur"
# Nom de l'événement de contrat (BE-110) ; schéma de payload en version 1.
TYPE_EVENEMENT_SESSION = "CheckoutSessionCreated"
VERSION_SCHEMA_SESSION = 1


@idempotent_command(route=ROUTE_IDEMPOTENCE, result_model=Checkout, principal_arg="actor_user_id")
async def creer_session_paiement(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    idempotency_key: str,
    plan_code: str,
    scenario: str,
    payer_id: uuid.UUID,
    consent_text_version: str,
) -> Checkout:
    """Crée une session de paiement (checkout `open`) pour l'organisation, de façon idempotente.

    Erreurs remontées telles quelles : `FORBIDDEN` (403) sans permission d'acheteur de BE-077/081 ;
    `payer_not_found` (404) ; `plan_not_found` (404) ; erreurs de prix (BE-078) ; `DUPLICATE` (409)
    pour une clé réutilisée avec une autre charge. Une commande refusée libère sa clé.
    Le consentement est vérifié par l'appelant (400 `consent_required`) avant tout écrit.
    """
    devis = await creer_devis(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        plan_code=plan_code,
        scenario=scenario,
        payer_id=payer_id,
    )
    devis = await accepter_devis(
        db, organization_id=organization_id, actor_user_id=actor_user_id, quote_id=devis.id,
    )
    db.add(ConsentRecord(
        personId=actor_user_id,
        accountId=payer_id,
        consentTextVersion=consent_text_version,
        scope=PORTEE_CONSENTEMENT,
    ))
    await db.commit()
    checkout = await creer_checkout(
        db, organization_id=organization_id, actor_user_id=actor_user_id, quote_id=devis.id,
    )
    await emettre_evenement_facturation(
        db,
        _enveloppe_session(organization_id, actor_user_id, checkout),
        emetteur_tenant=organization_id,
    )
    await db.commit()
    return checkout


def _enveloppe_session(organization_id: uuid.UUID, actor_user_id: uuid.UUID, checkout: Checkout) -> dict:
    """Enveloppe de `CheckoutSessionCreated`. Le payload ne porte que des identifiants et l'état."""
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": TYPE_EVENEMENT_SESSION,
        "schemaVersion": VERSION_SCHEMA_SESSION,
        "occurredAt": datetime.now(timezone.utc).isoformat(),
        "tenantId": str(organization_id),
        "scope": {"type": "organization", "id": str(organization_id)},
        "actor": {"userId": str(actor_user_id)},
        "subject": {"type": "Checkout", "id": str(checkout.id)},
        "dataClassification": "internal",
        "correlationId": None,
        "causationId": None,
        "payload": {"checkoutSessionId": str(checkout.id), "quoteId": str(checkout.quoteId), "status": checkout.status},
    }


async def lire_session_paiement(db: AsyncSession, *, organization_id: uuid.UUID, checkout_id: uuid.UUID) -> Checkout:
    """Renvoie la session si son devis appartient à `organization_id`, sinon 404 `checkout_session_not_found`.

    Le contrôle de permission est fait par la route (`exiger_action`) avant cet appel.
    """
    session = await db.scalar(
        select(Checkout)
        .join(Quote, Quote.id == Checkout.quoteId)
        .where(Checkout.id == checkout_id, Quote.beneficiaryTenantId == organization_id)
    )
    if session is None:
        raise AppError(code="checkout_session_not_found", message="Session de paiement introuvable.", status_code=404)
    return session


async def offre_figee(db: AsyncSession, checkout: Checkout) -> dict:
    """Offre figée de la session : contenu de l'instantané capturé au devis (BE-075).

    Le devis pointe `planVersionSnapshotId` ; une publication ultérieure du catalogue crée une
    autre version et ne modifie pas cet instantané (CA-6).
    """
    devis = await db.get(Quote, checkout.quoteId)
    instantane = await db.get(PlanVersionSnapshot, devis.planVersionSnapshotId)
    return instantane.snapshotJson
