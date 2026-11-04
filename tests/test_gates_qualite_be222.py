"""Gates qualité serveur (BE-222) : tests du gate lui-même.

Périmètre fixé par la définition BE-222 (implementation-backend/tasks-exploitation-architecture.md) :
  - CA-1 : un défaut connu introduit volontairement fait échouer le gate ;
  - CA-2 : une exception de lint ou de test est datée et assignée, sinon refusée ;
  - CA-3 : les résultats sont versionnés par révision de source ;
  - CA-4 : seuils de couverture, durée et flakiness lus depuis la configuration,
    jamais codés en dur (une clé absente fait échouer le chargement, sans repli).

Les tests travaillent sur des dépôts jetables (tmp_path) avec leur propre configuration ;
le module testé est chargé depuis son chemin, car scripts/ n'est pas un paquet Python.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
GATES_PATH = BACKEND_ROOT / "scripts" / "qualite" / "gates.py"
CONFIG_REELLE = BACKEND_ROOT / "scripts" / "qualite" / "gates.toml"
EXCEPTIONS_REELLES = BACKEND_ROOT / "scripts" / "qualite" / "exceptions.toml"


def _charge_module():
    spec = importlib.util.spec_from_file_location("gates_qualite_be222", GATES_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gates = _charge_module()


def _configuration(tmp_path, etapes, couverture=80, duree=900, relances=2) -> Path:
    """Écrit une configuration de gate jetable et renvoie son chemin."""
    lignes = [
        "[seuils]",
        f"couverture_minimale = {couverture}",
        f"duree_maximale_secondes = {duree}",
        f"relances_flaky = {relances}",
        "",
    ]
    for nom, commande in etapes:
        lignes += [
            "[[etape]]",
            f'nom = "{nom}"',
            "commande = [" + ", ".join(f'"{x}"' for x in commande) + "]",
            "",
        ]
    chemin = tmp_path / "gates.toml"
    chemin.write_text("\n".join(lignes), encoding="utf-8")
    return chemin


def _exceptions(tmp_path, bloc: str) -> Path:
    chemin = tmp_path / "exceptions.toml"
    chemin.write_text(bloc, encoding="utf-8")
    return chemin


PASSE = [sys.executable, "-c", "pass"]
DEFAUT_CONNU = [sys.executable, "-c", "raise SystemExit(1)"]


# CA-1 : un défaut connu introduit volontairement fait échouer le gate.
def test_be222_ca1_defaut_connu_fait_echouer_le_gate(tmp_path):
    config = _configuration(tmp_path, [("controle", PASSE), ("defaut", DEFAUT_CONNU)])
    exceptions = _exceptions(tmp_path, "")
    code = gates.executer_gate(config, exceptions, tmp_path / "rapports", "rev1")
    assert code != 0


def test_be222_ca1_gate_vert_quand_aucun_defaut(tmp_path):
    config = _configuration(tmp_path, [("controle", PASSE)])
    exceptions = _exceptions(tmp_path, "")
    code = gates.executer_gate(config, exceptions, tmp_path / "rapports", "rev1")
    assert code == 0


# CA-2 : une exception est datée et assignée ; sans date ou sans responsable, elle est refusée.
EXCEPTION_COMPLETE = """
[[exception]]
id = "EXC-001"
outil = "pytest"
cible = "tests/test_x.py::test_y"
motif = "dépendance externe indisponible en local"
responsable = "remy"
date = "2026-11-03"
"""


def test_be222_ca2_exception_datee_et_assignee_acceptee(tmp_path):
    chemin = _exceptions(tmp_path, EXCEPTION_COMPLETE)
    assert gates.valider_exceptions(chemin) == []


def test_be222_ca2_exception_sans_date_refusee(tmp_path):
    bloc = EXCEPTION_COMPLETE.replace('date = "2026-11-03"\n', "")
    erreurs = gates.valider_exceptions(_exceptions(tmp_path, bloc))
    assert erreurs, "une exception sans date doit être refusée"
    assert any("date" in e for e in erreurs)


def test_be222_ca2_exception_sans_responsable_refusee(tmp_path):
    bloc = EXCEPTION_COMPLETE.replace('responsable = "remy"\n', "")
    erreurs = gates.valider_exceptions(_exceptions(tmp_path, bloc))
    assert erreurs
    assert any("responsable" in e for e in erreurs)


def test_be222_ca2_exception_invalide_fait_echouer_le_gate(tmp_path):
    bloc = EXCEPTION_COMPLETE.replace('date = "2026-11-03"\n', "")
    config = _configuration(tmp_path, [("controle", PASSE)])
    code = gates.executer_gate(
        config, _exceptions(tmp_path, bloc), tmp_path / "rapports", "rev1"
    )
    assert code != 0


# CA-3 : résultats versionnés par révision de source.
def test_be222_ca3_rapport_present_par_identifiant_de_revision(tmp_path):
    config = _configuration(tmp_path, [("controle", PASSE)])
    dossier = tmp_path / "rapports"
    gates.executer_gate(config, _exceptions(tmp_path, ""), dossier, "a1b2c3d")

    assert gates.rapport_present(dossier, "a1b2c3d")
    assert not gates.rapport_present(dossier, "autre")

    contenu = json.loads((dossier / "a1b2c3d.json").read_text(encoding="utf-8"))
    assert contenu["revision"] == "a1b2c3d"
    assert contenu["verdict"] == "vert"
    assert contenu["etapes"][0]["nom"] == "controle"


def test_be222_ca3_rapport_rouge_si_etape_en_echec(tmp_path):
    config = _configuration(tmp_path, [("defaut", DEFAUT_CONNU)])
    dossier = tmp_path / "rapports"
    gates.executer_gate(config, _exceptions(tmp_path, ""), dossier, "rev9")
    contenu = json.loads((dossier / "rev9.json").read_text(encoding="utf-8"))
    assert contenu["verdict"] == "rouge"


# CA-4 : seuils lus depuis la configuration, aucune valeur codée.
def test_be222_ca4_seuils_lus_depuis_la_configuration(tmp_path):
    config_stricte = gates.charger_configuration(
        _configuration(tmp_path, [("controle", PASSE)], couverture=85)
    )
    assert config_stricte.couverture_minimale == 85

    erreurs = gates.verifier_seuils(
        {"couverture": 82, "duree_secondes": 10, "echecs_relance": 0}, config_stricte
    )
    assert erreurs, "82 % doit échouer si le seuil de configuration vaut 85"

    dossier_souple = tmp_path / "souple"
    dossier_souple.mkdir()
    config_souple = gates.charger_configuration(
        _configuration(dossier_souple, [("controle", PASSE)], couverture=80)
    )
    assert gates.verifier_seuils(
        {"couverture": 82, "duree_secondes": 10, "echecs_relance": 0}, config_souple
    ) == []


def test_be222_ca4_duree_et_flakiness_lues_depuis_la_configuration(tmp_path):
    config = gates.charger_configuration(
        _configuration(tmp_path, [("controle", PASSE)], duree=60, relances=1)
    )
    erreurs = gates.verifier_seuils(
        {"couverture": 100, "duree_secondes": 61, "echecs_relance": 2}, config
    )
    assert len(erreurs) == 2


def test_be222_ca4_cle_absente_echoue_sans_valeur_par_defaut(tmp_path):
    """Pas de repli codé : une clé de seuil absente de la configuration fait échouer le chargement."""
    chemin = tmp_path / "gates.toml"
    chemin.write_text(
        '[seuils]\nduree_maximale_secondes = 900\nrelances_flaky = 2\n'
        '[[etape]]\nnom = "x"\ncommande = ["true"]\n',
        encoding="utf-8",
    )
    with pytest.raises(gates.ConfigurationInvalide):
        gates.charger_configuration(chemin)


def test_be222_ca4_configuration_reelle_du_depot_se_charge_et_exceptions_valides():
    config = gates.charger_configuration(CONFIG_REELLE)
    assert config.etapes, "la configuration du dépôt doit déclarer au moins une étape"
    assert gates.valider_exceptions(EXCEPTIONS_REELLES) == []
