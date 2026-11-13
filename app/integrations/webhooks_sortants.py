"""Webhook sortant : endpoints, livraisons signées, relance bornée et DLQ (BE-211).

Rôle : publier vers les endpoints d'un tenant les événements committés de l'outbox
(`app.evenements`), en signant chaque corps, en relançant les échecs et en mettant en lettre morte
ceux qui dépassent le maximum de tentatives.

Règles tenues par ce module :
- CA-1 : chaque requête porte `X-Zylo-Signature: t=<unix>,v1=<hex>`, où `v1` est le HMAC-SHA256
  hexadécimal de `"<t>." + corps brut`, avec la valeur du secret de l'endpoint. Signer le corps brut
  évite qu'une re-sérialisation change le message signé ; signer `t` empêche de rejouer un corps
  valide avec un horodatage neuf. Le récepteur vérifie avec `verifier_signature`.
- CA-2 : un échec (statut hors 2xx, erreur réseau, délai de 10 s dépassé) compte une tentative. Au
  maximum (`NOMBRE_MAX_TENTATIVES`, recommandation QE-API-16), la livraison passe en `dlq` et n'est plus
  retentée. Les relances s'espacent en intervalles croissants.
- CA-3 : une livraison n'est lue que par le tenant de son endpoint (`lire_livraison`) ; un autre tenant
  reçoit `TENANT_MISMATCH` (404), comme une livraison absente.
- CA-4 : la rotation garde l'ancienne valeur pendant `DUREE_CHEVAUCHEMENT_ROTATION`. Pendant cette
  fenêtre, `secrets_acceptes` la renvoie aux récepteurs ; après, elle n'est plus acceptée. Une
  seconde rotation pendant un chevauchement ferme le précédent.
- CA-5 : le corps ne contient que l'enveloppe minimisée (`corps_minimise`) : identifiant, type,
  version de schéma, instant, tenant. Le payload métier n'est pas envoyé ; le récepteur le relit par
  l'API.
- CA-6 : les routes exigent `integrations.manage` (voir `webhooks_sortants_router`).

Secrets : valeurs dans `COFFRE_WEBHOOKS_SORTANTS` (magasin en mémoire du processus, même choix que
BE-161 et BE-210) ; la base ne porte que la référence. Aucune valeur n'entre dans une ligne, un
`changes` d'audit ni un message d'erreur. La valeur n'est renvoyée qu'une fois, à la création et à
la rotation, dans la réponse de l'appelant autorisé.

Écart assumé, tranché sans attendre : la lecture de l'outbox passe par le modèle
`OutboxEvenement`, comme `app.notifications.consultation`. Les récepteurs sont authentifiés par la
signature seule ; aucune permission de tenant n'est ajoutée au récepteur.

Les fonctions ne commitent pas, sauf l'écriture d'audit faite par `executer_mutation_sensible` : l'appelant gère
la transaction.
"""

import datetime as dt
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from typing import Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice, executer_mutation_sensible
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.core.secrets import SecretStore
from app.evenements.models import OutboxEvenement
from app.integrations.models import (
    ETAT_ENDPOINT_ACTIF,
    ETAT_ENDPOINT_REVOQUE,
    STATUT_LIVRAISON_DLQ,
    STATUT_LIVRAISON_ECHOUEE,
    STATUT_LIVRAISON_EN_ATTENTE,
    STATUT_LIVRAISON_LIVREE,
    WebhookDelivery,
    WebhookEndpoint,
)

EN_TETE_SIGNATURE = "X-Zylo-Signature"
EN_TETE_EVENEMENT = "X-Zylo-Event-Id"
# Recommandations appliquées pour les points NON DÉFINI (POINTS-OUVERTS, QE-API-16 et QE-API-19).
NOMBRE_MAX_TENTATIVES = 5
ENVOI_TIMEOUT_SECONDES = 10.0
BASE_RELANCE_SECONDES = 30
FENETRE_ANTI_REJEU_SECONDES = 300
# Durée de chevauchement après rotation : non tranchée par la définition. Recommandation appliquée : 1 heure.
DUREE_CHEVAUCHEMENT_ROTATION = dt.timedelta(hours=1)

TYPE_ENTITE = "WebhookEndpoint"
ACTION_CREATION = "webhook_endpoint.cree"
ACTION_ROTATION = "webhook_endpoint.secret_roté"

# Coffre des secrets de signature sortants. Seules les références sortent en base.
COFFRE_WEBHOOKS_SORTANTS = SecretStore()


@dataclass(frozen=True)
class BilanLivraison:
    """Bilan d'un passage du dispatcher : livraisons réussies, échecs relancés, passées en DLQ."""

    livrees: int
    echecs: int
    en_dlq: int


def _nouvelle_reference(endpoint_id: uuid.UUID) -> str:
    """Nom unique d'une version de secret dans le coffre. Il ne contient jamais la valeur."""
    return f"webhook-sortant/{endpoint_id}/{uuid.uuid4().hex}"


def _introuvable() -> ErreurCatalogue:
    """Endpoint ou livraison absent ou d'un autre tenant : même réponse, sans révéler l'existence (CA-3)."""
    return ErreurCatalogue(CodeErreur.TENANT_MISMATCH, detail="webhook introuvable pour ce tenant")


async def _charger_endpoint(db: AsyncSession, organization_id: uuid.UUID, endpoint_id: uuid.UUID) -> WebhookEndpoint:
    """Charge l'endpoint s'il appartient au tenant ; sinon 404."""
    endpoint = await db.get(WebhookEndpoint, endpoint_id)
    if endpoint is None or endpoint.organizationId != organization_id:
        raise _introuvable()
    return endpoint


async def creer_endpoint(db: AsyncSession, identite: IdentiteEmettrice, *, url: str) -> tuple[WebhookEndpoint, str]:
    """Crée un endpoint actif, génère son secret et audite la création (CA-1 des données).

    Renvoie l'endpoint et la valeur du secret, la seule fois où elle sort du coffre. Le secret est
    déposé dans le coffre après le flush de la ligne ; un échec d'audit laisse une valeur orpheline,
    jamais référencée.
    """
    organization_id = identite.organization_id
    endpoint_id = uuid.uuid4()
    valeur = secrets.token_urlsafe(32)
    reference = _nouvelle_reference(endpoint_id)

    async def mutation(session: AsyncSession) -> WebhookEndpoint:
        endpoint = WebhookEndpoint(
            id=endpoint_id,
            organizationId=organization_id,
            url=url,
            secretRef=reference,
            state=ETAT_ENDPOINT_ACTIF,
        )
        session.add(endpoint)
        await session.flush()
        COFFRE_WEBHOOKS_SORTANTS.rotate(reference, valeur)
        return endpoint

    endpoint = await executer_mutation_sensible(
        db,
        identite,
        organization_id,
        ACTION_CREATION,
        TYPE_ENTITE,
        endpoint_id,
        "Endpoint de webhook sortant créé",
        mutation,
        {"state": ETAT_ENDPOINT_ACTIF},
    )
    return endpoint, valeur


async def faire_tourner_secret(
    db: AsyncSession,
    identite: IdentiteEmettrice,
    endpoint_id: uuid.UUID,
    *,
    maintenant: dt.datetime | None = None,
) -> tuple[WebhookEndpoint, str]:
    """Remplace le secret par une nouvelle valeur et ouvre la fenêtre de chevauchement (CA-4).

    L'ancienne valeur reste acceptée jusqu'à `overlapJusquA`. Une rotation sur un endpoint révoqué est
    refusée (409 `VERSION_CONFLICT`). La valeur de la version précédente, plus ancienne encore, est
    retirée du coffre.
    """
    maintenant = maintenant or dt.datetime.now(dt.timezone.utc)
    organization_id = identite.organization_id
    endpoint = await _charger_endpoint(db, organization_id, endpoint_id)
    if endpoint.state == ETAT_ENDPOINT_REVOQUE:
        raise ErreurCatalogue(CodeErreur.VERSION_CONFLICT, detail="rotation refusée : endpoint révoqué")

    valeur = secrets.token_urlsafe(32)
    nouvelle = _nouvelle_reference(endpoint_id)
    ancienne = endpoint.secretRef
    precedente_retiree = endpoint.secretPrecedentRef
    fin_overlap = maintenant + DUREE_CHEVAUCHEMENT_ROTATION

    async def mutation(session: AsyncSession) -> WebhookEndpoint:
        endpoint.secretPrecedentRef = ancienne
        endpoint.overlapJusquA = fin_overlap
        endpoint.secretRef = nouvelle
        await session.flush()
        COFFRE_WEBHOOKS_SORTANTS.rotate(nouvelle, valeur)
        return endpoint

    tournee = await executer_mutation_sensible(
        db,
        identite,
        organization_id,
        ACTION_ROTATION,
        TYPE_ENTITE,
        endpoint_id,
        "Secret de webhook sortant renouvelé",
        mutation,
        {"overlapJusquA": fin_overlap.isoformat()},
    )
    if precedente_retiree:
        COFFRE_WEBHOOKS_SORTANTS.supprimer(precedente_retiree)
    return tournee, valeur


async def lire_livraison(db: AsyncSession, organization_id: uuid.UUID, delivery_id: uuid.UUID) -> WebhookDelivery:
    """Livraison du tenant, pour consultation de son statut (CA-3). 404 si absente ou d'un autre tenant."""
    livraison = await db.get(WebhookDelivery, delivery_id)
    if livraison is None or livraison.organizationId != organization_id:
        raise _introuvable()
    return livraison


def _signature_hex(valeur: str, corps: bytes, horodatage: int) -> str:
    """HMAC-SHA256 hexadécimal de `"<t>." + corps`, avec la valeur du secret."""
    message = f"{horodatage}.".encode("utf-8") + corps
    return hmac.new(valeur.encode("utf-8"), message, hashlib.sha256).hexdigest()


def signer(valeur: str, corps: bytes, horodatage: int) -> str:
    """Valeur de l'en-tête `X-Zylo-Signature` : `t=<unix>,v1=<hex>` (CA-1)."""
    return f"t={horodatage},v1={_signature_hex(valeur, corps, horodatage)}"


def verifier_signature(
    entete: str,
    corps: bytes,
    valeurs: Iterable[str],
    maintenant: dt.datetime,
    fenetre_secondes: int = FENETRE_ANTI_REJEU_SECONDES,
) -> bool:
    """Vérifie un en-tête de signature côté récepteur, avec les valeurs acceptées à cet instant.

    Refus si l'en-tête est mal formé, si `t` sort de la fenêtre anti-rejeu (300 s), ou si aucune
    valeur acceptée ne reproduit la signature. La comparaison est à temps constant.
    """
    try:
        morceaux = dict(partie.split("=", 1) for partie in entete.split(","))
        horodatage = int(morceaux["t"])
        recue = morceaux["v1"]
    except (KeyError, ValueError):
        return False
    if abs(maintenant.timestamp() - horodatage) > fenetre_secondes:
        return False
    return any(hmac.compare_digest(_signature_hex(valeur, corps, horodatage), recue) for valeur in valeurs)


async def secrets_acceptes(db: AsyncSession, endpoint_id: uuid.UUID, maintenant: dt.datetime) -> list[str]:
    """Valeurs de secret qu'un récepteur accepte à `maintenant` : la courante, et l'ancienne pendant l'overlap (CA-4)."""
    endpoint = await db.get(WebhookEndpoint, endpoint_id)
    references = [endpoint.secretRef]
    if endpoint.secretPrecedentRef and endpoint.overlapJusquA and maintenant < endpoint.overlapJusquA:
        references.append(endpoint.secretPrecedentRef)
    valeurs = [COFFRE_WEBHOOKS_SORTANTS.valeur_courante(reference) for reference in references]
    return [valeur for valeur in valeurs if valeur]


def corps_minimise(evenement: OutboxEvenement) -> bytes:
    """Corps JSON canonique d'une livraison : seule l'enveloppe minimisée est envoyée (CA-5).

    Clés triées et séparateurs compacts, pour que le corps signé soit reproductible.
    """
    corps = {
        "eventId": str(evenement.eventId),
        "eventType": evenement.eventType,
        "schemaVersion": evenement.schemaVersion,
        "occurredAt": evenement.payload.get("occurredAt"),
        "tenantId": str(evenement.tenantId),
    }
    return json.dumps(corps, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _delai_relance(tentatives: int) -> dt.timedelta:
    """Délai avant la prochaine tentative : `BASE_RELANCE_SECONDES` doublé à chaque échec."""
    return dt.timedelta(seconds=BASE_RELANCE_SECONDES * 2 ** (tentatives - 1))


async def dispatcher_webhooks(
    db: AsyncSession,
    organization_id: uuid.UUID,
    *,
    maintenant: dt.datetime,
    client: httpx.AsyncClient,
) -> BilanLivraison:
    """Crée les livraisons manquantes puis tente celles qui sont dues, pour les endpoints actifs du tenant.

    Une livraison existe par couple (endpoint, événement) : relancer le dispatcher ne duplique rien.
    Une livraison dont le secret est absent du coffre n'est pas tentée (aucune tentative consommée).
    Le dispatcher ne commite pas.
    """
    endpoints = (
        await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.organizationId == organization_id,
                WebhookEndpoint.state == ETAT_ENDPOINT_ACTIF,
            )
        )
    ).scalars().all()
    if not endpoints:
        return BilanLivraison(livrees=0, echecs=0, en_dlq=0)

    evenements = (
        await db.execute(
            select(OutboxEvenement)
            .where(OutboxEvenement.tenantId == organization_id, OutboxEvenement.portee == "tenant")
            .order_by(OutboxEvenement.createdAt, OutboxEvenement.eventId)
        )
    ).scalars().all()
    evenements_par_id = {ligne.eventId: ligne for ligne in evenements}

    for endpoint in endpoints:
        deja_livres = set(
            (
                await db.execute(select(WebhookDelivery.eventId).where(WebhookDelivery.endpointId == endpoint.id))
            ).scalars().all()
        )
        for evenement in evenements:
            if evenement.eventId not in deja_livres:
                db.add(
                    WebhookDelivery(
                        endpointId=endpoint.id,
                        organizationId=organization_id,
                        eventId=evenement.eventId,
                        attempts=0,
                        status=STATUT_LIVRAISON_EN_ATTENTE,
                        nextAttemptAt=maintenant,
                    )
                )
    await db.flush()

    endpoints_par_id = {endpoint.id: endpoint for endpoint in endpoints}
    dues = (
        await db.execute(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.organizationId == organization_id,
                WebhookDelivery.status.in_([STATUT_LIVRAISON_EN_ATTENTE, STATUT_LIVRAISON_ECHOUEE]),
                WebhookDelivery.nextAttemptAt <= maintenant,
            )
            .order_by(WebhookDelivery.nextAttemptAt, WebhookDelivery.id)
        )
    ).scalars().all()

    livrees = echecs = en_dlq = 0
    for livraison in dues:
        endpoint = endpoints_par_id.get(livraison.endpointId)
        evenement = evenements_par_id.get(livraison.eventId)
        if endpoint is None or evenement is None:
            continue
        valeur = COFFRE_WEBHOOKS_SORTANTS.valeur_courante(endpoint.secretRef)
        if valeur is None:
            continue

        corps = corps_minimise(evenement)
        entete = signer(valeur, corps, int(maintenant.timestamp()))
        try:
            reponse = await client.post(
                endpoint.url,
                content=corps,
                headers={
                    "Content-Type": "application/json",
                    EN_TETE_SIGNATURE: entete,
                    EN_TETE_EVENEMENT: str(livraison.eventId),
                },
                timeout=ENVOI_TIMEOUT_SECONDES,
            )
            succes = 200 <= reponse.status_code < 300
        except httpx.HTTPError:
            succes = False

        livraison.attempts += 1
        if succes:
            livraison.status = STATUT_LIVRAISON_LIVREE
            livrees += 1
        elif livraison.attempts >= NOMBRE_MAX_TENTATIVES:
            livraison.status = STATUT_LIVRAISON_DLQ
            en_dlq += 1
        else:
            livraison.status = STATUT_LIVRAISON_ECHOUEE
            livraison.nextAttemptAt = maintenant + _delai_relance(livraison.attempts)
            echecs += 1
    await db.flush()
    return BilanLivraison(livrees=livrees, echecs=echecs, en_dlq=en_dlq)
