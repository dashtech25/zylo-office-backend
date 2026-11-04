"""Service de gestion des clés de chiffrement (BE-231).

Trois opérations, réservées à l'exploitation (même liste que le registre des
secrets, `assert_operator_user`, 403 `operator_access_denied` sinon) :
- `charger_anneau` : reconstruit l'anneau en mémoire depuis la base (clés
  enveloppées déchiffrées avec la clé maître). Lecture, sans droit requis.
- `rotate_key` : crée la version N+1 (ou la version 1 si aucune n'existe),
  passe l'ancienne courante à `retiree`. Les valeurs déjà chiffrées restent
  lisibles (CA-1).
- `revoquer_cle` : passe une version non courante à `revoquee` et efface son
  matériel. Refus 409 pour la version courante, 404 si la version n'existe pas.

Approbation : la définition exige une approbation (QE-EXP-15). Le contrôle
d'approbation n'existe pas encore sur cette branche (BE-229 absent) : il est
consigné comme QE et l'accès repose pour l'instant sur la liste opérateur seule.

Les fonctions ne commitent pas : l'appelant gère la transaction.
"""

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import AnneauDeCles, desenvelopper_cle, envelopper_cle, generer_cle_donnee
from app.core.errors import AppError
from app.operator.encryption_models import EncryptionKey
from app.operator.permissions import assert_operator_user


async def charger_anneau(db: AsyncSession) -> AnneauDeCles:
    """Anneau des versions non révoquées (matériel présent), clés de données déchiffrées.

    La version marquée `active` devient la version courante de l'anneau."""
    lignes = (
        await db.execute(
            select(EncryptionKey)
            .where(EncryptionKey.wrappedKey.is_not(None))
            .order_by(EncryptionKey.version)
        )
    ).scalars().all()
    anneau = AnneauDeCles()
    for ligne in lignes:
        anneau.ajouter(
            ligne.version,
            desenvelopper_cle(ligne.wrappedKey),
            courante=ligne.statut == "active",
        )
    return anneau


async def rotate_key(db: AsyncSession, utilisateur: Any, maintenant: dt.datetime) -> int:
    """Crée la version suivante, la rend courante et retire l'ancienne. Retourne son numéro.

    Contrôle de droit en premier : sans droit, aucune ligne n'est touchée (403)."""
    assert_operator_user(utilisateur.id)
    courante = (
        await db.execute(select(EncryptionKey).where(EncryptionKey.statut == "active"))
    ).scalar_one_or_none()
    if courante is not None:
        courante.statut = "retiree"
        courante.retiredAt = maintenant
    derniere = await db.scalar(select(func.max(EncryptionKey.version)))
    nouvelle_version = (derniere or 0) + 1
    db.add(
        EncryptionKey(
            version=nouvelle_version,
            statut="active",
            wrappedKey=envelopper_cle(generer_cle_donnee()),
            createdAt=maintenant,
        )
    )
    await db.flush()
    return nouvelle_version


async def revoquer_cle(
    db: AsyncSession,
    utilisateur: Any,
    version: int,
    maintenant: dt.datetime,
    anneau: AnneauDeCles,
) -> None:
    """Révoque `version` : matériel effacé en base et retiré de `anneau`.

    Idempotent sur une version déjà révoquée. Les valeurs encore chiffrées avec
    cette version deviennent illisibles : elles doivent être ré-chiffrées avant."""
    assert_operator_user(utilisateur.id)
    ligne = (
        await db.execute(select(EncryptionKey).where(EncryptionKey.version == version))
    ).scalar_one_or_none()
    if ligne is None:
        raise AppError(code="cle_inconnue", message="Version de clé introuvable.", status_code=404)
    if ligne.statut == "active":
        raise AppError(
            code="cle_courante_non_revocable",
            message="La version courante ne peut pas être révoquée : effectuer une rotation d'abord.",
            status_code=409,
        )
    if ligne.statut == "revoquee":
        return
    anneau.revoquer(version)
    ligne.statut = "revoquee"
    ligne.wrappedKey = None
    ligne.revokedAt = maintenant
    await db.flush()
