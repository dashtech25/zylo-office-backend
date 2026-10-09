#!/usr/bin/env python3
"""Génère docs/architecture/securite/matrice-autorisation.md depuis les routes de l'application (T-023).

Intention : la matrice permission -> routes est lue sur le code, jamais saisie
à la main. Le test tests/test_route_inventory.py::test_matrice_documentee_a_jour
échoue si le fichier versionné n'est pas à jour : relancer ce script.

Usage (depuis la racine du dépôt backend, venv du dépôt) :
    .venv/bin/python scripts/dev/generer_matrice_autorisation.py
"""

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SORTIE = RACINE / "docs" / "architecture" / "securite" / "matrice-autorisation.md"

# L'import de l'application exige une configuration explicite (aucun secret de repli).
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET", "generation-matrice-" + "0123456789abcdef" * 2)
os.environ.setdefault("STORAGE_SIGNED_URL_SECRET", "generation-matrice-" + "fedcba9876543210" * 2)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://generation@/inexistante")

sys.path.insert(0, str(RACINE))

from app.main import app  # noqa: E402
from tests.route_inventory import inventaire, matrice_markdown  # noqa: E402


def main() -> None:
    SORTIE.write_text(matrice_markdown(inventaire(app)), encoding="utf-8")
    print(f"Matrice écrite : {SORTIE}")


if __name__ == "__main__":
    main()
