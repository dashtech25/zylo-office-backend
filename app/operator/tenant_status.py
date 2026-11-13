"""Suspension et rétablissement d'un tenant (BE-134).

Une suspension ou un rétablissement est une **intention** dans `admin_command` (BE-124),
de classe `tenant.suspension` (registre BE-127). Le statut de suspension appartient au
domaine tenant (PH-07, table `tenant`, cycle de vie BE-185) : ce module n'écrit jamais
`tenant.status`. L'effet reste chez le domaine propriétaire (QE-ADM-22) ; aucun
exécuteur n'est branché ici, donc aucune commande de cette classe ne peut s'exécuter
avant que le domaine soit câblé.

Règles appliquées :
- droit (CA-1, CA-3) : `role_effectif` évalue le rôle sur la portée du tenant de la
  route. La classe n'a pas d'entrée dans `ROLES_PAR_CLASSE` : elle retombe sur
  `ROLES_GESTION` (fermé par défaut). Un agent L1 reçoit 403, et un gestionnaire du tenant
  A reçoit 403 sur le tenant B ;
- approbation (CA-2) : la classe exige une double validation (BE-127). L'intention est
  créée sans approbateur ; `app.operator.guard.executer_commande` lève 409
  `approval_required` tant qu'aucun approbateur distinct n'a décidé. Ce module n'ajoute
  donc aucune exécution qui contournerait la garde ;
- rétablissement (préconditions) : un rétablissement n'est demandé que si le tenant est
  à l'état `suspended`, sinon 409 `reinstatement_preconditions_non_remplies`. Décision
  provisoire : les préconditions PH-07 et PH-10 ne sont pas tranchées (QE-ADM-22). La
  seule précondition retenue est l'état courant ;
- idempotence (CA-5) : même clé et même corps renvoient l'intention existante (200),
  sans seconde ligne ; même clé avec un autre corps renvoie 409 ;
- preview (CA-4) : `effets_suspension` est enregistré dans
  `app.operator.preview.EFFETS_PAR_CLASSE`. La preview expose la connexion (utilisateurs du
  tenant), les opérations ouvertes, l'API, les exports et la facturation. Les textes
  d'effet sur l'API, les exports et la facturation sont provisoires (PH-07, PH-10).

Ce fichier ne contient que la logique ; les routes sont dans
`app.operator.tenant_status_router`.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.identity.models import Tenant
from app.operator.commands import ETAT_INTENTION, AdminCommand, role_effectif
from app.operator.preview import EFFETS_PAR_CLASSE
from app.rbac.models import UserRole

CLASSE_SUSPENSION = "tenant.suspension"
TYPE_OBJET_TENANT = "Tenant"
OPERATIONS = ("suspension", "reinstatement")
ETAT_SUSPENDU = "suspended"
ETATS_OPERATION_OUVERTE = (ETAT_INTENTION, "approuvee")


def erreur_preconditions_retablissement() -> AppError:
    """409 : le rétablissement n'est demandé que si le tenant est suspendu (BE-134)."""
    return AppError(
        code="reinstatement_preconditions_non_remplies",
        message="Le rétablissement exige un tenant suspendu.",
        status_code=409,
    )


def corps_commande(
    *,
    organization_id: uuid.UUID,
    operation: str,
    reason_ticket: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Corps d'intention au format de BE-124 ; l'opération est reprise dans la charge utile.

    La cible est le tenant lui-même (`Tenant`, identifiant de l'organisation de la route).
    """
    return {
        "commandType": CLASSE_SUSPENSION,
        "commandVersion": 1,
        "tenantId": organization_id,
        "targetObjectType": TYPE_OBJET_TENANT,
        "targetObjectId": str(organization_id),
        "targetVersionExpected": None,
        "reasonTicket": reason_ticket,
        "idempotencyKey": idempotency_key,
        "payload": {"operation": operation},
    }


async def role_pour_operation(db: AsyncSession, actor_id: uuid.UUID, organization_id: uuid.UUID) -> str:
    """Rôle qui autorise la commande sur la portée du tenant (403 sinon, CA-1 et CA-3)."""
    return await role_effectif(db, actor_id, CLASSE_SUSPENSION, organization_id)


async def exiger_tenant_suspendu(db: AsyncSession, organization_id: uuid.UUID) -> None:
    """409 si le tenant n'est pas à l'état `suspended` (préconditions du rétablissement).

    Un tenant sans ligne `tenant` n'est pas suspendu : la réponse est alors le même 409.
    """
    etat = (await db.execute(
        select(Tenant.status).where(Tenant.organizationId == organization_id)
    )).scalar_one_or_none()
    if etat != ETAT_SUSPENDU:
        raise erreur_preconditions_retablissement()


async def effets_suspension(db: AsyncSession, commande: AdminCommand) -> dict[str, Any]:
    """Effets listés par la preview (CA-4) : connexion, opérations ouvertes, API, exports, facturation.

    Les comptes (`utilisateursAffectes`, `commandesOuvertes`) sont lus en base ; les textes
    d'effet des rubriques API, exports et facturation sont provisoires. Les clés sont
    toujours présentes, pour que le schéma de la preview soit stable.
    """
    charge = commande.payload or {}
    utilisateurs = (await db.execute(
        select(func.count(func.distinct(UserRole.userId))).where(UserRole.organizationId == commande.tenantId)
    )).scalar_one()
    ouvertes = (await db.execute(
        select(func.count()).select_from(AdminCommand).where(
            AdminCommand.tenantId == commande.tenantId,
            AdminCommand.status.in_(ETATS_OPERATION_OUVERTE),
            AdminCommand.commandId != commande.commandId,
        )
    )).scalar_one()
    return {
        "operation": charge.get("operation"),
        "connexion": {
            "utilisateursAffectes": int(utilisateurs),
            "effet": "Accès des utilisateurs du tenant modifié par l'opération.",
        },
        "operationsEnCours": {"commandesOuvertes": int(ouvertes)},
        "api": {"effet": "NON DÉFINI : effet sur l'API à arbitrer (PH-07)."},
        "exports": {"effet": "NON DÉFINI : effet sur les exports à arbitrer (PH-07)."},
        "facturation": {"effet": "NON DÉFINI : effet sur la facturation à arbitrer (PH-10)."},
    }


EFFETS_PAR_CLASSE[CLASSE_SUSPENSION] = effets_suspension
