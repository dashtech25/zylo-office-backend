"""Changement de configuration et gel de credential (BE-141).

Deux intentions opérateur, toutes deux de classe `configuration.modification` (registre
BE-127) et enregistrées dans `admin_command` (BE-124). Aucune table propre : une demande
de gel ou de changement n'est qu'une ligne de commande, son effet reste chez le domaine
propriétaire (BE-230 pour les credentials, BE-237 pour les réglages).

Charge utile (`admin_command.payload`) :
- changement de configuration : `action` = `config.change`, `settingKey` (clé du
  réglage, validée contre `settings_registry`), `valeurFournie` (booléen) et
  `valeurEmpreinte` (SHA-256 hexadécimal de la valeur). La valeur elle-même n'est jamais
  stockée ni renvoyée (CA-2) ; l'empreinte sert seulement à détecter un rejeu avec une
  autre valeur sous la même clé d'idempotence. Risque résiduel : une valeur très courte
  ou devinable peut être retrouvée par essai, d'où la consigne de ne pas envoyer de
  secret court (QE-ADM-141-a) ;
- gel de credential : `action` = `credential.freeze`, `credentialId` (identifiant de la
  ligne `secret_registry`) et `credentialName` (le nom de variable, jamais la valeur).

Droits :
- changement de configuration : rôle de gestion (`ROLES_GESTION`) sur la portée du
  tenant visé ; un gestionnaire d'un autre tenant reçoit 403 (CA-3) ;
- gel de credential : rôle sécurité / incident commander (`ROLES_GEL`) sur la portée
  plateforme ; un agent L2 reçoit 403 (CA-1). Le gel n'a pas de tenant : il n'est donc
  pas prévisualisable par BE-125 (voir QE-ADM-141-b).

Approbation (CA-4) : la classe exige une double validation. La garde d'exécution de
BE-126 (`app.operator.guard.executer_commande`) refuse l'exécution sans approbateur
distinct (409 `approval_required`) ; ce module ne contourne jamais cette garde.

Les routes HTTP sont dans `app.operator.config_security_router`.
"""

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.operator.cases import ROLES_GESTION, erreur_refus, portee_du_cas, roles_actifs_sur_portee
from app.operator.secrets_models import SecretRegistry
from app.settings.models import SettingsRegistry

CLASSE_CONFIGURATION = "configuration.modification"
TYPE_CIBLE_TENANT = "Tenant"
TYPE_CIBLE_CREDENTIAL = "Credential"
ACTION_CONFIG = "config.change"
ACTION_GEL = "credential.freeze"

# Rôle habilité à geler un credential : le responsable sécurité / incident commander.
# Hypothèse provisoire identique à QE-ADM-86 ; un rôle dédié relève de QE-ADM-89.
ROLES_GEL: frozenset[str] = ROLES_GESTION


def empreinte_valeur(valeur: str) -> str:
    """SHA-256 hexadécimal de la valeur : sert à la comparaison d'idempotence, jamais à l'affichage."""
    return hashlib.sha256(valeur.encode("utf-8")).hexdigest()


def erreur_reglage_inconnu() -> AppError:
    """422 : la clé ne figure pas dans le registre des réglages (BE-237)."""
    return AppError(code="reglage_inconnu", message="Réglage inconnu du registre.", status_code=422)


def erreur_credential_introuvable() -> AppError:
    """404 : l'identifiant ne désigne aucun credential du registre (BE-230)."""
    return AppError(code="credential_not_found", message="Credential introuvable.", status_code=404)


async def exiger_reglage_connu(db: AsyncSession, cle: str) -> None:
    """422 si la clé de réglage n'est pas déclarée. Aucune écriture n'a lieu avant ce contrôle."""
    trouve = (await db.execute(select(SettingsRegistry.key).where(SettingsRegistry.key == cle))).scalar_one_or_none()
    if trouve is None:
        raise erreur_reglage_inconnu()


async def credential_connu(db: AsyncSession, credential_id: uuid.UUID) -> SecretRegistry:
    """Ligne du credential, ou 404. Ne lit jamais une valeur de secret : le registre n'en porte pas."""
    ligne = (await db.execute(select(SecretRegistry).where(SecretRegistry.id == credential_id))).scalar_one_or_none()
    if ligne is None:
        raise erreur_credential_introuvable()
    return ligne


async def role_pour_configuration(db: AsyncSession, actor_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    """Rôle de gestion sur la portée du tenant visé (403 sinon, CA-3)."""
    actifs = await roles_actifs_sur_portee(db, actor_id, portee_du_cas(tenant_id))
    retenus = sorted(actifs & ROLES_GESTION)
    if not retenus:
        raise erreur_refus()
    return retenus[0]


async def role_pour_gel(db: AsyncSession, actor_id: uuid.UUID) -> str:
    """Rôle sécurité sur la portée plateforme (403 sinon, CA-1)."""
    actifs = await roles_actifs_sur_portee(db, actor_id, portee_du_cas(None))
    retenus = sorted(actifs & ROLES_GEL)
    if not retenus:
        raise erreur_refus()
    return retenus[0]


def corps_changement_configuration(
    *,
    organization_id: uuid.UUID,
    setting_key: str,
    valeur: str,
    reason_ticket: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Corps d'intention au format de BE-124 pour un changement de réglage (valeur absente)."""
    return {
        "commandType": CLASSE_CONFIGURATION,
        "commandVersion": 1,
        "tenantId": organization_id,
        "targetObjectType": TYPE_CIBLE_TENANT,
        "targetObjectId": str(organization_id),
        "targetVersionExpected": None,
        "reasonTicket": reason_ticket,
        "idempotencyKey": idempotency_key,
        "payload": {
            "action": ACTION_CONFIG,
            "settingKey": setting_key,
            "valeurFournie": True,
            "valeurEmpreinte": empreinte_valeur(valeur),
        },
    }


def corps_gel_credential(
    *,
    credential: SecretRegistry,
    reason_ticket: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Corps d'intention au format de BE-124 pour le gel d'un credential (sans valeur)."""
    return {
        "commandType": CLASSE_CONFIGURATION,
        "commandVersion": 1,
        "tenantId": None,
        "targetObjectType": TYPE_CIBLE_CREDENTIAL,
        "targetObjectId": str(credential.id),
        "targetVersionExpected": None,
        "reasonTicket": reason_ticket,
        "idempotencyKey": idempotency_key,
        "payload": {
            "action": ACTION_GEL,
            "credentialId": str(credential.id),
            "credentialName": credential.name,
        },
    }
