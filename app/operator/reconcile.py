"""Réconciliation des résultats inconnus et vérification post-action (BE-143).

Quand le domaine propriétaire ne sait pas si l'effet d'une commande a eu lieu, la garde
BE-126 pose la commande à `resultat_inconnu` et ne refait aucun appel (CA-5 de BE-126).
Ce module est la seule issue légitime de cet état, en deux temps :

1. `reconcilier_commande` (route `POST /api/v1/admin/commands/{id}/reconcile`) demande au
   domaine propriétaire ce qui s'est passé. Le réconciliateur ne lit que : il rapporte un
   effet `present`, `absent` ou `inconnu`, il n'écrit jamais dans l'état métier (CA-2).
   - `present` : l'effet a eu lieu ; la commande passe à `executee` avec le résultat du
     domaine ;
   - `absent` : l'effet n'a pas eu lieu ; la commande repasse à un état exécutable
     (`approuvee` si elle a une approbation, sinon `intention`). Une nouvelle exécution
     passe alors par la garde BE-126, qui transmet `commandId` comme clé d'idempotence
     d'origine (CA-4) ;
   - `inconnu` : rien ne change, la commande reste `resultat_inconnu` et bloque tout
     nouvel effet (CA-1).

2. `verifier_commande` (route `POST /api/v1/admin/commands/{id}/verify`) demande au
   propriétaire du domaine de contrôler l'état après action, l'absence d'effet dupliqué,
   et de rendre un verdict. Elle ne change pas le `status`.

Droits (fermés par défaut) :
- réconciliation : `ROLES_RECONCILIATION` (L2, opérateur plateforme, responsable de
  sécurité), sur la portée du tenant de la commande (égalité, BE-123) ; sinon 403 ;
- vérification : seul le propriétaire du domaine peut vérifier. Son rôle est fourni par
  `VERIFICATEURS` pour chaque type de commande. Sans entrée, personne ne vérifie : 403.
  Le rôle exact du propriétaire dépend de QE-ADM-22, non résolu.

Ordre des contrôles : existence (404), droit sur la portée (403), état (409), domaine
branché (409). Un compte sans droit ne reçoit donc jamais l'état de la commande.

Réentrance et bornes : le nombre maximal de reprises n'est pas fixé (QE-ADM-19). Ce
module ne le plafonne pas ; une réouverture n'est possible que si le domaine atteste
`absent`. La durée de validité de l'intention reste NULL (QE-ADM-90).

Chaque réconciliation et chaque vérification écrit un évènement d'audit (`audit_event`,
BE-007), avec l'état avant et après. Aucune table propre n'est créée : la migration n'est
pas nécessaire, le `status` `resultat_inconnu` existe déjà dans `admin_command` (BE-124).

Ce module ne dépend d'aucun module métier. Le domaine est branché par les tests, puis par
le domaine propriétaire une fois QE-ADM-22 résolu.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.admin_audit import ecrire_evenement_admin
from app.core.errors import AppError
from app.operator.approval import ETAT_APPROUVEE
from app.operator.cases import erreur_refus, portee_du_cas, roles_actifs_sur_portee
from app.operator.commands import ETAT_INTENTION, AdminCommand, erreur_commande_introuvable
from app.operator.guard import ETAT_EXECUTEE, ETAT_RESULTAT_INCONNU

ACTION_RECONCILIATION = "admin.command.reconciled"
ACTION_VERIFICATION = "admin.command.verified"

EFFET_PRESENT = "present"
EFFET_ABSENT = "absent"
EFFET_INCONNU = "inconnu"

# Rôles qui peuvent réconcilier une commande sur la portée de son tenant (BE-143).
ROLES_RECONCILIATION = frozenset({"agent_support_l2", "operateur_plateforme", "securite_incident_commander"})

# Réconciliateur d'un domaine : lit l'état du domaine et rapporte l'effet. Il ne doit rien
# écrire dans l'état métier. Il renvoie {"effet": "present", "resultat": dict} ou
# {"effet": "absent"} ou {"effet": "inconnu"}.
ReconciliateurDomaine = Callable[[AsyncSession, AdminCommand], Awaitable[dict[str, Any]]]

# Vérificateur d'un domaine : renvoie le verdict (dictionnaire) après action.
VerificateurDomaine = Callable[[AsyncSession, AdminCommand], Awaitable[dict[str, Any]]]

# Réconciliateur par `commandType`. Vide tant que QE-ADM-22 n'est pas résolu : la
# réconciliation est alors refusée (409 `domaine_non_branche`).
RECONCILIATEURS: dict[str, ReconciliateurDomaine] = {}

# Vérificateur par `commandType` : (rôles du propriétaire du domaine, vérificateur).
# Vide par défaut : la vérification est fermée (403) tant que le propriétaire n'est pas connu.
VERIFICATEURS: dict[str, tuple[frozenset[str], VerificateurDomaine]] = {}


def erreur_etat_non_reconciliable() -> AppError:
    """409 : seule une commande `resultat_inconnu` se réconcilie (CA-1)."""
    return AppError(
        code="command_etat_invalide",
        message="Seule une commande au résultat inconnu peut être réconciliée.",
        status_code=409,
    )


def erreur_domaine_non_branche() -> AppError:
    return AppError(
        code="domaine_non_branche",
        message="Aucun domaine propriétaire n'est branché pour ce type de commande.",
        status_code=409,
    )


def erreur_verification_inconnue() -> AppError:
    return AppError(
        code="verification_invalide",
        message="Le propriétaire du domaine n'a pas rendu de verdict exploitable.",
        status_code=409,
    )


async def _roles_sur_portee_de(db: AsyncSession, actor_id: uuid.UUID, commande: AdminCommand) -> set[str]:
    return await roles_actifs_sur_portee(db, actor_id, portee_du_cas(commande.tenantId))


async def reconcilier_commande(db: AsyncSession, *, command_id: uuid.UUID, actor_id: uuid.UUID) -> AdminCommand:
    """Réconcilie une commande `resultat_inconnu` et renvoie la commande (BE-143).

    Lève 404 si la commande n'existe pas, 403 si l'acteur n'a pas un rôle de
    `ROLES_RECONCILIATION` sur la portée du tenant (CA-3, CA-5), 409 si la commande n'est
    pas `resultat_inconnu` (CA-1) ou si aucun domaine n'est branché. Le réconciliateur ne
    modifie aucun état métier (CA-2) ; seule la commande et l'audit sont écrits.
    """
    commande = await db.get(AdminCommand, command_id)
    if commande is None:
        raise erreur_commande_introuvable()
    if not await _roles_sur_portee_de(db, actor_id, commande) & ROLES_RECONCILIATION:
        raise erreur_refus()
    if commande.status != ETAT_RESULTAT_INCONNU:
        raise erreur_etat_non_reconciliable()
    reconciliateur = RECONCILIATEURS.get(commande.commandType)
    if reconciliateur is None:
        raise erreur_domaine_non_branche()

    avant = commande.status
    rapport = await reconciliateur(db, commande)
    effet = rapport.get("effet") if isinstance(rapport, dict) else None

    if effet == EFFET_PRESENT and isinstance(rapport.get("resultat"), dict):
        commande.status = ETAT_EXECUTEE
        commande.result = {"reconciliation": EFFET_PRESENT, "resultat": rapport["resultat"]}
    elif effet == EFFET_ABSENT:
        commande.status = ETAT_APPROUVEE if commande.approverId is not None else ETAT_INTENTION
        commande.result = {"reconciliation": EFFET_ABSENT}
    else:
        # `inconnu`, ou rapport illisible : l'état reste bloquant (CA-1).
        effet = EFFET_INCONNU

    await ecrire_evenement_admin(
        db,
        organization_id=commande.tenantId,
        actor_user_id=actor_id,
        action=ACTION_RECONCILIATION,
        entity_type="admin_command",
        entity_id=commande.commandId,
        summary="Réconciliation d'une commande au résultat inconnu.",
        correlation_id=commande.correlationId or str(commande.commandId),
        changes={"effet": effet, "avant": avant, "apres": commande.status},
    )
    await db.commit()
    await db.refresh(commande)
    return commande


async def verifier_commande(db: AsyncSession, *, command_id: uuid.UUID, actor_id: uuid.UUID) -> dict[str, Any]:
    """Fait vérifier l'état après action par le propriétaire du domaine (BE-143).

    Renvoie `{"commandId", "status", "verification"}`. Lève 404 si la commande n'existe
    pas, 403 si aucun propriétaire n'est branché pour ce type (fermé par défaut) ou si
    l'acteur n'a pas le rôle du propriétaire sur la portée du tenant (CA-3), 409 si le
    verdict n'est pas un dictionnaire. Le `status` n'est pas modifié ; le verdict est
    tracé dans l'audit.
    """
    commande = await db.get(AdminCommand, command_id)
    if commande is None:
        raise erreur_commande_introuvable()
    branchement = VERIFICATEURS.get(commande.commandType)
    if branchement is None:
        raise erreur_refus()
    roles_proprietaire, verificateur = branchement
    if not await _roles_sur_portee_de(db, actor_id, commande) & roles_proprietaire:
        raise erreur_refus()

    verdict = await verificateur(db, commande)
    if not isinstance(verdict, dict):
        raise erreur_verification_inconnue()

    await ecrire_evenement_admin(
        db,
        organization_id=commande.tenantId,
        actor_user_id=actor_id,
        action=ACTION_VERIFICATION,
        entity_type="admin_command",
        entity_id=commande.commandId,
        summary="Vérification post-action par le propriétaire du domaine.",
        correlation_id=commande.correlationId or str(commande.commandId),
        changes={"status": commande.status},
    )
    await db.commit()
    return {"commandId": commande.commandId, "status": commande.status, "verification": verdict}
