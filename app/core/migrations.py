"""Migrations hors du démarrage du conteneur (T-028).

Intention : le démarrage de l'application ne modifie jamais le schéma. Les
migrations sont lancées explicitement, une fois par déploiement, par
`python -m app.cli migrer` (app/cli.py). Ce module porte la logique partagée :

- la lecture de la révision Alembic de la base (en lecture seule) ;
- le calcul des révisions en attente ;
- la garde des migrations destructives : une révision connue pour détruire des
  données n'est appliquée que sur confirmation explicite ET avec un fichier de
  sauvegarde existant. Cette garde ne sauvegarde rien elle-même : la sauvegarde
  est une étape opérateur documentée (docs/operations/migration.md).
- la vérification au démarrage : refus clair si la base n'est pas à la révision
  attendue, sans jamais migrer.

Ce module ne dépend d'aucun module métier (app/core ne doit pas importer
app/modules, voir CLAUDE.md).
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.database import engine

RACINE_BACKEND = Path(__file__).resolve().parents[2]
ALEMBIC_INI = RACINE_BACKEND / "alembic.ini"

# Révisions dont `upgrade()` détruit des données (colonne ou table supprimée,
# TRUNCATE). Liste maintenue à la main, contrôlée par un balayage AST dans
# tests/test_migrations_conteneur.py : toute nouvelle migration destructive doit
# être ajoutée ici, sinon le test échoue.
# Remarque : les `drop_table` de 1047562d0691, 00e30f42d09d et 0240c128e5de sont
# dans `downgrade()` (retour arrière manuel), pas dans `upgrade()` : elles ne
# sont pas appliquées par `migrer`.
REVISIONS_DESTRUCTIVES: dict[str, str] = {
    "139b3a1a96cb": "upgrade supprime des colonnes de livraison (delivery_tank_chosen_at_delivery)",
    "7ffb9473d45e": "upgrade fait TRUNCATE de zyloLiquidFuelProduct : ne jamais rejouer sur une base contenant des données",
    "82fd37bd908f": "upgrade supprime une colonne (tank_mm_alarm_thresholds)",
    "c4d5e6f7a8b9": "upgrade supprime des colonnes vestigiales des prix carburant",
}


class MigrationError(RuntimeError):
    """Refus explicite : message destiné à l'opérateur, sans secret."""


def config_alembic() -> Config:
    return Config(str(ALEMBIC_INI))


def script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(config_alembic())


def revisions_attendues() -> set[str]:
    """Têtes du dépôt de migrations : la base doit être exactement là."""
    return set(script_directory().get_heads())


def verifie_tete_unique(tetes: set[str] | None = None) -> str:
    """Retourne l'unique tête de la chaîne, ou lève MigrationError.

    Intention : deux têtes signifient deux branches de migrations non fusionnées.
    Alembic ne sait pas choisir laquelle appliquer : on refuse plutôt que de
    deviner. `tetes` permet de tester le contrôle sur une chaîne fictive ; sans
    argument, la chaîne du dépôt est lue.
    """
    lues = set(script_directory().get_heads()) if tetes is None else set(tetes)
    if len(lues) != 1:
        raise MigrationError(
            f"Chaîne de migrations à plusieurs têtes ({', '.join(sorted(lues)) or 'aucune'}). "
            "Fusionner les branches avec `alembic merge` avant toute migration."
        )
    return next(iter(lues))


def revisions_en_attente(courantes: set[str]) -> list[str]:
    """Révisions à appliquer pour atteindre la tête, dans l'ordre d'application.

    Intention : une base vide (aucune révision) a toutes les révisions en attente.
    Une révision courante inconnue du dépôt signifie une base plus récente que le
    code : refus, sans rien appliquer."""
    script = script_directory()
    deja_appliquees: set[str] = set()
    for revision in courantes:
        try:
            deja_appliquees.update(r.revision for r in script.iterate_revisions(revision, "base"))
        except Exception as exc:  # alembic lève CommandError/ResolutionError selon la version
            raise MigrationError(
                f"Révision de la base inconnue du dépôt ({revision}) : base plus récente que le code. "
                "Ne pas migrer ; vérifier la version déployée."
            ) from exc
    return [r.revision for r in script.walk_revisions("base", "heads") if r.revision not in deja_appliquees]


def garde_destructive(
    en_attente: list[str], base_vide: bool, confirmation: bool, sauvegarde: str | None
) -> list[str]:
    """Retourne les révisions destructives en attente, ou lève MigrationError.

    Intention : aucune migration destructive ne part sans (1) confirmation
    explicite (`--confirmer-destructives`) et (2) un fichier de sauvegarde
    existant et non vide, désigné par l'opérateur. Une base sans table (création
    depuis zéro) ne contient aucune donnée à perdre : la garde ne s'applique pas.
    """
    destructives = [r for r in en_attente if r in REVISIONS_DESTRUCTIVES]
    if not destructives or base_vide:
        return destructives
    if not confirmation:
        lignes = "\n".join(f"  - {r} : {REVISIONS_DESTRUCTIVES[r]}" for r in destructives)
        raise MigrationError(
            "Migrations destructives en attente, refusées sans confirmation explicite :\n"
            f"{lignes}\n"
            "Sauvegarder la base (docs/operations/migration.md), puis relancer avec "
            "--confirmer-destructives et --sauvegarde <fichier>."
        )
    if not sauvegarde:
        raise MigrationError("Migration destructive : --sauvegarde <fichier> est obligatoire.")
    fichier = Path(sauvegarde)
    if not fichier.is_file() or fichier.stat().st_size == 0:
        raise MigrationError(f"Sauvegarde introuvable ou vide : {sauvegarde}.")
    return destructives


async def lit_etat_base() -> tuple[set[str], bool]:
    """Révisions appliquées et indicateur « base vide » (aucune table publique
    hormis alembic_version). Lecture seule."""
    async with engine.connect() as connexion:
        tables = (
            await connexion.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        ).scalars().all()
        revisions: set[str] = set()
        if "alembic_version" in tables:
            revisions = set(
                (await connexion.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
            )
    base_vide = not [t for t in tables if t != "alembic_version"]
    return revisions, base_vide


async def verifie_revision_a_jour() -> None:
    """Appelé au démarrage : refuse de servir si le schéma n'est pas à la tête.

    Intention : l'application ne migre jamais elle-même. Un schéma en retard
    provoque un refus de démarrage avec le message de la commande à lancer."""
    revisions, _ = await lit_etat_base()
    attendues = revisions_attendues()
    if revisions != attendues:
        actuelles = ", ".join(sorted(revisions)) or "aucune"
        raise MigrationError(
            f"Schéma non à jour : base à [{actuelles}], attendu [{', '.join(sorted(attendues))}]. "
            "Lancer `python -m app.cli migrer` avant de démarrer l'application."
        )
