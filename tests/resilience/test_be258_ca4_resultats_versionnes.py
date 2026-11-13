"""BE-258 CA-4 : le résultat de chaque scénario de résilience est versionné (test de présence).

Tests écrits d'après la définition `### BE-258` de implementation-backend/tasks-exploitation-architecture.md,
avant le code.

Chaque scénario (BE258-CA1 à BE258-CA4) a un fichier `tests/resilience/resultats/<scénario>.json` versionné
dans git : identifiant, version du scénario (entier >= 1), fichier de test, résultat (`vert`) et liste des
fonctions de test qui le couvrent. Ce test vérifie la présence du fichier, sa forme, et que chaque fonction
citée existe dans le fichier de test désigné.
"""

import ast
import json
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent
DOSSIER_RESULTATS = RACINE / "resultats"
SCENARIOS = {
    "BE258-CA1": "test_be258_ca1_migration_interrompue.py",
    "BE258-CA2": "test_be258_ca2_replay_sans_doublon.py",
    "BE258-CA3": "test_be258_ca3_panne_dependance.py",
    "BE258-CA4": "test_be258_ca4_resultats_versionnes.py",
}


def _fonctions_de(fichier: Path) -> set[str]:
    """Noms des fonctions de test définies au niveau du module (lecture de l'arbre, sans import)."""
    arbre = ast.parse(fichier.read_text(encoding="utf-8"))
    return {
        noeud.name
        for noeud in arbre.body
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)) and noeud.name.startswith("test_")
    }


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_be258_ca4_resultat_de_scenario_versionne(scenario):
    """CA-4 : le résultat du scénario existe, est versionné, et renvoie à des tests existants."""
    chemin = DOSSIER_RESULTATS / f"{scenario}.json"
    assert chemin.is_file(), f"résultat versionné absent : {chemin}"

    resultat = json.loads(chemin.read_text(encoding="utf-8"))
    assert resultat["scenario"] == scenario
    assert isinstance(resultat["version"], int) and resultat["version"] >= 1
    assert resultat["fichier_test"] == SCENARIOS[scenario]
    assert resultat["resultat"] == "vert"
    assert resultat["tests"], "le résultat doit citer au moins une fonction de test"
    assert set(resultat["tests"]) <= _fonctions_de(RACINE / SCENARIOS[scenario])
