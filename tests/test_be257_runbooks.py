"""BE-257 : runbooks et preuves d'exploitation.

Intention : prouver par des tests que
- chaque alerte d'exploitation a un runbook existant dans docs/exploitation/alertes.md,
  dont la section porte le propriétaire, la sévérité, l'escalade et la première action,
  cohérents avec la route de routage BE-241 (CA-1) ;
- chaque runbook de restauration référence un exercice daté et une preuve existante (CA-2) ;
- un runbook sans propriétaire est refusé, et chaque fichier de docs/exploitation/
  déclare son propriétaire (CA-3).

Les tests lisent les fichiers de docs/exploitation/ et utilisent les contrôles de
app/operator/runbooks.py. Les imports sont faits à l'intérieur de chaque test : chaque
test échoue donc pour sa seule raison tant que le code n'existe pas.
"""

import re
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DOSSIER_RUNBOOKS = RACINE / "docs" / "exploitation"
ALERTES = DOSSIER_RUNBOOKS / "alertes.md"
RESTAURATION = DOSSIER_RUNBOOKS / "restauration.md"


def test_chaque_alerte_d_exploitation_a_un_runbook_existant():
    """CA-1 : chaque signal routé pointe vers un fichier existant et une section du même nom."""
    from app.operator.alertes_registre import ROUTES_PROVISOIRES, SIGNAUX_EXPLOITATION
    from app.operator.runbooks import sections_runbook

    sections = sections_runbook(ALERTES.read_text(encoding="utf-8"))
    for signal in SIGNAUX_EXPLOITATION:
        fichier, _, ancre = ROUTES_PROVISOIRES[signal]["runbook"].partition("#")
        assert (RACINE / fichier).is_file(), signal
        assert ancre == signal, signal
        assert signal in sections, signal


def test_section_de_chaque_alerte_est_complete_et_coherente_avec_la_route():
    """CA-1 : la section porte propriétaire, sévérité, escalade et première action, comme la route."""
    from app.operator.alertes_registre import ROUTES_PROVISOIRES, SIGNAUX_EXPLOITATION
    from app.operator.runbooks import anomalies_section, sections_runbook, valeur_champ

    sections = sections_runbook(ALERTES.read_text(encoding="utf-8"))
    for signal in SIGNAUX_EXPLOITATION:
        route = ROUTES_PROVISOIRES[signal]
        corps = sections[signal]
        assert anomalies_section(corps) == [], signal
        assert valeur_champ(corps, "Propriétaire") == route["owner"], signal
        assert valeur_champ(corps, "Sévérité") == route["severity"], signal


def test_runbook_de_restauration_reference_un_exercice_date_et_une_preuve():
    """CA-2 : restauration.md porte une date d'exercice valide et une preuve de test existante."""
    from app.operator.runbooks import date_exercice, preuve_exercice

    texte = RESTAURATION.read_text(encoding="utf-8")
    jour = date_exercice(texte)
    assert jour is not None
    assert isinstance(jour, date)
    preuve = preuve_exercice(texte)
    assert preuve is not None
    assert (RACINE / preuve).is_file()


def test_runbook_sans_proprietaire_est_refuse():
    """CA-3 : un runbook sans propriétaire, ou avec un propriétaire vide, est refusé."""
    from app.operator.runbooks import anomalies_fichier_runbook

    assert anomalies_fichier_runbook("# Titre\n\nSans propriétaire.\n") == ["Propriétaire"]
    assert anomalies_fichier_runbook("# Titre\n\nPropriétaire :   \n") == ["Propriétaire"]


def test_chaque_fichier_d_exploitation_declare_un_proprietaire():
    """CA-3 : tous les runbooks de docs/exploitation/ déclarent un propriétaire non vide."""
    from app.operator.runbooks import anomalies_fichier_runbook

    fichiers = sorted(DOSSIER_RUNBOOKS.glob("*.md"))
    assert fichiers
    for fichier in fichiers:
        texte = fichier.read_text(encoding="utf-8")
        assert anomalies_fichier_runbook(texte) == [], fichier.name
        assert re.search(r"^Propriétaire\s*:\s*\S", texte, re.M), fichier.name
