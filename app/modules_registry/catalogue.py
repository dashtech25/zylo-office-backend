"""Règles du catalogue de modules sur les versions (BE-040).

Ce module porte les deux invariants du catalogue, sans dépendre des routes :

- une version ne peut être publiée que si elle a un `digest` et une `provenance` (un paquet
  sans empreinte ni origine ne doit jamais devenir installable) ;
- une version publiée est immuable : son contenu (digest, provenance, licence, compatibilité,
  prérequis, numéro) ne se modifie plus. Pour changer le contenu, on publie une nouvelle version.

Les erreurs sont des `AppError` aux codes `MODULE_VERSION_INCOMPLETE` et
`MODULE_VERSION_IMMUTABLE`. Les fonctions ne valident que la version passée ; la transition
complète d'état (machine à états, journal) est de BE-041.
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules_registry.models import ModuleVersion

# Champs qui définissent le contenu d'une version. Une fois publiée, aucun ne change.
CHAMPS_IMMUABLES_APRES_PUBLICATION: frozenset[str] = frozenset(
    {"version", "digest", "provenance", "licence", "compatibility", "prerequisites"}
)


def verifier_publiable(version: ModuleVersion) -> None:
    """Lève `MODULE_VERSION_INCOMPLETE` si la version n'a pas de `digest` ni de `provenance`.

    Fonction pure : ne touche pas à la base, elle peut être appelée avant toute écriture.
    Une chaîne vide compte comme absente.
    """
    manquants = [nom for nom in ("digest", "provenance") if not getattr(version, nom)]
    if manquants:
        raise AppError(
            code="MODULE_VERSION_INCOMPLETE",
            message=f"Version non publiable : champ(s) manquant(s) {', '.join(manquants)}.",
            status_code=422,
        )


async def publier_version(db: AsyncSession, version: ModuleVersion) -> ModuleVersion:
    """Publie la version : vérifie `verifier_publiable`, puis renseigne `publishedAt`.

    Une version déjà publiée est renvoyée telle quelle (la publication est idempotente)."""
    if version.publishedAt is not None:
        return version
    verifier_publiable(version)
    version.publishedAt = datetime.now(timezone.utc)
    await db.flush()
    return version


async def modifier_version(db: AsyncSession, version: ModuleVersion, **champs) -> ModuleVersion:
    """Modifie les champs d'une version, sauf si elle est publiée et qu'un champ immuable est visé.

    Lève `MODULE_VERSION_IMMUTABLE` (409) dès qu'un champ de `CHAMPS_IMMUABLES_APRES_PUBLICATION`
    est demandé sur une version publiée. Aucun champ n'est modifié dans ce cas (tout ou rien).
    Les champs non immuables (ex. `stateVersion`) restent modifiables après publication."""
    if version.publishedAt is not None:
        interdits = sorted(set(champs) & CHAMPS_IMMUABLES_APRES_PUBLICATION)
        if interdits:
            raise AppError(
                code="MODULE_VERSION_IMMUTABLE",
                message=f"Version publiée, champ(s) immuable(s) : {', '.join(interdits)}.",
                status_code=409,
            )
    for nom, valeur in champs.items():
        setattr(version, nom, valeur)
    await db.flush()
    return version
