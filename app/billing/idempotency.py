"""Socle d'idempotence et de version optimiste de la facturation (BE-072).

Ce module est le seul endroit qui décide, pour une commande mutante, si la demande
est nouvelle, rejouée ou refusée. Il s'appuie sur trois mécanismes.

1. Portée (`scopeKey`) : `principal | route | clé`. Une clé n'a de sens que pour
   le principal qui l'a créée. Un autre principal qui envoie la même clé obtient
   le comportement d'une clé inconnue : il ne reçoit jamais le résultat d'autrui
   et aucune erreur ne révèle l'existence de la clé (CA-4).

2. Empreinte de commande (`commandHash`) : SHA-256 des arguments métier
   (hors `db`, principal, clé et `request_id`). Même portée et même empreinte :
   le résultat initial est renvoyé sans effet de bord (CA-1). Même portée et
   empreinte différente : `DUPLICATE`, rien n'est modifié (CA-2). Une demande
   encore en cours (statut `pending`) est traitée de la même façon.

3. Version optimiste (`version`, entier, défaut 1) sur `subscription` et
   `invoice` : `write_versioned` n'écrit que si la version attendue est encore
   la version courante, puis incrémente. Sinon `VERSION_CONFLICT`, sans
   modification (CA-3). `quote` n'a pas encore de table dans le code ; sa
   colonne `version` viendra avec sa table.

Cycle d'une commande décorée par `idempotent_command` :
- lecture de la portée : existante et terminée → résultat rejoué ; existante
  autrement → `DUPLICATE` ;
- sinon réservation (ligne `pending`) validée en base, puis exécution de la
  commande ;
- succès : la ligne passe à `completed` avec `resultRef` = id du résultat ;
- échec : la ligne est supprimée, la clé redevient utilisable (une commande
  refusée n'« consomme » pas sa clé).

Compatibilité jusqu'à migration : `invoice.idempotencyKey` reste unique. La
valeur stockée est l'empreinte de la portée (`empreinte_portee`), pas la clé
brute, pour qu'un autre principal ne se heurte pas à la contrainte.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import IdempotencyRecord

STATUT_EN_ATTENTE = "pending"
STATUT_TERMINE = "completed"

# Arguments qui ne font pas partie de la commande : la connexion, la portée
# (principal, clé) et l'identifiant de requête (trace, change à chaque appel).
_ARGUMENTS_HORS_EMPREINTE = frozenset({"db", "idempotency_key", "request_id"})


def portee_idempotence(principal_id: uuid.UUID | str, route: str, idempotency_key: str) -> str:
    """Portée d'une clé : principal, route et clé séparés par `|`.

    Le séparateur n'apparaît dans aucun des trois champs (route en points, identifiant
    en UUID), donc deux portées distinctes ne peuvent pas se confondre.
    """
    return f"{principal_id}|{route}|{idempotency_key}"


def empreinte_portee(scope_key: str) -> str:
    """SHA-256 hexadécimal (64 caractères) d'une portée.

    Sert de valeur à `invoice.idempotencyKey` (colonne 120 caractères, unique) :
    la clé brute n'y est jamais stockée, et deux principaux ne partagent pas la valeur.
    """
    return hashlib.sha256(scope_key.encode("utf-8")).hexdigest()


def empreinte_commande(arguments: dict[str, Any]) -> str:
    """SHA-256 hexadécimal des arguments métier, sérialisés en JSON canonique.

    Les clés sont triées et les valeurs non sérialisables (UUID, datetime) passent
    par `str`, pour qu'une même commande produise toujours la même empreinte.
    """
    canonique = json.dumps(arguments, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


def idempotent_command(*, route: str, result_model: type, principal_arg: str = "actor_user_id") -> Callable:
    """Décorateur d'une commande mutante de facturation (CA-1 à CA-4).

    La fonction décorée doit accepter `db` en premier argument, un argument
    `idempotency_key` et un argument de principal nommé `principal_arg`.
    Elle renvoie une instance de `result_model` dont l'attribut `id` identifie le
    résultat : c'est cet id qui est stocké dans `resultRef` puis rejoué.

    Paramètres :
    - `route` : identifiant stable de la commande (ex. `billing.invoice.create`),
      entré dans la portée ;
    - `result_model` : classe SQLAlchemy relue pour rejouer le résultat ;
    - `principal_arg` : nom de l'argument qui identifie le principal appelant.
    """

    def decorateur(fonction: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        signature = inspect.signature(fonction)

        @functools.wraps(fonction)
        async def enveloppe(db: AsyncSession, *args: Any, **kwargs: Any) -> Any:
            liaison = signature.bind(db, *args, **kwargs)
            liaison.apply_defaults()
            arguments = dict(liaison.arguments)
            principal = arguments[principal_arg]
            cle = arguments["idempotency_key"]
            portee = portee_idempotence(principal, route, cle)
            empreinte = empreinte_commande({
                nom: valeur for nom, valeur in arguments.items()
                if nom not in _ARGUMENTS_HORS_EMPREINTE and nom != principal_arg
            })

            existant = await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.scopeKey == portee))
            if existant is not None:
                if existant.commandHash != empreinte or existant.status != STATUT_TERMINE:
                    raise billing_error(BillingErrorCode.DUPLICATE)
                return await db.get(result_model, uuid.UUID(existant.resultRef))

            # Réservation committée avant l'exécution : deux demandes simultanées de
            # même portée ne peuvent pas toutes deux passer (contrainte unique sur scopeKey).
            db.add(IdempotencyRecord(
                scopeKey=portee, idempotencyKey=cle, commandHash=empreinte, status=STATUT_EN_ATTENTE,
            ))
            try:
                await db.commit()
            except IntegrityError as exc:
                await db.rollback()
                raise billing_error(BillingErrorCode.DUPLICATE) from exc

            try:
                resultat = await fonction(db, *args, **kwargs)
            except Exception:
                # Une commande refusée ne consomme pas sa clé : la réservation est retirée.
                await db.rollback()
                await db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.scopeKey == portee))
                await db.commit()
                raise

            registre = await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.scopeKey == portee))
            registre.status = STATUT_TERMINE
            registre.resultRef = str(resultat.id)
            await db.commit()
            return resultat

        return enveloppe

    return decorateur


async def write_versioned(
    db: AsyncSession, model: type, object_id: uuid.UUID, *, expected_version: int, changes: dict[str, Any],
) -> Any:
    """Applique `changes` seulement si la version courante vaut `expected_version`.

    Réussite : les champs sont écrits, `version` passe à `expected_version + 1`,
    l'objet relu est renvoyé. Échec (version obsolète ou objet absent) :
    `VERSION_CONFLICT`, transaction annulée, aucune ligne modifiée. Le contrôle et
    l'écriture sont une seule instruction UPDATE, donc sans fenêtre de course.
    """
    resultat = await db.execute(
        update(model)
        .where(model.id == object_id, model.version == expected_version)
        .values(**changes, version=model.version + 1)
        .execution_options(synchronize_session=False)
    )
    if resultat.rowcount != 1:
        await db.rollback()
        raise billing_error(BillingErrorCode.VERSION_CONFLICT)
    await db.commit()
    objet = await db.get(model, object_id)
    await db.refresh(objet)
    return objet
