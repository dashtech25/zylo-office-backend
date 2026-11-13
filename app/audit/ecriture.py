"""Écriture d'audit fail-closed pour les mutations sensibles (BE-153).

Rôle : imposer, pour les services métier qui écrivent, deux garanties que
`record_audit_event` (BE-007) ne donne pas à elle seule :
- l'émetteur doit être authentifié et rattaché au tenant visé, sinon rien n'est
  écrit (refus `PERMISSION_DENIED` 403 ou `TENANT_MISMATCH`) ;
- pour une mutation sensible, la mutation et son entrée d'audit forment une seule
  unité : si l'audit échoue, la mutation est annulée et le code
  `AUDIT_WRITE_FAILED` (catalogue BE-151) est renvoyé.

Ce module ne définit aucune table ni code d'erreur nouveau. Il réutilise
`record_audit_event` (app/audit/service.py) pour l'écriture et `ErreurCatalogue`
(app/core/erreurs/codes.py) pour les erreurs. Modèle de référence :
app/audit/ecriture.md.

Transaction : chaque fonction ouvre un SAVEPOINT (`begin_nested`) autour de la
mutation et de l'audit. Un échec de l'audit annule le savepoint, donc la mutation,
sans toucher au reste de la transaction de l'appelant. L'appelant reste responsable
du `commit()` : une réussite n'est persistée qu'à ce commit.

Fail-closed et tolérance : la fermeture est la règle pour les mutations
(`executer_mutation_sensible`). Pour une lecture non sensible, l'échec d'audit est
tolérant (`executer_lecture_non_sensible`) : la valeur est rendue et l'échec est
journalisé. Cette tolérance est la recommandation de la définition ; la décision
humaine est ouverte (QE-PAR-05).
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue

journal = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class IdentiteEmettrice:
    """Identité authentifiée d'un émetteur d'audit.

    - `user_id` : l'acteur, écrit dans `actorUserId` ;
    - `organization_id` : le tenant de l'adhésion active de cet acteur. Une écriture
      visant un autre tenant est refusée (`TENANT_MISMATCH`).

    Le tenant vient du contexte serveur (app/core/tenant_context.py), jamais du corps
    de la requête. Un `None` à la place de l'identité signifie « non authentifié ».
    """

    user_id: uuid.UUID
    organization_id: uuid.UUID


def _verifier_emetteur(identite: IdentiteEmettrice | None, organization_id: uuid.UUID) -> IdentiteEmettrice:
    """Refuse toute écriture sans identité, ou visant un autre tenant que celui de l'identité.

    Appelée avant toute écriture : un refus n'a donc jamais d'effet de bord (CA-3, CA-4).

    Lève `ErreurCatalogue` `PERMISSION_DENIED` (403) si `identite` est `None`, et
    `TENANT_MISMATCH` (404, statut fixé par la fiche BE-151) si `organization_id` ne
    correspond pas au tenant de l'identité. Le message exposé ne révèle pas le tenant
    réel."""
    if identite is None:
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail="émetteur d'audit non authentifié")
    if identite.organization_id != organization_id:
        raise ErreurCatalogue(CodeErreur.TENANT_MISMATCH, detail="tenant de l'écriture différent de l'identité")
    return identite


async def _ecrire_audit(
    db: AsyncSession,
    identite: IdentiteEmettrice,
    organization_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    resume: str,
    changes: dict | None,
    result: str,
    motif: str | None = None,
) -> None:
    """Écrit l'entrée d'audit `result` via `record_audit_event`, dans le savepoint courant.

    `motif` (BE-227 CA-1) est stocké dans la colonne `reason` ; `None` pour les lectures.

    Toute exception de l'écriture (contrainte, injection de test, invariant d'audit) est
    convertie en `ErreurCatalogue` `AUDIT_WRITE_FAILED` (500). La cause est gardée dans
    `detail` pour le journal ; le message renvoyé au client est la phrase fixe de la fiche.
    """
    try:
        await record_audit_event(
            db,
            organization_id,
            identite.user_id,
            action,
            entity_type,
            entity_id,
            resume,
            changes,
            result=result,
            reason=motif,
        )
    except Exception as exc:
        raise ErreurCatalogue(CodeErreur.AUDIT_WRITE_FAILED, detail=f"{type(exc).__name__}: {exc}") from exc


async def executer_mutation_sensible(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    organization_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    resume: str,
    mutation: Callable[[AsyncSession], Awaitable[T]],
    changes: dict | Callable[[T], dict | None] | None = None,
    *,
    motif: str | None = None,
) -> T:
    """Exécute une mutation sensible et son entrée d'audit dans un même savepoint (CA-1).

    Ordre :
    1. contrôle de l'émetteur (`_verifier_emetteur`), sans écriture en cas de refus ;
    2. `mutation(db)` : la fonction fait ses écritures (flush inclus) et rend sa valeur ;
    3. entrée d'audit `success` avec `action`, `entity_type`, `entity_id`, `resume`.

    Si l'étape 3 échoue, le savepoint est annulé : la mutation disparaît, et
    `AUDIT_WRITE_FAILED` (500) est levé. Une exception levée par `mutation` elle-même
    est propagée telle quelle, après annulation du savepoint.

    Paramètres :
    - `identite` : émetteur authentifié, ou `None` (refus 403) ;
    - `organization_id` : tenant de la mutation, comparé à celui de l'identité ;
    - `action` : code d'action (ex. `organisation.renommer`), 150 caractères au plus ;
    - `entity_type`, `entity_id` : cible de l'action ;
    - `resume` : texte court pré-rendu, 500 caractères au plus ;
    - `mutation` : coroutine recevant la session ; elle ne doit pas appeler `commit()` ;
    - `changes` : détail facultatif, masqué des secrets par `record_audit_event`. Peut être
      un appelable recevant le résultat de `mutation` (BE-157 : le numéro de version n'existe
      qu'après la mutation) ; il est appelé dans le savepoint, après la mutation.
    - `motif` : justification de l'action (BE-227 CA-1), stockée dans `reason`. Optionnel
      pour ne pas casser les appelants existants ; une action privilégiée nouvelle le passe.

    Retour : la valeur rendue par `mutation`. L'appelant doit encore `commit()`.
    """
    emetteur = _verifier_emetteur(identite, organization_id)
    async with db.begin_nested():
        resultat = await mutation(db)
        detail = changes(resultat) if callable(changes) else changes
        await _ecrire_audit(
            db, emetteur, organization_id, action, entity_type, entity_id, resume, detail, "success", motif=motif
        )
    return resultat


async def executer_lecture_non_sensible(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    organization_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    resume: str,
    lecture: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    """Exécute une lecture non sensible ; un échec d'audit ne bloque pas la réponse (CA-2).

    Le refus d'émetteur (403, tenant différent) reste bloquant : la tolérance ne
    concerne que l'écriture d'audit elle-même. Si l'écriture échoue, l'échec est
    journalisé au niveau `ERROR` avec l'action et la cause, puis la valeur de `lecture`
    est rendue. Le savepoint isole cet échec : la transaction de l'appelant reste utilisable.
    """
    emetteur = _verifier_emetteur(identite, organization_id)
    resultat = await lecture(db)
    try:
        async with db.begin_nested():
            await _ecrire_audit(db, emetteur, organization_id, action, entity_type, entity_id, resume, None, "success")
    except ErreurCatalogue as exc:
        journal.error("Audit de lecture non écrit (tolérance BE-153 CA-2) : action=%s cause=%s", action, exc.detail_journal)
    return resultat
