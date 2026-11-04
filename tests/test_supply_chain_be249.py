"""Sécurité applicative, dépendances et SBOM (BE-249).

Périmètre fixé par la définition BE-249 (implementation-backend/tasks-exploitation-architecture.md) :
  - CA-1 : un SBOM est produit par révision et lié à l'artefact ;
  - CA-2 : une dépendance vulnérable introduite fait échouer le pipeline ou exige une
    exception datée ;
  - CA-3 : les exceptions expirées bloquent ;
  - CA-4 : sources, criticités et délais NON DÉFINIS (QE-EXP-19) : aucune valeur n'est codée
    dans le module ; les valeurs viennent de la configuration, et une clé absente échoue.

Les tests n'interrogent jamais le réseau : la sortie de pip-audit est fournie en fichier.
Le module testé est chargé depuis son chemin, car scripts/ n'est pas un paquet Python.
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = BACKEND_ROOT / "scripts" / "securite" / "supply_chain.py"
CONFIG_REELLE = BACKEND_ROOT / "scripts" / "securite" / "supply_chain.toml"
EXCEPTIONS_REELLES = BACKEND_ROOT / "scripts" / "securite" / "exceptions_dependances.toml"
REQUIREMENTS_REELLES = BACKEND_ROOT / "requirements.txt"

AUJOURDHUI = "2026-11-03"


def _charge_module():
    spec = importlib.util.spec_from_file_location("supply_chain_be249", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    # Enregistré avant exécution : les dataclasses consultent sys.modules à la définition.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


supply = _charge_module()


def _requirements(tmp_path, lignes=("fastapi==0.141.1", "requests==2.32.0")) -> Path:
    chemin = tmp_path / "requirements.txt"
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin


def _config(tmp_path, *, sources=True, criticite=True, delais=True, criticite_valeur="", duree=0):
    """Écrit une configuration jetable. Une section absente doit faire échouer le chargement."""
    lignes = []
    if sources:
        lignes += ["[sources]", "bases = []", ""]
    if criticite:
        lignes += ["[criticite]", f'criticite_bloquante = "{criticite_valeur}"', ""]
    if delais:
        lignes += ["[delais]", f"duree_maximale_exception_jours = {duree}", ""]
    chemin = tmp_path / "supply_chain.toml"
    chemin.write_text("\n".join(lignes), encoding="utf-8")
    return chemin


def _exceptions(tmp_path, entrees) -> Path:
    lignes = []
    for entree in entrees:
        lignes.append("[[exception]]")
        for cle, valeur in entree.items():
            lignes.append(f'{cle} = "{valeur}"')
        lignes.append("")
    chemin = tmp_path / "exceptions_dependances.toml"
    chemin.write_text("\n".join(lignes), encoding="utf-8")
    return chemin


def _exception_valide(**surcharges):
    entree = {
        "id": "GHSA-test-0001",
        "paquet": "fastapi",
        "version": "0.141.1",
        "motif": "Pas de correctif amont",
        "responsable": "Remy",
        "date": "2026-11-01",
        "expire": "2026-12-31",
    }
    entree.update(surcharges)
    return entree


def _audit(tmp_path, dependances) -> Path:
    """Sortie au format pip-audit -f json : dependances = [(nom, version, [identifiants])]."""
    payload = {
        "dependencies": [
            {
                "name": nom,
                "version": version,
                "vulns": [
                    {"id": identifiant, "fix_versions": [], "aliases": [], "description": ""}
                    for identifiant in identifiants
                ],
            }
            for nom, version, identifiants in dependances
        ]
    }
    chemin = tmp_path / "audit.json"
    chemin.write_text(json.dumps(payload), encoding="utf-8")
    return chemin


def _vulnerabilite_fastapi(tmp_path) -> Path:
    return _audit(tmp_path, [("fastapi", "0.141.1", ["GHSA-test-0001"])])


def _argv(tmp_path, *, audit=None, exceptions=None, config=None, requirements=None,
          revision="rev-test", aujourdhui=AUJOURDHUI):
    return [
        "--requirements", str(requirements or _requirements(tmp_path)),
        "--revision", revision,
        "--artefact", "zylo-office-backend",
        "--sbom-sortie", str(tmp_path / "sbom.json"),
        "--config", str(config or _config(tmp_path)),
        "--exceptions", str(exceptions if exceptions is not None else _exceptions(tmp_path, [])),
        "--audit-json", str(audit if audit is not None else _audit(tmp_path, [])),
        "--aujourdhui", aujourdhui,
    ]


# CA-1 : SBOM par révision, lié à l'artefact.

def test_sbom_est_produit_par_revision_et_lie_a_l_artefact(tmp_path):
    requirements = _requirements(tmp_path)
    assert supply.main(_argv(tmp_path, requirements=requirements, revision="abc123")) == 0

    sbom = json.loads((tmp_path / "sbom.json").read_text(encoding="utf-8"))
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["metadata"]["component"]["name"] == "zylo-office-backend"
    proprietes = {p["name"]: p["value"] for p in sbom["metadata"]["properties"]}
    assert proprietes["zylo:revision"] == "abc123"
    assert proprietes["zylo:requirements.sha256"] == hashlib.sha256(
        requirements.read_bytes()
    ).hexdigest()


def test_sbom_liste_chaque_dependance_epinglee(tmp_path):
    requirements = _requirements(
        tmp_path, ["fastapi==0.141.1", "uvicorn[standard]==0.52.4", "# commentaire", ""]
    )
    sbom = supply.generer_sbom(requirements, "rev", "zylo-office-backend")

    paires = {(c["name"], c["version"]) for c in sbom["components"]}
    assert paires == {("fastapi", "0.141.1"), ("uvicorn", "0.52.4")}
    assert all(c["purl"] == f"pkg:pypi/{c['name']}@{c['version']}" for c in sbom["components"])


def test_sbom_du_depot_couvre_toutes_les_lignes_epinglees():
    sbom = supply.generer_sbom(REQUIREMENTS_REELLES, "rev", "zylo-office-backend")
    attendues = [
        ligne
        for ligne in REQUIREMENTS_REELLES.read_text(encoding="utf-8").splitlines()
        if ligne.strip() and not ligne.lstrip().startswith("#")
    ]
    assert len(sbom["components"]) == len(attendues)


def test_sbom_refuse_une_dependance_non_epinglee(tmp_path):
    requirements = _requirements(tmp_path, ["fastapi>=0.141"])
    with pytest.raises(supply.ErreurSupplyChain):
        supply.generer_sbom(requirements, "rev", "zylo-office-backend")


# CA-2 : dépendance vulnérable = échec du pipeline ou exception datée.

def test_vulnerabilite_sans_exception_fait_echouer_le_pipeline(tmp_path, capsys):
    assert supply.main(_argv(tmp_path, audit=_vulnerabilite_fastapi(tmp_path))) == 1
    assert "GHSA-test-0001" in capsys.readouterr().out


def test_vulnerabilite_couverte_par_exception_datee_passe(tmp_path):
    exceptions = _exceptions(tmp_path, [_exception_valide()])
    assert supply.main(
        _argv(tmp_path, audit=_vulnerabilite_fastapi(tmp_path), exceptions=exceptions)
    ) == 0


def test_exception_pour_une_autre_version_ne_couvre_pas(tmp_path):
    exceptions = _exceptions(tmp_path, [_exception_valide(version="0.1.0")])
    assert supply.main(
        _argv(tmp_path, audit=_vulnerabilite_fastapi(tmp_path), exceptions=exceptions)
    ) == 1


@pytest.mark.parametrize("champ", ["motif", "responsable", "date", "expire"])
def test_exception_incomplete_est_refusee(tmp_path, champ):
    entree = _exception_valide()
    del entree[champ]
    exceptions = _exceptions(tmp_path, [entree])
    assert supply.main(
        _argv(tmp_path, audit=_vulnerabilite_fastapi(tmp_path), exceptions=exceptions)
    ) == 1


def test_audit_sans_vulnerabilite_passe(tmp_path):
    assert supply.main(_argv(tmp_path)) == 0


def test_sortie_d_audit_illisible_echoue_fermee(tmp_path):
    illisible = tmp_path / "audit.json"
    illisible.write_text("pas du json", encoding="utf-8")
    assert supply.main(_argv(tmp_path, audit=illisible)) == 1


# CA-3 : les exceptions expirées bloquent.

def test_exception_expiree_bloque_meme_sans_vulnerabilite(tmp_path, capsys):
    exceptions = _exceptions(tmp_path, [_exception_valide(date="2026-09-01", expire="2026-10-01")])
    assert supply.main(_argv(tmp_path, exceptions=exceptions)) == 1
    assert "expirée" in capsys.readouterr().out


def test_exception_qui_expire_le_jour_meme_reste_valide(tmp_path):
    exceptions = _exceptions(tmp_path, [_exception_valide(expire=AUJOURDHUI)])
    assert supply.main(
        _argv(tmp_path, audit=_vulnerabilite_fastapi(tmp_path), exceptions=exceptions)
    ) == 0


def test_exception_expiree_ne_couvre_plus_la_vulnerabilite(tmp_path):
    exceptions = _exceptions(tmp_path, [_exception_valide(date="2026-09-01", expire="2026-10-31")])
    assert supply.main(
        _argv(tmp_path, audit=_vulnerabilite_fastapi(tmp_path), exceptions=exceptions)
    ) == 1


# CA-4 : sources, criticités et délais NON DÉFINIS, sans valeur codée.

def test_configuration_reelle_declare_les_valeurs_non_definies_vides():
    config = supply.charger_configuration(CONFIG_REELLE)
    assert tuple(config.sources) == ()
    assert config.criticite_bloquante == ""
    assert config.duree_maximale_exception_jours == 0


@pytest.mark.parametrize(
    "section_absente", ["sources", "criticite", "delais"]
)
def test_cle_absente_fait_echouer_le_chargement(tmp_path, section_absente):
    config = _config(tmp_path, **{section_absente: False})
    with pytest.raises(supply.ErreurSupplyChain):
        supply.charger_configuration(config)


def test_criticite_renseignee_est_refusee_tant_que_non_implementee(tmp_path):
    config = _config(tmp_path, criticite_valeur="haute")
    with pytest.raises(supply.ErreurSupplyChain):
        supply.charger_configuration(config)


def test_delai_maximal_vient_de_la_configuration(tmp_path):
    # Exception valide de 120 jours (2026-11-01 -> 2027-03-01) couvrant la vulnérabilité.
    exceptions = _exceptions(tmp_path, [_exception_valide(expire="2027-03-01")])
    audit = _vulnerabilite_fastapi(tmp_path)

    assert supply.main(
        _argv(tmp_path, audit=audit, exceptions=exceptions, config=_config(tmp_path, duree=30))
    ) == 1
    assert supply.main(
        _argv(tmp_path, audit=audit, exceptions=exceptions, config=_config(tmp_path, duree=0))
    ) == 0


def test_fichiers_reels_sans_exception_active():
    assert supply.charger_exceptions(EXCEPTIONS_REELLES) == []
