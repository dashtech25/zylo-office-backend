"""Enveloppe d'événement commune et sa validation (BE-150).

Rôle : décrire, sous forme d'un modèle unique, les champs que doit porter tout événement de
domaine, et refuser avant distribution tout événement mal formé, de mauvais tenant ou contenant une
valeur secrète.

Champs (CA-1) : `eventId`, `eventType`, `schemaVersion`, `occurredAt` (ramené en UTC), `tenantId`,
`scope`, `actor`, `subject`, `dataClassification`, `correlationId`, `causationId`, `payload`.
Les champs nullables (`causationId`, par exemple) doivent être présents dans l'entrée, même à
`null` : leur absence est une erreur de schéma, pas une valeur par défaut silencieuse.

Codes d'erreur (catalogue complet : BE-151) :
- `SCHEMA_INVALID` (400) : champ obligatoire absent, type invalide, date sans fuseau, clé secrète
  dans le payload (CA-2, CA-5) ;
- `TENANT_MISMATCH` (403) : `tenantId` de l'enveloppe, ou `tenantId` / `organizationId` cité dans
  le payload, différent du tenant de l'identité authentifiée (CA-4). Le code HTTP 403 est une
  recommandation : NON DÉFINI dans la définition, à confirmer avec BE-151.

Invariant de sécurité : aucun message d'erreur ni aucune trace ne contient la valeur d'un champ
d'entrée. Les erreurs de validation Pydantic sont donc réduites à un message fixe, car elles
recopient la valeur fautive.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.errors import AppError

# Marqueurs de clés considérées comme secrètes (CA-5). La comparaison ignore la casse, les
# underscores et les tirets : `api_token`, `apiToken` et `API-TOKEN` sont tous refusés.
# Recommandation appliquée : liste fermée, à élargir par revue plutôt que par configuration.
MARQUEURS_CLE_SECRETE = ("password", "passwd", "secret", "token", "apikey", "motdepasse", "credential", "privatekey")

# Clés du payload qui désignent un tenant. Leur présence avec une autre valeur que le tenant de
# l'identité est un TENANT_MISMATCH (CA-4), pas une correction silencieuse.
CLES_TENANT_PAYLOAD = ("tenantId", "organizationId")


class EnveloppeEvenement(BaseModel):
    """Enveloppe validée d'un événement de domaine.

    Instance immuable. Toute construction passe par `valider_enveloppe`, qui garantit les
    invariants ci-dessus ; instancier ce modèle directement contourne la vérification de tenant
    et du secret et ne doit pas se faire hors de ce module.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    eventId: uuid.UUID = Field(description="Identifiant unique de l'événement ; clé de déduplication (CA-3).")
    eventType: str = Field(min_length=1, description="Nom de l'événement ; sert de clé d'abonnement dans app.shared.events.")
    schemaVersion: int = Field(ge=1, description="Version du schéma du payload, incrémentée à chaque changement incompatible.")
    occurredAt: datetime = Field(description="Instant de l'événement, toujours en UTC après validation.")
    tenantId: uuid.UUID = Field(description="Tenant (organisation) auquel appartient l'événement ; égal au tenant de l'identité.")
    scope: dict[str, Any] = Field(description="Portée de l'événement (type et identifiant de la ressource de portée).")
    actor: dict[str, Any] = Field(description="Acteur à l'origine de l'événement ; vide ou système pour un traitement automatique.")
    subject: dict[str, Any] = Field(description="Sujet métier concerné (type et identifiant).")
    dataClassification: str = Field(min_length=1, description="Classification de la donnée (ex. internal) ; guide la minimisation (BE-174).")
    correlationId: str | None = Field(description="Identifiant de corrélation d'une chaîne d'événements ; null si la chaîne commence ici.")
    causationId: str | None = Field(description="Identifiant de l'événement qui a causé celui-ci ; null pour une cause initiale.")
    payload: dict[str, Any] = Field(description="Données métier de l'événement, sans secret (CA-5).")

    @field_validator("occurredAt")
    @classmethod
    def _exiger_fuseau_et_ramener_en_utc(cls, valeur: datetime) -> datetime:
        """Refuse une date sans fuseau (ambiguë) et ramène toute date aware en UTC.

        Une date naïve serait interprétée selon le fuseau du serveur, ce qui change l'ordre des
        événements d'une machine à l'autre : elle est donc refusée plutôt que supposée UTC.
        """
        if valeur.tzinfo is None or valeur.utcoffset() is None:
            raise ValueError("occurredAt doit porter un fuseau horaire")
        return valeur.astimezone(timezone.utc)


def _cle_est_secrete(cle: str) -> bool:
    """Vrai si le nom de clé contient un marqueur secret, après normalisation."""
    normalisee = cle.lower().replace("_", "").replace("-", "")
    return any(marqueur in normalisee for marqueur in MARQUEURS_CLE_SECRETE)


def _contient_cle_secrete(valeur: Any) -> bool:
    """Parcourt récursivement dicts et listes à la recherche d'une clé secrète.

    La recherche porte sur les noms de clés uniquement : la valeur d'une clé secrète n'est jamais
    lue, ni renvoyée, ni journalisée.
    """
    if isinstance(valeur, Mapping):
        for cle, sous_valeur in valeur.items():
            if isinstance(cle, str) and _cle_est_secrete(cle):
                return True
            if _contient_cle_secrete(sous_valeur):
                return True
    elif isinstance(valeur, (list, tuple)):
        return any(_contient_cle_secrete(element) for element in valeur)
    return False


def valider_enveloppe(donnees: Mapping[str, Any], *, tenant_identite: uuid.UUID) -> EnveloppeEvenement:
    """Valide une enveloppe brute et renvoie sa forme canonique.

    Ordre des contrôles (le premier échec gagne) :
    1. schéma : champs obligatoires, types, date avec fuseau -> `SCHEMA_INVALID` ;
    2. secret : clé marquée secrète dans le payload -> `SCHEMA_INVALID` ;
    3. tenant : `tenantId` de l'enveloppe ou tenant cité dans le payload différent de
       `tenant_identite` -> `TENANT_MISMATCH`.

    Le tenant n'est jamais repris depuis l'entrée à la place de l'identité : l'entrée est seulement
    comparée. La fonction ne persiste rien et ne distribue rien.
    """
    try:
        enveloppe = EnveloppeEvenement.model_validate(dict(donnees))
    except ValidationError:
        # Pas de détail : les erreurs Pydantic recopient la valeur fautive (voir l'en-tête).
        raise AppError(code="SCHEMA_INVALID", message="Enveloppe d'événement invalide.", status_code=400)

    if _contient_cle_secrete(enveloppe.payload):
        raise AppError(
            code="SCHEMA_INVALID",
            message="Le payload contient une donnée secrète : événement refusé.",
            status_code=400,
        )

    if enveloppe.tenantId != tenant_identite:
        raise AppError(code="TENANT_MISMATCH", message="Le tenant de l'événement ne correspond pas à l'identité.", status_code=403)

    for cle in CLES_TENANT_PAYLOAD:
        if cle in enveloppe.payload and str(enveloppe.payload[cle]) != str(tenant_identite):
            raise AppError(code="TENANT_MISMATCH", message="Le payload cite un autre tenant que l'identité.", status_code=403)

    return enveloppe
