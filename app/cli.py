"""Commandes d'exploitation explicites (T-028), hors du démarrage du conteneur.

Usage (dans le conteneur, depuis /app) :

    python -m app.cli verifier-revision     # lecture seule ; code 1 si le schéma n'est pas à la tête
    python -m app.cli migrer --dry-run      # liste ce qui serait appliqué, sans rien modifier
    python -m app.cli migrer                # applique `alembic upgrade head` (garde destructive incluse)
    python -m app.cli migrer --confirmer-destructives --sauvegarde <fichier>
    python -m app.cli seed                  # permissions et modules connus (idempotent)
    python -m app.cli backfill              # répare le rôle owner (idempotent, owner seulement)

Intention :
- aucune commande ne tourne au démarrage de l'application ;
- `migrer` est la seule commande qui modifie le schéma ;
- `seed` et `backfill` ne touchent jamais les rôles autres que `owner` (le rôle
  `manager` et les rôles personnalisés ne sont pas élargis automatiquement) ;
- rejouer une commande ne change rien au second passage (idempotence).

Ce module est un point de composition (comme app/main.py) : il peut importer les
seeds et backfills des domaines, ce que app/core ne fait pas.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from alembic import command

from app.core.database import AsyncSessionLocal, engine
from app.core.migrations import (
    MigrationError,
    config_alembic,
    garde_destructive,
    lit_etat_base,
    revisions_attendues,
    revisions_en_attente,
    verifie_revision_a_jour,
)
from app.identity.service import backfill_owner_default_permissions
from app.modules_registry.service import backfill_active_module_permissions_for_owners
from app.modules_registry.seed import seed_known_modules
from app.rbac.seed import seed_known_permissions as seed_rbac_permissions
from app.identity.seed import seed_known_permissions as seed_identity_permissions
from app.audit.seed import seed_known_permissions as seed_audit_permissions
from app.modules.zylo_liquid.seed import seed_known_permissions as seed_zylo_liquid_permissions
from app.modules.zylo_tanker.seed import seed_known_permissions as seed_zylo_tanker_permissions

CODE_REFUS = 2


async def execute_seeds() -> None:
    """Ordre identique à l'ancien on_startup : modules d'abord, puis permissions.
    Idempotent : chaque seed ne crée que ce qui manque."""
    await seed_known_modules()
    await seed_rbac_permissions()
    await seed_identity_permissions()
    await seed_audit_permissions()
    await seed_zylo_liquid_permissions()
    await seed_zylo_tanker_permissions()


async def execute_backfills() -> dict[str, int]:
    """Répare les organisations créées avant l'ajout de permissions au rôle owner.

    Intention de sécurité : ces deux fonctions ne lisent et n'écrivent que le
    rôle `owner` (voir identity/service.py et modules_registry/service.py). Elles
    n'accordent rien au rôle `manager`, aux rôles personnalisés ni aux grants
    individuels. Relancer ne change rien une fois les organisations à jour."""
    async with AsyncSessionLocal() as db:
        socle = await backfill_owner_default_permissions(db)
    async with AsyncSessionLocal() as db:
        modules = await backfill_active_module_permissions_for_owners(db)
    return {"permissionsOwnerSocleAjoutees": socle, "permissionsOwnerModulesAjoutees": modules}


def _affiche(donnees: dict) -> None:
    print(json.dumps(donnees, ensure_ascii=False, indent=2))


def _lance(coroutine):
    """Exécute une commande dans sa propre boucle, avec un pool de connexions neuf.

    Intention : le moteur est un singleton ; ses connexions poolées sont liées à la
    boucle qui les a ouvertes. Vider le pool avant et après chaque commande évite
    de réutiliser une connexion d'une autre boucle (cas des tests, ou d'un
    appelant qui enchaîne plusieurs commandes dans le même processus)."""
    async def enveloppe() -> int:
        await engine.dispose()
        try:
            return await coroutine
        finally:
            await engine.dispose()

    return asyncio.run(enveloppe())


async def _commande_verifier() -> int:
    try:
        await verifie_revision_a_jour()
    except MigrationError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    _affiche({"schemaAJour": True, "revision": sorted(revisions_attendues())})
    return 0


async def _commande_seed() -> int:
    await execute_seeds()
    _affiche({"seeds": "appliques"})
    return 0


async def _commande_backfill() -> int:
    _affiche({"backfill": await execute_backfills()})
    return 0


def _commande_migrer(args: argparse.Namespace) -> int:
    # Lecture de l'état avant toute écriture : la garde décide sur cet état.
    courantes, base_vide = _lance(lit_etat_base())
    try:
        en_attente = revisions_en_attente(courantes)
        destructives = garde_destructive(en_attente, base_vide, args.confirmer_destructives, args.sauvegarde)
    except MigrationError as exc:
        print(f"REFUS : {exc}", file=sys.stderr)
        return CODE_REFUS

    rapport = {
        "revisionsCourantes": sorted(courantes),
        "revisionsEnAttente": en_attente,
        "destructivesEnAttente": destructives,
        "baseVide": base_vide,
        "dryRun": args.dry_run,
    }
    if args.dry_run or not en_attente:
        _affiche({**rapport, "action": "rien a appliquer" if not en_attente else "aucune ecriture (dry-run)"})
        return 0

    # Alembic ouvre son propre moteur (alembic/env.py) : pas de boucle asyncio active ici.
    command.upgrade(config_alembic(), "head")
    _affiche({**rapport, "action": "applique", "revisionFinale": sorted(revisions_attendues())})
    return 0


def construit_parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(prog="python -m app.cli", description="Commandes d'exploitation Zylo Office.")
    sous = parseur.add_subparsers(dest="commande", required=True)

    sous.add_parser("verifier-revision", help="Vérifie que le schéma est à la tête (lecture seule).")

    migrer = sous.add_parser("migrer", help="Applique les migrations Alembic jusqu'à la tête.")
    migrer.add_argument("--dry-run", action="store_true", help="Affiche ce qui serait appliqué, sans écrire.")
    migrer.add_argument(
        "--confirmer-destructives",
        action="store_true",
        help="Confirme l'application de migrations destructives (exige --sauvegarde).",
    )
    migrer.add_argument(
        "--sauvegarde",
        metavar="FICHIER",
        help="Fichier de sauvegarde vérifiée, créé AVANT la migration (docs/operations/migration.md).",
    )

    sous.add_parser("seed", help="Enregistre les modules et permissions connus (idempotent).")
    sous.add_parser("backfill", help="Répare les permissions du rôle owner (idempotent).")
    return parseur


def main(argv: list[str] | None = None) -> int:
    args = construit_parseur().parse_args(argv)
    if args.commande == "migrer":
        return _commande_migrer(args)
    if args.commande == "verifier-revision":
        return _lance(_commande_verifier())
    if args.commande == "seed":
        return _lance(_commande_seed())
    if args.commande == "backfill":
        return _lance(_commande_backfill())
    raise AssertionError(f"commande non gérée : {args.commande}")


if __name__ == "__main__":
    sys.exit(main())
