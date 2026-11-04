"""Évènements webhook de paiement : idempotence, refus et quarantaine (BE-029).

Ce module est le seul endroit qui décide ce qu'un évènement webhook de paiement
produit dans la base. La route d'entrée (`POST /api/v1/billing/webhooks/flutterwave`,
dans `app/billing/router.py`) ne fait que vérifier la signature puis déléguer ici.
La route et sa vérification de signature appartiennent à BE-083 ; ce module n'en
crée aucune.

Contrat, dans l'ordre d'exécution de `traiter_evenement_webhook` :

1. Signature. Seuls les évènements vérifiés sont traités. Un appel sans
   `signature_verifiee=True` est refusé (401 `webhook_signature_invalid`) avant
   toute lecture du contenu : rien n'est écrit.

2. Lecture. Le corps doit être du JSON objet (400 `webhook_payload_invalid`) et
   porter un identifiant d'évènement de 160 caractères au plus (400
   `webhook_event_id_missing`). Pour les évènements Flutterwave v3 sans `id`, l'identifiant
   est `type:data.id:status` : un passage « en attente » à « réussi » n'est pas pris
   pour un doublon.

3. Référence (CA-2, CA-4). La référence est `data.tx_ref`, qui doit être l'identifiant
   d'une tentative de paiement (`paymentAttempt.id`). Une référence inconnue, mal formée
   ou appartenant à une autre organisation que `organisation_id` (lorsque ce paramètre
   est fourni) est refusée en 404 `webhook_reference_unknown`. Le refus est
   volontairement identique pour « inexistant » et « hors périmètre » : aucune
   information n'est révélée sur les tentatives des autres organisations. Aucune ligne
   n'est écrite à cette étape.

4. Doublon et quarantaine (CA-1, CA-5). L'évènement est cherché par
   (fournisseur, identifiant) dans `paymentWebhookEvent` :
   - absent : traitement ci-dessous ;
   - présent, même empreinte de contenu (`payloadDigest`) : doublon. Renvoie
     `duplicate=True` sans aucun effet, même si l'effet d'origine a déjà été
     appliqué ;
   - présent, empreinte différente : contradiction. L'évènement existant passe en
     `outcome='quarantined'` avec `quarantinedAt` et `quarantineDigest` (empreinte du
     contenu contradictoire, dont le contenu n'est pas appliqué), puis 409
     `webhook_event_conflict`. Le contenu contradictoire n'a aucun effet métier.

5. Effet métier (CA-3). Seul un évènement `charge.completed` dont `data.status` vaut
   `successful` ou `failed` a un effet reconnu : la tentative passe de `pending` à
   `reported_successful` ou `reported_failed`. Ce statut signifie « le fournisseur
   l'annonce, non vérifié côté serveur » ; il ne règle aucune facture et n'accorde aucun
   entitlement (ce sont BE-024 et BE-027 qui en portent la règle). Les autres évènements
   sont enregistrés avec `outcome='ignored'` ; un évènement reconnu visant une tentative
   qui n'est plus `pending` est enregistré avec `outcome='ignored_state'`, sans changer
   la tentative.

6. Enregistrement. La ligne d'idempotence et l'effet métier sont écrits dans la même
   transaction : un échec entre les deux ne laisse ni ligne orpheline, ni effet sans
   trace. Une insertion concurrente du même évènement (violation de la contrainte
   unique) annule la transaction et est traitée comme un doublon.

Ce module ne fait aucun appel réseau au fournisseur et ne lit jamais le contenu
complet pour le stocker : seule l'empreinte SHA-256 du corps brut est conservée
(`payloadDigest`), ce qui évite de persister données de carte ou secrets marchands.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Invoice, PaymentAttempt, PaymentWebhookEvent, Subscription
from app.core.errors import AppError

FOURNISSEUR_FLUTTERWAVE = "flutterwave"
TYPE_EVENEMENT_PAIEMENT = "charge.completed"
STATUTS_FOURNISSEUR_RECONNUS = {"successful": "reported_successful", "failed": "reported_failed"}
STATUT_TENTATIVE_EN_ATTENTE = "pending"
LONGUEUR_MAX_IDENTIFIANT = 160


@dataclass(frozen=True)
class ResultatWebhook:
    """Issue d'un évènement traité.

    `duplicate` : vrai si l'évènement avait déjà été reçu avec le même contenu.
    `outcome` : état enregistré de l'évènement (`applied`, `ignored`, `ignored_state`,
    `quarantined` ou la valeur d'origine pour un doublon).
    """

    duplicate: bool
    outcome: str
    event_id: str


def _extraire_evenement(payload: dict) -> tuple[str, str, str, str | None]:
    """Renvoie (identifiant, type, statut fournisseur, référence) d'un évènement Flutterwave.

    Le statut et la référence viennent de `data`. Aucun champ n'est obligatoire ici :
    un évènement incomplet sera refusé ou ignoré par les étapes suivantes.
    """
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    type_evt = str(payload.get("event") or payload.get("type") or "unknown")
    identifiant = str(payload.get("id") or data.get("id") or "")
    statut = str(data.get("status", "unknown"))
    if not payload.get("id") and data:
        # Évènement v3 sans `id` : l'identifiant inclut le statut (voir docstring du module).
        identifiant = f"{type_evt}:{identifiant}:{statut}"
    reference = data.get("tx_ref")
    return identifiant, type_evt, statut, (str(reference) if reference is not None else None)


async def _tentative_pour_reference(
    db: AsyncSession, reference: str | None, organisation_id: uuid.UUID | None,
) -> PaymentAttempt:
    """Tentative visée par la référence, ou 404 `webhook_reference_unknown`.

    La recherche passe par la facture et l'abonnement pour connaître l'organisation.
    Si `organisation_id` est fourni, une tentative d'une autre organisation est traitée
    comme inconnue (CA-4).
    """
    try:
        identifiant_tentative = uuid.UUID(reference) if reference else None
    except ValueError:
        identifiant_tentative = None
    if identifiant_tentative is not None:
        requete = (
            select(PaymentAttempt)
            .join(Invoice, Invoice.id == PaymentAttempt.invoiceId)
            .join(Subscription, Subscription.id == Invoice.subscriptionId)
            .where(PaymentAttempt.id == identifiant_tentative)
        )
        if organisation_id is not None:
            requete = requete.where(Subscription.organizationId == organisation_id)
        tentative = await db.scalar(requete)
        if tentative is not None:
            return tentative
    raise AppError(
        code="webhook_reference_unknown",
        message="Référence de paiement inconnue : aucun évènement n'a été enregistré.",
        status_code=404,
    )


async def traiter_evenement_webhook(
    db: AsyncSession,
    *,
    corps: bytes,
    signature_verifiee: bool,
    request_id: str | None = None,
    organisation_id: uuid.UUID | None = None,
) -> ResultatWebhook:
    """Traite un évènement webhook de paiement vérifié (BE-029).

    Paramètres :
    - `corps` : contenu brut de la requête, tel que reçu (son empreinte est comparée) ;
    - `signature_verifiee` : doit valoir True, sinon l'évènement est refusé sans lecture ;
    - `request_id` : identifiant de corrélation, conservé pour la trace ;
    - `organisation_id` : périmètre optionnel. Lorsqu'il est fourni, seule une tentative
      de cette organisation peut être visée (CA-4).

    Retourne un `ResultatWebhook`. Lève `AppError` pour un refus (401, 400, 404 ou 409) ;
    dans ce cas aucune ligne d'effet n'a été écrite, sauf la mise en quarantaine (409)
    qui ne modifie que la ligne de l'évènement d'origine.
    """
    if not signature_verifiee:
        raise AppError(code="webhook_signature_invalid", message="Signature de webhook invalide.", status_code=401)
    try:
        payload = json.loads(corps)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError(code="webhook_payload_invalid", message="Payload webhook invalide.", status_code=400) from exc
    if not isinstance(payload, dict):
        raise AppError(code="webhook_payload_invalid", message="Payload webhook invalide.", status_code=400)

    identifiant, type_evt, statut, reference = _extraire_evenement(payload)
    if not identifiant or len(identifiant) > LONGUEUR_MAX_IDENTIFIANT:
        raise AppError(
            code="webhook_event_id_missing",
            message="Identifiant d'événement manquant ou invalide.",
            status_code=400,
        )

    tentative = await _tentative_pour_reference(db, reference, organisation_id)
    empreinte = hashlib.sha256(corps).hexdigest()

    existant = await db.scalar(select(PaymentWebhookEvent).where(
        PaymentWebhookEvent.provider == FOURNISSEUR_FLUTTERWAVE,
        PaymentWebhookEvent.eventId == identifiant,
    ))
    if existant is not None:
        if existant.payloadDigest == empreinte:
            return ResultatWebhook(duplicate=True, outcome=existant.outcome, event_id=identifiant)
        existant.outcome = "quarantined"
        existant.quarantinedAt = datetime.now(timezone.utc)
        existant.quarantineDigest = empreinte
        await db.commit()
        raise AppError(
            code="webhook_event_conflict",
            message="Cet identifiant d'événement a déjà été reçu avec un contenu différent.",
            status_code=409,
        )

    outcome = "ignored"
    if type_evt == TYPE_EVENEMENT_PAIEMENT and statut in STATUTS_FOURNISSEUR_RECONNUS:
        if tentative.status == STATUT_TENTATIVE_EN_ATTENTE:
            tentative.status = STATUTS_FOURNISSEUR_RECONNUS[statut]
            outcome = "applied"
        else:
            outcome = "ignored_state"

    db.add(PaymentWebhookEvent(
        provider=FOURNISSEUR_FLUTTERWAVE,
        eventId=identifiant,
        eventType=type_evt,
        payloadDigest=empreinte,
        signatureVerified=True,
        requestId=request_id,
        processedAt=datetime.now(timezone.utc),
        outcome=outcome,
    ))
    try:
        await db.commit()
    except IntegrityError:
        # Insertion concurrente du même évènement : la transaction entière est annulée
        # (effet métier compris), puis l'évènement gagnant est relu.
        await db.rollback()
        gagnant = await db.scalar(select(PaymentWebhookEvent).where(
            PaymentWebhookEvent.provider == FOURNISSEUR_FLUTTERWAVE,
            PaymentWebhookEvent.eventId == identifiant,
        ))
        if gagnant is None or gagnant.payloadDigest != empreinte:
            raise AppError(
                code="webhook_event_conflict",
                message="Cet identifiant d'événement a déjà été reçu avec un contenu différent.",
                status_code=409,
            )
        return ResultatWebhook(duplicate=True, outcome=gagnant.outcome, event_id=identifiant)
    return ResultatWebhook(duplicate=False, outcome=outcome, event_id=identifiant)
