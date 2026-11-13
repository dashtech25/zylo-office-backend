"""BE-259 : passation de la porte back-end et preuves de passage.

Tests écrits d'après la définition `### BE-259` de implementation-backend/tasks-exploitation-architecture.md,
avant la rédaction du rapport et du PV (documents versionnés dans implementation-backend/ du dépôt).

- CA-1 : rapport et PV présents ; chaque critère CA des tâches BE-220 à BE-258 est référencé ; les fichiers
  de test cités dans le rapport existent.
- CA-2 : inventaire des seuils NON DÉFINI (QE-EXP-01 à QE-EXP-34) ; aucun n'apparaît comme approuvé.
- CA-3 : la porte reste BLOCKED tant que la décision du décideur humain manque.

Aucune base de données ni code applicatif n'est sollicité : les tests lisent seulement les documents.
"""

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "implementation-backend"
RAPPORT = DOSSIER / "BE-259-rapport-passation.md"
PV = DOSSIER / "BE-259-pv-porte.md"
DOCUMENTS = [RAPPORT, PV]

# Nombre de critères CA par tâche, relevé dans la définition (BE-220 à BE-258 : 171 critères).
NB_CA = {
    220: 5, 221: 4, 222: 4, 223: 5, 224: 4, 225: 4, 226: 5, 227: 5, 228: 4, 229: 6,
    230: 4, 231: 4, 232: 5, 233: 4, 234: 4, 235: 5, 236: 4, 237: 5, 238: 5, 239: 5,
    240: 5, 241: 4, 242: 4, 243: 5, 244: 5, 245: 5, 246: 5, 247: 4, 248: 4, 249: 4,
    250: 4, 251: 5, 252: 4, 253: 4, 254: 4, 255: 4, 256: 3, 257: 3, 258: 4,
}

QE_NON_DEFINI = [f"QE-EXP-{n:02d}" for n in range(1, 35)]


def _texte(fichier: Path) -> str:
    return fichier.read_text(encoding="utf-8") if fichier.is_file() else ""


def _ligne_tache(texte: str, tache: int) -> list[str]:
    return [ligne for ligne in texte.splitlines() if ligne.startswith(f"| BE-{tache} |")]


def _statut_attendu(decision: str) -> str:
    """La porte n'est ouverte que par une validation écrite du décideur humain (BE-259, droits)."""
    return "OUVERTE" if decision == "validée" else "BLOCKED"


# --- CA-1 : présence et référencement -------------------------------------------------

@pytest.mark.parametrize("fichier", DOCUMENTS, ids=lambda p: p.name)
def test_ca1_document_present(fichier):
    assert fichier.is_file(), f"document manquant : {fichier}"


@pytest.mark.parametrize("fichier", DOCUMENTS, ids=lambda p: p.name)
@pytest.mark.parametrize("tache", sorted(NB_CA))
def test_ca1_chaque_ca_de_la_tache_est_reference(fichier, tache):
    lignes = _ligne_tache(_texte(fichier), tache)
    assert len(lignes) == 1, f"BE-{tache} doit avoir exactement une ligne dans {fichier.name}"
    ligne = lignes[0]
    for k in range(1, NB_CA[tache] + 1):
        assert f"CA-{k}" in ligne, f"BE-{tache} CA-{k} absent de {fichier.name}"
    assert f"CA-{NB_CA[tache] + 1}" not in ligne, f"BE-{tache} : critère en trop dans {fichier.name}"


@pytest.mark.parametrize("fichier", DOCUMENTS, ids=lambda p: p.name)
def test_ca1_couverture_totale_des_taches(fichier):
    texte = _texte(fichier)
    for tache in range(220, 259):
        assert _ligne_tache(texte, tache), f"BE-{tache} absent de {fichier.name}"


def test_ca1_liens_vers_tests_existants():
    cibles = set(re.findall(r"tests/[\w/.-]+\.py", _texte(RAPPORT)))
    assert cibles, "le rapport ne cite aucun fichier de test"
    manquants = sorted(c for c in cibles if not (RACINE / c).is_file())
    assert manquants == [], f"liens vers des tests inexistants : {manquants}"


# --- CA-2 : inventaire des seuils NON DÉFINI -----------------------------------------

def test_ca2_inventaire_des_seuils_non_definis_complet():
    texte = _texte(PV)
    for identifiant in QE_NON_DEFINI:
        lignes = [ligne for ligne in texte.splitlines() if identifiant in ligne]
        assert lignes, f"{identifiant} absent du PV"
        assert any("NON DÉFINI" in ligne for ligne in lignes), f"{identifiant} non marqué NON DÉFINI"


def test_ca2_aucun_seuil_non_defini_n_est_approuve():
    for ligne in _texte(PV).splitlines():
        if "NON DÉFINI" in ligne:
            assert not re.search(r"approuv", ligne, re.IGNORECASE), f"seuil NON DÉFINI approuvé : {ligne}"


# --- CA-3 : statut de la porte --------------------------------------------------------

def test_ca3_statut_bloque_tant_que_la_decision_manque():
    texte = _texte(PV)
    statut = re.search(r"^Statut de la porte : (\S+)$", texte, re.MULTILINE)
    decision = re.search(r"^Décision du décideur humain : (.+)$", texte, re.MULTILINE)
    assert statut is not None, "ligne « Statut de la porte » absente du PV"
    assert decision is not None, "ligne « Décision du décideur humain » absente du PV"
    assert decision.group(1).strip() == "absente"
    assert statut.group(1) == _statut_attendu(decision.group(1).strip()) == "BLOCKED"


@pytest.mark.parametrize("decision", ["absente", "refusée"])
def test_ca3_statut_reste_bloque_sans_validation(decision):
    assert _statut_attendu(decision) == "BLOCKED"


def test_ca3_validation_finale_reservee_au_decideur():
    texte = _texte(PV)
    assert re.search(r"^Validation finale : décideur humain", texte, re.MULTILINE), \
        "la validation finale doit être attribuée au décideur humain"
