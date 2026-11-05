"""Catégories et règles de notification (BE-167).

Ce module porte les écritures de configuration des catégories et des règles
(`categorie_notification`, `regle_notification`). Il ne décide ni des destinataires
(BE-169) ni des préférences des utilisateurs (BE-168).

Décisions portées ici :
- CA-1 : une catégorie sans audience est refusée avant écriture (`422`
  SCHEMA_INVALID) ; la base refuse aussi une audience vide (CHECK), second rempart.
- CA-2 : une règle ne peut référencer qu'un type d'événement du catalogue. Le
  catalogue (BE-176) n'existe pas encore : `TYPES_EVENEMENT_CONNUS` en est le point
  d'injection. Il est vide par défaut, donc fermé : aucune règle ne passe tant que
  le catalogue n'est pas branché (refus `422` SCHEMA_INVALID).
- CA-3 : configurer une règle est réservé à l'autorité plateforme
  (`rbac.role_assignments.has_platform_authority`). Un administrateur de tenant
  reçoit `403` PERMISSION_DENIED. La règle exacte des droits reste QE-PAR-03 ; le
  refus fermé appliqué ici est la seule décision retenue en attendant.
- CA-4 : aucun canal n'est présumé. Un canal absent se lit `NON DÉFINI`
  (`canal_defaut_categorie`), jamais une valeur inventée.

Module documenté dans `app/notifications/categories.md`.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.notifications.models import CategorieNotification, RegleNotification
from app.rbac.role_assignments import has_platform_authority

# Libellé renvoyé quand la catégorie n'a pas de canal défini (CA-4). Ce n'est pas
# une valeur de canal : l'appelant doit le traiter comme une absence.
NON_DEFINI = "NON DÉFINI"

# Types d'événement connus du catalogue (CA-2). Vide tant que BE-176 n'est pas livré :
# le refus est alors le comportement attendu (fermé). Les tests injectent un
# ensemble via monkeypatch ; le catalogue réel le remplacera.
TYPES_EVENEMENT_CONNUS: frozenset[str] = frozenset()


def _exiger_plateforme(est_plateforme: bool) -> None:
    """Refuse (403 PERMISSION_DENIED) si l'acteur n'a pas l'autorité plateforme."""
    if not est_plateforme:
        raise AppError(
            "PERMISSION_DENIED",
            "La configuration des règles de notification est réservée à l'administration plateforme.",
            status_code=403,
        )


async def creer_categorie(
    db: AsyncSession,
    *,
    code: str,
    libelle: str,
    audience_regle: str,
    canal_defaut: str | None = None,
) -> CategorieNotification:
    """Déclare une catégorie active avec son audience (CA-1, CA-4).

    `audience_regle` vide ou blanc lève `422` SCHEMA_INVALID avant toute écriture.
    `canal_defaut` reste NULL si l'appelant n'en fournit pas : aucun canal n'est
    présumé à la création.
    """
    if not audience_regle or not audience_regle.strip():
        raise AppError("SCHEMA_INVALID", "Une catégorie de notification doit avoir une audience.", status_code=422)
    categorie = CategorieNotification(
        code=code,
        libelle=libelle,
        audienceRegle=audience_regle,
        canalDefaut=canal_defaut,
        actif=True,
    )
    db.add(categorie)
    await db.commit()
    await db.refresh(categorie)
    return categorie


async def canal_defaut_categorie(db: AsyncSession, code: str) -> str:
    """Renvoie le canal par défaut de la catégorie, ou `NON DÉFINI` s'il est absent (CA-4).

    Une catégorie inconnue lève `404` NOTIFICATION_CATEGORY_NOT_FOUND : son absence
    n'est pas un canal absent.
    """
    categorie = await db.get(CategorieNotification, code)
    if categorie is None:
        raise AppError("NOTIFICATION_CATEGORY_NOT_FOUND", "Catégorie de notification introuvable.", status_code=404)
    return categorie.canalDefaut if categorie.canalDefaut is not None else NON_DEFINI


async def creer_regle(
    db: AsyncSession,
    *,
    acteur_id: uuid.UUID,
    evenement_type: str,
    categorie_code: str,
    audience: str,
) -> RegleNotification:
    """Crée une règle type d'événement vers catégorie, réservée à l'autorité plateforme.

    Ordre de décision : droits (403) puis type d'événement au catalogue (422 CA-2),
    puis existence de la catégorie (404). Rien n'est écrit en cas de refus.
    """
    _exiger_plateforme(await has_platform_authority(db, acteur_id))
    if evenement_type not in TYPES_EVENEMENT_CONNUS:
        raise AppError(
            "SCHEMA_INVALID",
            "Le type d'événement n'existe pas dans le catalogue.",
            status_code=422,
            field_errors={"evenementType": ["type inconnu du catalogue"]},
        )
    if await db.get(CategorieNotification, categorie_code) is None:
        raise AppError("NOTIFICATION_CATEGORY_NOT_FOUND", "Catégorie de notification introuvable.", status_code=404)
    regle = RegleNotification(evenementType=evenement_type, categorieCode=categorie_code, audience=audience)
    db.add(regle)
    await db.commit()
    await db.refresh(regle)
    return regle


async def modifier_regle_audience(
    db: AsyncSession,
    *,
    acteur_id: uuid.UUID,
    regle_id: uuid.UUID,
    audience: str,
) -> RegleNotification:
    """Change l'audience d'une règle, réservé à l'autorité plateforme (CA-3).

    Un administrateur de tenant reçoit `403` PERMISSION_DENIED et la règle reste
    inchangée. Une règle inconnue lève `404`.
    """
    _exiger_plateforme(await has_platform_authority(db, acteur_id))
    regle = await db.get(RegleNotification, regle_id)
    if regle is None:
        raise AppError("NOTIFICATION_RULE_NOT_FOUND", "Règle de notification introuvable.", status_code=404)
    regle.audience = audience
    await db.commit()
    await db.refresh(regle)
    return regle

