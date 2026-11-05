"""Déclaration et synchronisation du registre des réglages (BE-237, CA-1).

Module de référence des réglages de la plateforme. Chaque réglage est déclaré par un
`ReglageDeclare` ; la déclaration refuse, à la construction, un propriétaire vide, une
portée hors `PORTEES_REGLAGE` ou un effet vide. `synchroniser_registre` pousse les
déclarations en base au démarrage : un doublon de clé dans la liste est refusé avant
toute écriture.

Liste des réglages déclarés : aucune à ce stade. Les réglages métier arrivent avec leurs
issues ; leur valeur par défaut reste NON DÉFINIE tant que la définition ne la donne pas.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.settings.models import PORTEES_REGLAGE, SettingsRegistry


@dataclass(frozen=True)
class ReglageDeclare:
    """Déclaration d'un réglage. Toute incohérence lève `ValueError` dès la construction.

    - `key` : identifiant stable, jamais réutilisé ;
    - `owner` : entité qui porte le réglage (texte non vide) ;
    - `scope` : portée parmi `PORTEES_REGLAGE` ;
    - `secret` : une valeur secrète n'est jamais renvoyée ni journalisée en clair ;
    - `effect` : effet non vide (la liste des effets est NON DÉFINIE) ;
    - `defaut` : valeur de repli, `None` si la définition ne la fixe pas ;
    - `date_effet` : date d'effet optionnelle.
    """

    key: str
    owner: str
    scope: str
    secret: bool
    effect: str
    defaut: Any = None
    date_effet: datetime | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.key.strip():
            raise ValueError("Réglage sans clé : déclaration refusée.")
        if not self.owner or not self.owner.strip():
            raise ValueError(f"Réglage « {self.key} » sans propriétaire : déclaration refusée.")
        if self.scope not in PORTEES_REGLAGE:
            raise ValueError(f"Réglage « {self.key} » : portée hors ensemble fermé : déclaration refusée.")
        if not self.effect or not self.effect.strip():
            raise ValueError(f"Réglage « {self.key} » sans effet : déclaration refusée.")


def verifier_declarations(declarations: Iterable[ReglageDeclare]) -> list[ReglageDeclare]:
    """Vérifie qu'aucune clé n'est déclarée deux fois ; renvoie la liste si elle est saine."""
    liste = list(declarations)
    vues: set[str] = set()
    for declaration in liste:
        if declaration.key in vues:
            raise ValueError(f"Réglage « {declaration.key} » déclaré deux fois : démarrage refusé.")
        vues.add(declaration.key)
    return liste


async def synchroniser_registre(db: AsyncSession, declarations: Iterable[ReglageDeclare]) -> None:
    """Insère ou met à jour les déclarations dans `settings_registry`, puis valide.

    Les déclarations invalides ont déjà été refusées à la construction ; la contrainte de
    table constitue une seconde barrière. L'appelant ne reçoit rien en retour.
    """
    for declaration in verifier_declarations(declarations):
        await db.merge(
            SettingsRegistry(
                key=declaration.key,
                scopeKind=declaration.scope,
                owner=declaration.owner,
                secret=declaration.secret,
                effect=declaration.effect,
                effectiveAt=declaration.date_effet,
                defaultValue=declaration.defaut,
            )
        )
    await db.commit()
