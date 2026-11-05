"""Webhook entrant d'un connecteur (BE-163) : signature, tenant et idempotence.

Route : `POST /api/v1/integrations/webhooks/{connecteur_id}`, sans authentification
utilisateur. L'émetteur externe s'authentifie par la signature de la requête, avec le secret
propre au connecteur. Ordre de traitement, qui détermine les codes renvoyés :

1. secret du connecteur résolu (`resoudre_secret_pour_envoi`, BE-161) : connecteur introuvable
   `404`, tenant de l'en-tête `X-Organization-Id` différent du tenant du connecteur
   `TENANT_MISMATCH` (`404`), secret expiré `SECRET_EXPIRED` ;
2. signature vérifiée sur le corps brut (`SIGNATURE_INVALID`, `401`) ;
3. horodatage signé dans la fenêtre anti-rejeu (`REPLAY_DUPLICATE`, `409`) ;
4. schéma minimal validé (`SCHEMA_INVALID`, `422`) ;
5. idempotence : doublon de `(connecteur, idExterne)` -> `200` avec `REPLAY_DUPLICATE` ;
   sinon insertion d'une ligne `webhook_recu` et `202`.

Une requête refusée aux étapes 1 à 4 n'écrit rien (CA-3, CA-4, CA-5).

Format de signature : en-tête `X-Zylo-Signature: t=<unix>,v1=<hex>`, où `v1` est le HMAC-SHA256
hexadécimal, avec la clé du connecteur, de `"<t>." + corps brut`. Signer le corps brut (et non
le JSON re-sérialisé) évite qu'une normalisation change le message signé ; signer `t` empêche
de rejouer un corps valide plus tard avec un horodatage neuf.

Fenêtre anti-rejeu : `WEBHOOK_FENETRE_ANTI_REJEU_SECONDS` (QE-PAR-09). Sans valeur configurée,
la réception échoue fermée en `503` : aucune valeur par défaut n'est codée.

Tenant : l'organisation de la ligne vient du connecteur, jamais de l'en-tête. L'en-tête ne sert
qu'à détecter une adresse vers un autre tenant ; il n'élargit jamais l'accès.

Écarts assumés, tranchés sans attendre :
- la colonne s'appelle `organizationId` (convention BE-007/BE-160), et non `tenantId` ;
- CA-2 renvoie `200` avec `REPLAY_DUPLICATE` dans le corps (succès idempotent), alors que
  CA-4 (hors fenêtre) renvoie l'erreur du catalogue, `409` ;
- la permission d'écriture explicite du credential (QE-PAR-11) n'est pas vérifiée ici : seul le
  secret propre au connecteur authentifie l'émetteur. État du connecteur non contrôlé (à ouvrir).
"""

import datetime as dt
import hashlib
import hmac
import json
import uuid

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.core.secrets import SecretStore
from app.integrations.models import STATUT_WEBHOOK_RECU, WebhookRecu
from app.integrations.secrets import SERVICE_INTEGRATION, resoudre_secret_pour_envoi

router = APIRouter()

EN_TETE_SIGNATURE = "X-Zylo-Signature"
EN_TETE_TENANT = "X-Organization-Id"
LONGUEUR_ID_EXTERNE_MAX = 255

# Coffre de processus, comme pour BE-161. Les tests le remplacent par `dependency_overrides`.
_COFFRE = SecretStore()


def get_coffre() -> SecretStore:
    """Coffre de secrets utilisé par la réception des webhooks (surchargeable en test)."""
    return _COFFRE


def _lire_signature(entete: str | None) -> tuple[int, str]:
    """Extrait `(t, v1)` de l'en-tête de signature.

    Un en-tête absent, sans `t` entier ou sans `v1` lève `SIGNATURE_INVALID` : le format
    mal formé est traité comme une signature fausse, sans précision utile à l'attaquant.
    """
    if not entete:
        raise ErreurCatalogue(CodeErreur.SIGNATURE_INVALID, detail="en-tête de signature absent")
    morceaux = dict(p.split("=", 1) for p in entete.split(",") if "=" in p)
    try:
        horodatage = int(morceaux["t"])
        signature = morceaux["v1"]
    except (KeyError, ValueError):
        raise ErreurCatalogue(CodeErreur.SIGNATURE_INVALID, detail="en-tête de signature mal formé") from None
    return horodatage, signature


def _signature_valide(secret: str, corps: bytes, horodatage: int, signature_recue: str) -> bool:
    """Vrai si `signature_recue` est le HMAC-SHA256 de `"<t>." + corps` sous `secret`.

    La comparaison passe par `hmac.compare_digest` pour ne pas révéler la signature attendue par
    le temps de réponse. Le secret n'est jamais journalisé.
    """
    message = f"{horodatage}.".encode("utf-8") + corps
    attendue = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(attendue.encode("ascii"), signature_recue.encode("utf-8", "replace"))


def _verifier_fenetre(horodatage: int, maintenant: dt.datetime) -> None:
    """Refuse un horodatage signé hors de la fenêtre anti-rejeu (CA-4).

    Lit la fenêtre à chaque appel, pour qu'une modification de configuration soit prise en compte.
    Fenêtre absente : `503`, réception fermée plutôt que fenêtre devinée.
    """
    fenetre = settings.WEBHOOK_FENETRE_ANTI_REJEU_SECONDS
    if fenetre is None:
        raise AppError(
            code="webhook_fenetre_non_configuree",
            message="Réception de webhook non configurée.",
            status_code=503,
        )
    if abs(int(maintenant.timestamp()) - horodatage) > fenetre:
        raise ErreurCatalogue(CodeErreur.REPLAY_DUPLICATE, detail="horodatage hors fenêtre anti-rejeu")


def _valider_schema(corps: bytes) -> tuple[str, str]:
    """Valide le schéma minimal et renvoie `(idExterne, typeEvenement)`.

    Schéma : objet JSON, `idExterne` et `typeEvenement` chaînes non vides, `idExterne` d'au plus
    255 caractères. Tout le reste est ignoré et non stocké (`payloadMinimal` ne garde que le type).
    """
    try:
        donnees = json.loads(corps)
    except (ValueError, UnicodeDecodeError):
        raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="corps non JSON") from None
    if not isinstance(donnees, dict):
        raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="corps non objet")
    id_externe = donnees.get("idExterne")
    type_evenement = donnees.get("typeEvenement")
    if not isinstance(id_externe, str) or not id_externe.strip() or len(id_externe) > LONGUEUR_ID_EXTERNE_MAX:
        raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="idExterne absent ou invalide")
    if not isinstance(type_evenement, str) or not type_evenement.strip():
        raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="typeEvenement absent ou invalide")
    return id_externe, type_evenement


def _lire_tenant(entete: str | None) -> uuid.UUID | None:
    """Tenant annoncé par l'en-tête, ou None si absent ou non UUID.

    None ne correspond à aucun connecteur de tenant : la requête est donc refusée en
    `TENANT_MISMATCH` (échec fermé).
    """
    if not entete:
        return None
    try:
        return uuid.UUID(entete)
    except ValueError:
        return None


async def _trouver_doublon(db: AsyncSession, connecteur_id: uuid.UUID, id_externe: str) -> WebhookRecu | None:
    """Ligne déjà reçue pour ce connecteur et cet `idExterne`, ou None (CA-2)."""
    return (
        await db.execute(
            select(WebhookRecu).where(
                WebhookRecu.connecteurId == connecteur_id,
                WebhookRecu.idExterne == id_externe,
            )
        )
    ).scalar_one_or_none()


def _reponse_doublon(ligne: WebhookRecu) -> JSONResponse:
    """Réponse `200` d'un doublon : succès idempotent, sans seconde ligne (CA-2)."""
    return JSONResponse(
        status_code=200,
        content={"code": CodeErreur.REPLAY_DUPLICATE.value, "webhookId": str(ligne.id), "statut": ligne.statut},
    )


@router.post("/webhooks/{connecteur_id}")
async def recevoir_webhook(
    connecteur_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    coffre: SecretStore = Depends(get_coffre),
    tenant: str | None = Header(default=None, alias=EN_TETE_TENANT),
    signature: str | None = Header(default=None, alias=EN_TETE_SIGNATURE),
) -> JSONResponse:
    """Reçoit un événement externe pour un connecteur. Voir le module pour l'ordre des contrôles.

    `202` avec `webhookId` pour un événement nouveau ; `200` avec `REPLAY_DUPLICATE` pour un
    doublon. Les refus renvoient l'enveloppe d'erreur du catalogue (BE-151).
    """
    corps = await request.body()
    maintenant = dt.datetime.now(dt.UTC)
    organization_id = _lire_tenant(tenant)

    valeur = await resoudre_secret_pour_envoi(
        db, coffre, SERVICE_INTEGRATION, connecteur_id, organization_id, maintenant
    )
    horodatage, signature_recue = _lire_signature(signature)
    if not _signature_valide(valeur, corps, horodatage, signature_recue):
        raise ErreurCatalogue(CodeErreur.SIGNATURE_INVALID, detail=f"connecteur {connecteur_id}")
    _verifier_fenetre(horodatage, maintenant)

    id_externe, type_evenement = _valider_schema(corps)

    doublon = await _trouver_doublon(db, connecteur_id, id_externe)
    if doublon is not None:
        return _reponse_doublon(doublon)

    ligne = WebhookRecu(
        connecteurId=connecteur_id,
        idExterne=id_externe,
        organizationId=organization_id,
        payloadMinimal={"typeEvenement": type_evenement},
        statut=STATUT_WEBHOOK_RECU,
    )
    db.add(ligne)
    try:
        await db.commit()
    except IntegrityError:
        # Course entre deux réceptions identiques : la contrainte d'unicité tranche (CA-2).
        await db.rollback()
        doublon = await _trouver_doublon(db, connecteur_id, id_externe)
        if doublon is None:
            raise
        return _reponse_doublon(doublon)
    return JSONResponse(
        status_code=202,
        content={"webhookId": str(ligne.id), "statut": STATUT_WEBHOOK_RECU},
    )
