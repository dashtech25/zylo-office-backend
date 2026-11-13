"""Modification et lecture des réglages avec historique (BE-237).

Règles, dans l'ordre d'évaluation :
1. Isolation de portée (404 TENANT_MISMATCH) : un tenant ne vise jamais la portée
   plateforme ni le réglage d'une autre organisation. Le refus est un 404, pour ne pas
   révéler l'existence d'un autre tenant.
2. Permission (403 PERMISSION_DENIED) : `settings.setting.update` est exigée sur
   l'organisation de l'acteur. Sans organisation (portée plateforme sans opérateur), le
   refus est aussi 403 : aucun chemin d'écriture plateforme n'est ouvert ici (QE-BE237-02).
3. Validité (422 SCHEMA_INVALID) : réglage déclaré, portée identique à la déclaration,
   motif non vide.

Une écriture réussie ajoute une ligne `settings_history` (ancienne valeur, nouvelle
valeur, acteur, motif). La valeur courante d'une portée est la dernière ligne de
l'historique de cette portée, ou le défaut de la déclaration à défaut. Pour un réglage
secret, la valeur écrite et l'ancienne valeur sont remplacées par `MASQUE_SECRET`.

La fonction commit elle-même : la modification et son entrée d'historique sont persistées
ensemble ou pas du tout (même motif que `app.parametres.service.ecrire_version`).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.rbac.service import user_has_permission
from app.settings.models import SettingsHistory, SettingsRegistry

PERMISSION_MODIFIER_REGLAGE = "settings.setting.update"
MASQUE_SECRET = "********"


async def _declaration(db: AsyncSession, cle: str) -> SettingsRegistry:
    declaration = await db.get(SettingsRegistry, cle)
    if declaration is None:
        raise AppError("SCHEMA_INVALID", "Réglage inconnu.", status_code=422)
    return declaration


async def _derniere_entree(db: AsyncSession, cle: str, portee: str, scope_id: uuid.UUID | None) -> SettingsHistory | None:
    """Dernière modification de la portée donnée, ou None si le réglage n'a jamais été écrit."""
    requete = select(SettingsHistory).where(
        SettingsHistory.settingKey == cle,
        SettingsHistory.scopeKind == portee,
        SettingsHistory.scopeId.is_(None) if scope_id is None else SettingsHistory.scopeId == scope_id,
    ).order_by(SettingsHistory.createdAt.desc()).limit(1)
    return (await db.execute(requete)).scalars().first()


async def modifier_reglage(
    db: AsyncSession,
    *,
    acteur_id: uuid.UUID,
    organisation_id: uuid.UUID | None,
    cle: str,
    portee: str,
    scope_id: uuid.UUID | None,
    valeur: object,
    motif: str,
) -> SettingsHistory:
    """Applique une nouvelle valeur à un réglage et ajoute son entrée d'historique.

    `organisation_id` est l'organisation de l'acteur (None hors contexte tenant). Voir la
    règle d'ordre dans le docstring du module. Renvoie l'entrée d'historique persistée.
    """
    # 1. Isolation de portée.
    if portee == "platform" and organisation_id is not None:
        raise AppError("TENANT_MISMATCH", "Réglage introuvable pour cette organisation.", status_code=404)
    if portee == "tenant" and (organisation_id is None or scope_id != organisation_id):
        raise AppError("TENANT_MISMATCH", "Réglage introuvable pour cette organisation.", status_code=404)

    # 2. Permission.
    if organisation_id is None or not await user_has_permission(db, acteur_id, organisation_id, PERMISSION_MODIFIER_REGLAGE):
        raise AppError("PERMISSION_DENIED", "Droit insuffisant pour modifier ce réglage.", status_code=403)

    # 3. Validité.
    declaration = await _declaration(db, cle)
    if declaration.scopeKind != portee:
        raise AppError("SCHEMA_INVALID", "Portée incompatible avec la déclaration du réglage.", status_code=422)
    if not motif or not motif.strip():
        raise AppError("SCHEMA_INVALID", "Le motif de modification est obligatoire.", status_code=422)

    precedente = await _derniere_entree(db, cle, portee, scope_id)
    ancienne = precedente.newValue if precedente is not None else declaration.defaultValue
    nouvelle = valeur
    if declaration.secret:
        nouvelle = MASQUE_SECRET
        ancienne = MASQUE_SECRET if ancienne is not None else None

    entree = SettingsHistory(
        settingKey=cle,
        scopeKind=portee,
        scopeId=scope_id,
        oldValue=ancienne,
        newValue=nouvelle,
        actorId=acteur_id,
        reason=motif.strip(),
    )
    db.add(entree)
    # Commit ici : la modification et son entrée d'historique forment une seule unité.
    # Un appelant qui doit grouper d'autres écritures passera par une transaction englobante.
    await db.commit()
    return entree


async def lire_reglage(db: AsyncSession, *, cle: str, portee: str, scope_id: uuid.UUID | None) -> object:
    """Valeur courante d'un réglage pour une portée, masquée si le réglage est secret (CA-4).

    Renvoie la dernière valeur écrite de la portée, sinon le défaut de la déclaration.
    Un secret renvoie `MASQUE_SECRET` dès qu'une valeur existe, jamais la valeur en clair.
    """
    declaration = await _declaration(db, cle)
    precedente = await _derniere_entree(db, cle, portee, scope_id)
    valeur = precedente.newValue if precedente is not None else declaration.defaultValue
    if declaration.secret and valeur is not None:
        return MASQUE_SECRET
    return valeur
