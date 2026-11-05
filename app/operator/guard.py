"""Garde de commande : pipeline d'exécution d'une commande opérateur (BE-126).

Le pipeline est le seul chemin qui fait passer une commande confirmée à l'état `executee`.
Il ne porte aucune logique métier : l'effet est appelé chez le domaine propriétaire
(QE-ADM-22), enregistré par type de commande dans `EXECUTEURS`. Sans domaine enregistré
pour un type, la commande est refusée (409 `domaine_non_branche`) avant toute écriture.

Ordre des étapes (CA-1, constante `ETAPES`) :
1. `autorisation` : l'acteur est l'initiateur de la commande (404 ou 403 sinon) ;
2. `tenant` : le tenant de la commande est re-résolu et égal à celui de la preview (409) ;
3. `etat` : la commande est encore `intention` ou `approuvee`, et un domaine est branché ;
4. `preview` : la preview est confirmée, non invalidée, non expirée, et l'empreinte de la
   cible n'a pas bougé (409) ;
5. `motif` : le motif (`reasonTicket`) est présent (422) ;
6. `approbation` : une classe à double validation exige une décision `approuvee` (409) ;
7. `revalidation` : rôle et affectation encore valides sur la portée au moment du commit (403) ;
8. `intention_audit` : l'intention d'audit est committée AVANT l'appel au domaine (CA-3) ;
9. `execution` : appel unique au domaine propriétaire ;
10. `verification` : le résultat retourné doit être un dictionnaire, sinon résultat inconnu ;
11. `notification` : NON DÉFINI (aucun canal branché) ; l'étape est tracée sans effet ;
12. `cloture` : statut `executee`, résultat enregistré, audit de clôture committé.

Résultat inconnu (CA-5) : si le domaine lève `ResultatInconnu`, ou rend autre chose qu'un
dictionnaire, la commande passe à `resultat_inconnu` et le pipeline lève 409. Aucun second
appel n'est fait : les états `resultat_inconnu`, `executee` et `echec` ne sont plus
exécutables. La réconciliation relève de BE-143. Une autre exception du domaine passe la
commande à `echec` (la transaction est annulée avant) puis est relevée telle quelle.

Idempotence : le domaine reçoit `commandId`, qui doit servir de clé d'idempotence chez
lui. Le pipeline ne rejoue jamais l'appel de lui-même.

Branchement : la route `POST /api/v1/admin/commands/{id}/confirm` de BE-125 ne déclenche
pas encore ce pipeline. Le brancher changerait la réponse de confirmation tant que le
domaine propriétaire n'est pas résolu (QE-ADM-22) ; c'est une ligne à ajouter dans
`app.operator.commands_router` une fois `EXECUTEURS` renseigné.

Ce module réutilise la garde d'initiateur et la preview de BE-125 (`app.operator.preview`),
le modèle de commande et la révision de rôle de BE-124 (`app.operator.commands`), le
registre des classes de BE-127 et l'écriture d'audit administrative de BE-122.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.audit.admin_audit import ecrire_evenement_admin
from app.operator.approval import ETAT_APPROUVEE
from app.operator.commands import ETAT_INTENTION, AdminCommand, role_effectif
from app.operator.preview import (
    RAISON_ETAT_MODIFIE,
    RAISON_EXPIREE,
    AdminCommandPreview,
    commande_de_l_initiateur,
    empreinte_etat,
    erreur_preview_introuvable,
    erreur_preview_invalide,
    etat_observable,
    lire_tenant_cible,
)
from app.operator.sensitive_classes import classe_par_code, exiger_approbation

ETAPES: tuple[str, ...] = (
    "autorisation",
    "tenant",
    "etat",
    "preview",
    "motif",
    "approbation",
    "revalidation",
    "intention_audit",
    "execution",
    "verification",
    "notification",
    "cloture",
)

ETAT_EXECUTEE = "executee"
ETAT_ECHEC = "echec"
ETAT_RESULTAT_INCONNU = "resultat_inconnu"
ETATS_EXECUTABLES = (ETAT_INTENTION, ETAT_APPROUVEE)

ACTION_INTENTION = "admin.command.intent_execution"
ACTION_CLOTURE = "admin.command.executed"


class ResultatInconnu(Exception):
    """Levée par un domaine propriétaire qui ne sait pas si l'effet a eu lieu (CA-5)."""


ExecuteurDomaine = Callable[[AsyncSession, AdminCommand], Awaitable[dict[str, Any]]]

# Domaine propriétaire par `commandType`. Vide tant que QE-ADM-22 n'est pas résolu : aucune
# commande ne peut alors être exécutée. Les tests injectent un domaine fictif.
EXECUTEURS: dict[str, ExecuteurDomaine] = {}


def _etape(etapes: list[str] | None, nom: str) -> None:
    """Trace l'étape franchie dans l'enregistreur, s'il est fourni (test d'ordre)."""
    if etapes is not None:
        etapes.append(nom)


def _erreur_tenant_modifie() -> AppError:
    return AppError(
        code="tenant_modifie",
        message="Le tenant de la commande a changé depuis la prévisualisation.",
        status_code=409,
    )


def _erreur_etat_non_executable() -> AppError:
    return AppError(
        code="command_etat_invalide",
        message="Cette commande ne peut plus être exécutée dans son état actuel.",
        status_code=409,
    )


def _erreur_domaine_non_branche() -> AppError:
    return AppError(
        code="domaine_non_branche",
        message="Aucun domaine propriétaire n'est branché pour ce type de commande.",
        status_code=409,
    )


def _erreur_resultat_inconnu() -> AppError:
    return AppError(
        code="resultat_inconnu",
        message="Le résultat de l'action est inconnu : aucune nouvelle tentative n'est faite.",
        status_code=409,
    )


async def _arreter_resultat_inconnu(db: AsyncSession, commande: AdminCommand) -> AppError:
    """Marque la commande `resultat_inconnu`, committe, et renvoie l'erreur à lever (CA-5)."""
    commande.status = ETAT_RESULTAT_INCONNU
    commande.result = {"etat": ETAT_RESULTAT_INCONNU}
    await db.commit()
    return _erreur_resultat_inconnu()


async def executer_commande(
    db: AsyncSession,
    *,
    command_id: uuid.UUID,
    actor_id: uuid.UUID,
    preview_id: uuid.UUID,
    etapes: list[str] | None = None,
) -> AdminCommand:
    """Exécute la commande confirmée par `preview_id`, ou lève l'erreur de l'étape refusée.

    Paramètres : `etapes`, si fourni, reçoit le nom de chaque étape franchie, dans l'ordre
    (sert au test d'ordre). Renvoie la commande à l'état `executee`.

    Erreurs : 404 (commande ou preview absente), 403 (initiateur différent, ou droit retiré
    au commit), 409 (tenant changé, état non exécutable, domaine non branché, preview
    invalide, approbation absente, résultat inconnu), 422 (motif ou type de commande
    invalide). Une erreur levée avant `intention_audit` n'écrit rien.
    """
    _etape(etapes, "autorisation")
    commande = await commande_de_l_initiateur(db, command_id, actor_id)
    commande_id = commande.commandId
    type_commande = commande.commandType
    tenant_id = commande.tenantId

    _etape(etapes, "tenant")
    if tenant_id is None:
        raise AppError(
            code="preview_tenant_absent",
            message="L'exécution exige un tenant cible.",
            status_code=422,
        )
    organisation = await lire_tenant_cible(db, commande)
    preview = await db.get(AdminCommandPreview, preview_id)
    if preview is None or preview.commandId != commande_id:
        raise erreur_preview_introuvable()
    if organisation.id != tenant_id or str(tenant_id) != preview.effects.get("tenantId"):
        raise _erreur_tenant_modifie()

    _etape(etapes, "etat")
    if commande.status not in ETATS_EXECUTABLES:
        raise _erreur_etat_non_executable()
    classe = classe_par_code(type_commande)
    if classe is None:
        raise AppError(
            code="command_type_unknown",
            message="Type de commande inconnu du registre des classes d'action sensible.",
            status_code=422,
        )
    domaine = EXECUTEURS.get(type_commande)
    if domaine is None:
        raise _erreur_domaine_non_branche()

    _etape(etapes, "preview")
    if preview.invalidatedReason is not None:
        raise erreur_preview_invalide(preview.invalidatedReason)
    if preview.confirmedAtUtc is None:
        raise erreur_preview_invalide("non_confirmee")
    if preview.expiresAtUtc <= datetime.now(timezone.utc):
        raise erreur_preview_invalide(RAISON_EXPIREE)
    if empreinte_etat(etat_observable(commande, organisation)) != preview.stateSnapshotHash:
        raise erreur_preview_invalide(RAISON_ETAT_MODIFIE)

    _etape(etapes, "motif")
    if not commande.reasonTicket.strip():
        raise AppError(code="motif_absent", message="Le motif de la commande est absent.", status_code=422)

    _etape(etapes, "approbation")
    if classe.requiresDoubleValidation:
        approbateur = commande.approverId if commande.status == ETAT_APPROUVEE else None
        exiger_approbation(classe, approbateur)

    _etape(etapes, "revalidation")
    await role_effectif(db, actor_id, type_commande, tenant_id)

    _etape(etapes, "intention_audit")
    correlation = commande.correlationId or str(commande_id)
    await ecrire_evenement_admin(
        db,
        organization_id=tenant_id,
        actor_user_id=actor_id,
        action=ACTION_INTENTION,
        entity_type="admin_command",
        entity_id=commande_id,
        summary="Intention d'exécution enregistrée avant l'appel au domaine propriétaire.",
        correlation_id=correlation,
        changes={"commandType": type_commande, "previewId": str(preview.previewId)},
    )
    await db.commit()

    _etape(etapes, "execution")
    try:
        resultat = await domaine(db, commande)
    except ResultatInconnu:
        raise await _arreter_resultat_inconnu(db, commande)
    except Exception:
        await db.rollback()
        commande.status = ETAT_ECHEC
        await db.commit()
        raise

    _etape(etapes, "verification")
    if not isinstance(resultat, dict):
        raise await _arreter_resultat_inconnu(db, commande)

    _etape(etapes, "notification")
    # NON DÉFINI : aucun canal de notification n'est branché à ce stade.

    _etape(etapes, "cloture")
    commande.status = ETAT_EXECUTEE
    commande.result = resultat
    await ecrire_evenement_admin(
        db,
        organization_id=tenant_id,
        actor_user_id=actor_id,
        action=ACTION_CLOTURE,
        entity_type="admin_command",
        entity_id=commande_id,
        summary="Commande exécutée par le domaine propriétaire.",
        correlation_id=correlation,
        changes={"commandType": type_commande},
    )
    await db.commit()
    return commande
