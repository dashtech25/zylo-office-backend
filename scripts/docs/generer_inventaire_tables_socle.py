#!/usr/bin/env python3
"""Génère ou contrôle la documentation canonique des tables du socle."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path


RACINE_BACKEND = Path(__file__).resolve().parents[2]
FICHIER_CIBLE = RACINE_BACKEND / "docs/architecture/inventaire-tables-socle.md"


def _charger_modeles() -> None:
    """Enregistre dans Base.metadata le périmètre complet de l'inventaire.

    L'import de app.main enregistre les modèles montés par l'API ; les modules
    listés dans MODULES_ORM_SOCLE_HORS_APP y ajoutent les tables du socle que
    l'application ne charge pas. Doit tourner dans un processus neuf pour être
    reproductible.
    """
    sys.path.insert(0, str(RACINE_BACKEND))
    import app.main  # noqa: F401
    from app.core.table_inventory import MODULES_ORM_SOCLE_HORS_APP

    for nom_module in MODULES_ORM_SOCLE_HORS_APP:
        importlib.import_module(nom_module)


def main() -> int:
    """Écrit le document canonique ou échoue si le document est désynchronisé."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="vérifie que le document versionné correspond au rendu courant",
    )
    parser.add_argument(
        "--noms-tables",
        action="store_true",
        help="affiche en JSON les noms des tables du périmètre (utilisé par les tests)",
    )
    arguments = parser.parse_args()

    _charger_modeles()

    from app.core.table_inventory import noms_tables_socle, render_inventory_markdown

    if arguments.noms_tables:
        print(json.dumps(noms_tables_socle()))
        return 0

    rendu = render_inventory_markdown()
    if arguments.check:
        if not FICHIER_CIBLE.is_file():
            print(f"Document absent : {FICHIER_CIBLE.relative_to(RACINE_BACKEND)}", file=sys.stderr)
            return 1
        courant = FICHIER_CIBLE.read_text(encoding="utf-8")
        if courant != rendu:
            print(
                "Document désynchronisé : relancer sans --check pour le régénérer.",
                file=sys.stderr,
            )
            return 1
        print("Inventaire des tables du socle à jour.")
        return 0

    FICHIER_CIBLE.parent.mkdir(parents=True, exist_ok=True)
    FICHIER_CIBLE.write_text(rendu, encoding="utf-8")
    print(f"Document généré : {FICHIER_CIBLE.relative_to(RACINE_BACKEND)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

