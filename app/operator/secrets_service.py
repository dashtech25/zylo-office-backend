"""Service du registre des secrets et contrôles liés (BE-230).

Trois opérations, chacune avec un contrat précis :
- `lire_registre` : lecture du registre, réservée à l'exploitation. Sans droit,
  AppError 403 `operator_access_denied` (même contrôle que l'interface de support,
  app/operator/permissions.py : une seule liste d'opérateurs).
- `enregistrer_rotation` : remplace la valeur dans le magasin puis date la rotation
  dans le registre. L'ancienne valeur devient inopérante (voir SecretStore).
  Le nom du secret est journalisé, jamais sa valeur.
- `controle_secrets_au_demarrage` : échec fermé. Un secret obligatoire expiré ou
  sans valeur lève ConfigurationSecretError, dont le message nomme les secrets mais
  jamais leurs valeurs.

Les fonctions ne commitent pas : l'appelant gère la transaction.
"""

import datetime as dt
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import ConfigurationSecretError
from app.core.errors import AppError
from app.core.secrets import SecretStore
from app.operator.permissions import assert_operator_user
from app.operator.secrets_models import SecretRegistry

logger = logging.getLogger(__name__)


async def lire_registre(db: AsyncSession, utilisateur: Any) -> list[SecretRegistry]:
    """Lignes du registre, triées par nom. Exige un opérateur (403 sinon)."""
    assert_operator_user(utilisateur.id)
    resultat = await db.execute(select(SecretRegistry).order_by(SecretRegistry.name))
    return list(resultat.scalars().all())


async def enregistrer_rotation(
    db: AsyncSession,
    store: SecretStore,
    nom: str,
    nouvelle_valeur: str,
    maintenant: dt.datetime,
) -> None:
    """Remplace la valeur de `nom` et date la rotation dans le registre.

    Le secret doit être inventorié : une rotation d'un nom inconnu du registre est
    refusée (404) avant toute modification du magasin, pour qu'aucun secret non
    inventorié n'entre en service sans trace."""
    ligne = (await db.execute(select(SecretRegistry).where(SecretRegistry.name == nom))).scalar_one_or_none()
    if ligne is None:
        raise AppError(code="secret_inconnu", message="Secret absent du registre.", status_code=404)
    store.rotate(nom, nouvelle_valeur)
    ligne.lastRotatedAt = maintenant
    await db.flush()
    logger.info("rotation de secret enregistrée", extra={"secret_name": nom})


async def controle_secrets_au_demarrage(db: AsyncSession, store: SecretStore, maintenant: dt.datetime) -> None:
    """Refuse le démarrage si un secret obligatoire est expiré ou sans valeur.

    Intention : un secret périmé ne doit jamais servir silencieusement. Le message
    cite les noms des secrets fautifs et jamais leurs valeurs."""
    resultat = await db.execute(select(SecretRegistry).where(SecretRegistry.required.is_(True)))
    fautifs: list[str] = []
    for ligne in resultat.scalars().all():
        if ligne.expiresAt is not None and ligne.expiresAt <= maintenant:
            fautifs.append(f"{ligne.name} (expiré)")
        if store.valeur_courante(ligne.name) is None:
            fautifs.append(f"{ligne.name} (absent)")
    if fautifs:
        raise ConfigurationSecretError(
            "Démarrage refusé : secrets obligatoires expirés ou absents : "
            + ", ".join(sorted(fautifs))
            + " (noms seuls, aucune valeur affichée)."
        )
