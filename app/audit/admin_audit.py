"""Journal d'audit administratif, append-only (BE-122).

Ce module ne crée aucune table : il écrit et relit la seule table d'audit,
`audit_event` (propriétaire BE-007). Aucune colonne n'est ajoutée ici.

Correspondance entre le vocabulaire de la définition BE-122 et les colonnes de
BE-007 :
- `occurredAtUtc` = `createdAt` ; `actorId` = `actorUserId` ;
- `tenantId` = `organizationId` (NULL pour la portée plateforme) ;
- `objectType` / `objectId` = `entityType` / `entityId` ;
- `scope` = `scopeResourceType` / `scopeResourceId` ;
- `correlationId` = `request_id` ; `action` = `action` ;
- `result` = `result` (`success` | `refused` | `error`).

Garanties de l'écriture (`ecrire_evenement_admin`) :
- CA-1 : un identifiant de corrélation et une action non vides sont obligatoires ;
  sinon 422 et aucune ligne n'est ajoutée. La corrélation est passée explicitement
  et n'est jamais reprise d'un repli automatique (`sans-requete`), réservé au
  service BE-007 ;
- CA-5 : une clé marquée secret (mot de passe, jeton, condensat...) ou une clé de
  carte (PAN, CVV, CVC, numéro de carte) est rejetée en 422. Le service BE-007
  masque ces clés au lieu de les rejeter ; ce chemin-ci, plus strict, les refuse.

Correction (`enregistrer_correction`) : une erreur déjà journalisée se corrige
par une nouvelle entrée qui pointe l'original (`changes.corrigeEventId`). Aucun
UPDATE ni DELETE n'est jamais émis (CA-3).

Lecture : `GET /api/v1/admin/audit-events`, dans `app/operator/admin_audit_router.py`,
gardée par `require_admin_scope` (BE-120). Portée plateforme : seules les entrées
sans organisation sont renvoyées ; portée tenant : seules les entrées de ce tenant,
après contrôle d'affectation (sinon 403).

Immutabilité : le trigger BE-073 ne protège que les entrées `billing.*`.

QE (consignées, non créées par BE-122) :
- colonne demandée à BE-007 : actorService
- colonne demandée à BE-007 : authContext
- colonne demandée à BE-007 : category
- colonne demandée à BE-007 : reasonTicket
- colonne demandée à BE-007 : initiatorId
- colonne demandée à BE-007 : approverId
- colonne demandée à BE-007 : stateBeforeRef
- colonne demandée à BE-007 : stateAfterRef
- colonne demandée à BE-007 : notificationStatus
- colonne demandée à BE-007 : windowDuration
- QE-ADM-10 / PH-13 : immutabilité des entrées non financières non décidée ; le
  trigger ne couvre que `billing.*`, et le test CA-3 ne vérifie que ce périmètre.
- Rôle auditeur distinct : BE-121 (affectations globales) absent ; le droit de lecture
  repose sur l'autorité plateforme de BE-120 (liste d'exploitation).
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.audit.service import _CLE_CARTE, _CLE_SENSIBLE, record_audit_event
from app.core.errors import AppError

ACTION_CORRECTION = "audit.correction"


def _refus(code: str, message: str) -> AppError:
    return AppError(code=code, message=message, status_code=422)


def _cle_interdite(valeur: Any) -> str | None:
    """Renvoie la première clé secrète ou de carte trouvée (récursivement), sinon None.

    Seul le nom de la clé est renvoyé, jamais sa valeur : le message d'erreur ne
    doit pas reproduire le secret qu'il refuse."""
    if isinstance(valeur, dict):
        for cle, sous_valeur in valeur.items():
            if _CLE_SENSIBLE.search(str(cle)) or _CLE_CARTE.search(str(cle)):
                return str(cle)
            trouvee = _cle_interdite(sous_valeur)
            if trouvee is not None:
                return trouvee
    elif isinstance(valeur, list):
        for element in valeur:
            trouvee = _cle_interdite(element)
            if trouvee is not None:
                return trouvee
    return None


async def ecrire_evenement_admin(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    summary: str,
    correlation_id: str | None,
    changes: dict | None = None,
    scope_resource_type: str | None = None,
    scope_resource_id: uuid.UUID | None = None,
    result: str = "success",
) -> AuditEvent:
    """Ajoute une entrée d'audit administrative dans `audit_event`, sans la valider
    ni la commiter (l'appelant gère la transaction, comme BE-007).

    Lève `AppError` 422 et n'écrit rien si :
    - `correlation_id` est absent ou vide (`audit_correlation_absente`) ;
    - `action` est vide ou blanche (`audit_action_absente`) ;
    - `changes` contient une clé secrète ou de carte (`audit_donnee_interdite`).
    """
    if correlation_id is None or not correlation_id.strip():
        raise _refus("audit_correlation_absente", "Écriture d'audit refusée : identifiant de corrélation absent.")
    if not action or not action.strip():
        raise _refus("audit_action_absente", "Écriture d'audit refusée : action absente.")
    if changes is not None:
        cle = _cle_interdite(changes)
        if cle is not None:
            raise _refus(
                "audit_donnee_interdite",
                f"Écriture d'audit refusée : la clé « {cle} » désigne un secret ou une donnée de carte.",
            )
    return await record_audit_event(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        changes=changes,
        scope_resource_type=scope_resource_type,
        scope_resource_id=scope_resource_id,
        result=result,
        correlation_id=correlation_id,
    )


async def enregistrer_correction(
    db: AsyncSession,
    *,
    evenement_original: AuditEvent,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
    summary: str,
) -> AuditEvent:
    """Corrige une entrée par une entrée nouvelle qui la référence (CA-3).

    L'original n'est jamais modifié : la correction porte `changes.corrigeEventId`,
    l'`eventId` de l'entrée corrigée, et l'entité visée reste celle de l'original."""
    return await ecrire_evenement_admin(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=ACTION_CORRECTION,
        entity_type="AuditEvent",
        entity_id=evenement_original.id,
        summary=summary,
        correlation_id=correlation_id,
        changes={"corrigeEventId": evenement_original.eventId},
    )
