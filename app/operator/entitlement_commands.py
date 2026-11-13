"""Commande d'entitlement et de module (BE-135).

Une commande de classe `entitlement.module` demande un changement d'activation d'un
module pour une organisation. Elle ne modifie jamais un entitlement dérivé : seule
l'intention est enregistrée (table `admin_command`, BE-124), avec le module et
l'opération dans `admin_command.payload`. L'effet sur les droits reste chez le domaine
propriétaire (QE-ADM-22), donc aucun exécuteur n'est branché ici.

Règles appliquées :
- droit (CA-2, CA-3) : `role_effectif` évalue le rôle sur la portée du tenant de la
  route. La classe n'a pas d'entrée dans `ROLES_PAR_CLASSE` : elle retombe sur
  `ROLES_GESTION` (fermé par défaut). Un agent L2, ou un gestionnaire d'un autre tenant,
  reçoit donc 403 sans rien écrire ;
- preview (CA-4) : `effets_changement_module` est enregistré dans
  `app.operator.preview.EFFETS_PAR_CLASSE`. La preview liste le module visé et les
  utilisateurs qui portent un rôle de ce module dans l'organisation ;
- invalidation (CA-5) : l'intention écrit, dans la même transaction, un événement
  `Tenant.entitlement.cache_invalidation_requested` dans l'outbox (BE-166). Ce choix
  est provisoire : l'événement devrait naître à l'exécution, quand le domaine sera
  branché (QE-ADM-24) ;
- module inconnu : 422 `module_inconnu` (le module doit exister dans le catalogue).

Le module ne contient que la logique ; les routes sont dans
`app.operator.entitlement_commands_router`.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.evenements.outbox import enregistrer_evenement
from app.modules_registry.models import Module
from app.operator.commands import AdminCommand, role_effectif
from app.operator.preview import EFFETS_PAR_CLASSE
from app.rbac.models import Role, UserRole

CLASSE_ENTITLEMENT_MODULE = "entitlement.module"
TYPE_OBJET_TENANT = "Tenant"
TYPE_EVENEMENT_INVALIDATION_CACHE = "Tenant.entitlement.cache_invalidation_requested"
OPERATIONS = ("activation", "desactivation")


def erreur_module_inconnu() -> AppError:
    """422 : le code de module ne figure pas dans le catalogue."""
    return AppError(code="module_inconnu", message="Module inconnu du catalogue.", status_code=422)


def erreur_entitlement_derive() -> AppError:
    """405 : un entitlement dérivé ne s'écrit jamais directement (CA-1 de BE-135)."""
    return AppError(
        code="entitlement_derive_non_modifiable",
        message="Un entitlement dérivé ne se modifie pas directement : utiliser une commande.",
        status_code=405,
    )


def corps_commande(
    *,
    organization_id: uuid.UUID,
    module_code: str,
    operation: str,
    reason_ticket: str,
    idempotency_key: str,
    target_version_expected: int | None,
) -> dict[str, Any]:
    """Corps d'intention au format de BE-124, avec la charge utile du changement de module.

    La cible est le tenant lui-même (`Tenant`, id de l'organisation), ce qui permet à la
    preview BE-125 de lire la version de l'organisation.
    """
    return {
        "commandType": CLASSE_ENTITLEMENT_MODULE,
        "commandVersion": 1,
        "tenantId": organization_id,
        "targetObjectType": TYPE_OBJET_TENANT,
        "targetObjectId": str(organization_id),
        "targetVersionExpected": target_version_expected,
        "reasonTicket": reason_ticket,
        "idempotencyKey": idempotency_key,
        "payload": {"moduleCode": module_code, "operation": operation},
    }


async def exiger_module_connu(db: AsyncSession, module_code: str) -> None:
    """422 si `module_code` n'existe pas dans le catalogue `module`."""
    trouve = (await db.execute(select(Module.code).where(Module.code == module_code))).scalar_one_or_none()
    if trouve is None:
        raise erreur_module_inconnu()


async def role_pour_changement(db: AsyncSession, actor_id: uuid.UUID, organization_id: uuid.UUID) -> str:
    """Rôle qui autorise la commande sur la portée du tenant (403 sinon, CA-2 et CA-3)."""
    return await role_effectif(db, actor_id, CLASSE_ENTITLEMENT_MODULE, organization_id)


def _enveloppe_invalidation(commande: AdminCommand, actor_id: uuid.UUID) -> dict[str, Any]:
    """Enveloppe canonique (BE-150) de l'événement d'invalidation de l'intention."""
    charge = commande.payload or {}
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": TYPE_EVENEMENT_INVALIDATION_CACHE,
        "schemaVersion": 1,
        "occurredAt": datetime.now(timezone.utc),
        "tenantId": commande.tenantId,
        "scope": {"type": TYPE_OBJET_TENANT, "id": str(commande.tenantId)},
        "actor": {"type": "user", "id": str(actor_id)},
        "subject": {"type": "Module", "id": charge.get("moduleCode")},
        "dataClassification": "internal",
        "correlationId": commande.correlationId,
        "causationId": None,
        "payload": {
            "commandId": str(commande.commandId),
            "moduleCode": charge.get("moduleCode"),
            "operation": charge.get("operation"),
        },
    }


async def ecrire_evenement_invalidation(db: AsyncSession, commande: AdminCommand, actor_id: uuid.UUID) -> None:
    """Écrit l'événement d'invalidation dans la transaction de l'intention, sans commit (CA-5).

    Choix provisoire : l'émetteur est le tenant de la commande, pour satisfaire la règle
    `TENANT_MISMATCH` de l'outbox, bien que l'acteur soit un opérateur hors tenant.
    """
    await enregistrer_evenement(
        db,
        _enveloppe_invalidation(commande, actor_id),
        emetteur_tenant=commande.tenantId,
    )


async def effets_changement_module(db: AsyncSession, commande: AdminCommand) -> dict[str, Any]:
    """Effets listés par la preview (CA-4) : module visé et utilisateurs à rôle de module.

    Les utilisateurs sont ceux qui portent, dans l'organisation, un rôle dont
    `Role.moduleCode` est le module visé. La liste peut être vide ; les clés sont toujours
    présentes, pour que le schéma de la preview soit stable.
    """
    charge = commande.payload or {}
    code = charge.get("moduleCode")
    stmt = (
        select(UserRole.userId)
        .join(Role, Role.id == UserRole.roleId)
        .where(UserRole.organizationId == commande.tenantId, Role.moduleCode == code)
        .distinct()
    )
    utilisateurs = sorted(str(uid) for uid in (await db.execute(stmt)).scalars().all())
    return {
        "modulesAffectes": [{"moduleCode": code, "operation": charge.get("operation")}],
        "utilisateursAffectes": utilisateurs,
    }


EFFETS_PAR_CLASSE[CLASSE_ENTITLEMENT_MODULE] = effets_changement_module
