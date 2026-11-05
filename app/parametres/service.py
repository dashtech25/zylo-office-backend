"""Accès minimal aux valeurs de paramètres (BE-154).

Ce module ne porte que ce que BE-154 exige au niveau du modèle : écrire une version
avec conflit de version traduit en erreur métier, et lire la dernière version d'une
portée en la filtrant strictement sur son identifiant de portée (isolation tenant,
CA-4). La validation des valeurs (BE-155), la résolution d'héritage (BE-156) et
l'application atomique (BE-157) sont hors périmètre.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.parametres.models import SettingValue

# Nom de la contrainte d'unicité par version (voir SettingValue). Sert à distinguer
# un conflit de version d'une autre violation (NOT NULL, CHECK, clé étrangère).
_CONTRAINTE_VERSION = "uq_setting_value_definitionKey_scopeKind_scopeId_version"


async def ecrire_version(
    db: AsyncSession,
    definition_key: str,
    scope_kind: str,
    scope_id: uuid.UUID,
    version: int,
    value: object,
    created_by: uuid.UUID,
    reason: str,
    applied: bool = False,
) -> SettingValue:
    """Écrit une version de valeur et la valide immédiatement (commit).

    Une écriture qui réutilise une version déjà prise pour la même clé et la même
    portée lève `AppError` code `VERSION_CONFLICT`, statut 409 : c'est la contrainte
    d'unicité de la base qui arbitre, même en cas d'écritures concurrentes. Toute
    autre violation d'intégrité est relancée telle quelle : elle n'est pas un conflit
    de version et ne doit pas être présentée comme telle.
    """
    ligne = SettingValue(
        definitionKey=definition_key,
        scopeKind=scope_kind,
        scopeId=scope_id,
        version=version,
        value=value,
        applied=applied,
        createdBy=created_by,
        reason=reason,
    )
    db.add(ligne)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _CONTRAINTE_VERSION in str(exc.orig):
            raise AppError(
                "VERSION_CONFLICT",
                "Une autre écriture a déjà pris cette version de paramètre.",
                status_code=409,
            ) from exc
        raise
    await db.refresh(ligne)
    return ligne


async def lire_valeur_courante(
    db: AsyncSession, definition_key: str, scope_kind: str, scope_id: uuid.UUID
) -> SettingValue | None:
    """Renvoie la version la plus récente d'une valeur pour une portée exacte, ou None.

    La requête filtre sur `scopeId` : une valeur écrite pour une organisation n'est
    jamais renvoyée pour une autre (CA-4). Le choix de la version appliquée revient à
    BE-157 ; ici « courante » signifie « dernière écrite ».
    """
    resultat = await db.execute(
        select(SettingValue)
        .where(
            SettingValue.definitionKey == definition_key,
            SettingValue.scopeKind == scope_kind,
            SettingValue.scopeId == scope_id,
        )
        .order_by(SettingValue.version.desc())
        .limit(1)
    )
    return resultat.scalar_one_or_none()
