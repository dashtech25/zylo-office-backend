"""Documentation du domaine modules (BE-061).

Intention : vérifier, sans liste écrite à la main, que la documentation du domaine
`app/modules_registry` (routes, docstrings, valeurs NON DÉFINIES) reste en accord
avec le code réel. Périmètre : toute route dont le handler est défini dans
`app.modules_registry` (lue depuis l'application réelle).

Critères de la définition (implementation-backend/tasks-modules-droits.md, BE-061) :
- CA-1 : chaque route du domaine figure dans `docs/modules/routes.md` avec méthode,
  chemin, permission et codes HTTP. Les lignes de la table qui ne correspondent à
  aucune route réelle du domaine sont aussi refusées (table périmée).
- CA-2 : chaque fonction, classe publique (sans `_` initial) du domaine possède une
  docstring. La définition demande un outil d'analyse statique (BE-222) ; ce test
  reproduit le contrôle en lecture AST pour que le critère soit vérifiable localement.
- CA-3 : toute ligne du domaine qui contient « NON DÉFINI » renvoie à un QE-MOD-nn.
- CA-4 : chaque document `.md` lié depuis `docs/modules/routes.md` existe.

Les tests ne lisent que le code et la documentation ; ils ne touchent pas la base.
"""

import ast
import re
from pathlib import Path

from app.main import app
from tests.route_inventory import _iter_routes

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DOMAINE_DIR = BACKEND_ROOT / "app" / "modules_registry"
DOMAINE_MODULE = "app.modules_registry"
ROUTES_DOC = BACKEND_ROOT / "docs" / "modules" / "routes.md"
METHODES_HTTP = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _routes_du_domaine() -> set[tuple[str, str]]:
    """Retourne les couples (méthode, chemin) des routes dont le handler est dans le domaine."""
    couples: set[tuple[str, str]] = set()
    for chemin, route, _ctx in _iter_routes(app.router):
        if route.endpoint.__module__.startswith(DOMAINE_MODULE):
            for methode in route.methods:
                couples.add((methode, chemin))
    return couples


def _lignes_de_table(texte: str) -> list[list[str]]:
    """Découpe les lignes de tableau Markdown en cellules, sans la ligne de séparation."""
    lignes = []
    for ligne in texte.splitlines():
        if not ligne.strip().startswith("|"):
            continue
        cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cellules if c):
            continue
        lignes.append(cellules)
    return lignes


def test_be061_ca1_chaque_route_du_domaine_est_documentee():
    # CA-1 : une ligne par route, avec méthode, chemin, permission et codes HTTP renseignés.
    assert ROUTES_DOC.exists(), f"document absent : {ROUTES_DOC.relative_to(BACKEND_ROOT)}"
    lignes = _lignes_de_table(ROUTES_DOC.read_text(encoding="utf-8"))
    entete = next(
        (cellules for cellules in lignes if {"Méthode", "Chemin", "Permission", "Codes HTTP"} <= set(cellules)),
        None,
    )
    assert entete is not None, "le tableau doit avoir les colonnes Méthode, Chemin, Permission, Codes HTTP"
    colonnes = {nom: entete.index(nom) for nom in ("Méthode", "Chemin", "Permission", "Codes HTTP")}

    lignes_par_route: dict[tuple[str, str], list[str]] = {}
    for cellules in lignes:
        if len(cellules) <= max(colonnes.values()) or cellules[colonnes["Méthode"]] not in METHODES_HTTP:
            continue
        cle = (cellules[colonnes["Méthode"]], cellules[colonnes["Chemin"]].strip("`"))
        lignes_par_route[cle] = cellules

    attendues = _routes_du_domaine()
    manquantes = sorted(attendues - set(lignes_par_route))
    assert not manquantes, f"routes absentes de la table : {manquantes}"

    for cle in sorted(attendues):
        cellules = lignes_par_route[cle]
        assert cellules[colonnes["Permission"]], f"permission non renseignée pour {cle}"
        assert cellules[colonnes["Codes HTTP"]], f"codes HTTP non renseignés pour {cle}"


def test_be061_ca1_pas_de_ligne_perimee():
    # CA-1 (complément) : une ligne de la table qui ne correspond à aucune route réelle du domaine
    # est refusée, pour qu'une route supprimée ou renommée ne reste pas documentée.
    lignes = _lignes_de_table(ROUTES_DOC.read_text(encoding="utf-8"))
    attendues = _routes_du_domaine()
    perimees = []
    for cellules in lignes:
        if len(cellules) >= 2 and cellules[0] in METHODES_HTTP:
            cle = (cellules[0], cellules[1].strip("`"))
            if cle not in attendues:
                perimees.append(cle)
    assert not perimees, f"lignes sans route réelle du domaine : {perimees}"


def _definitions_publiques(fichier: Path):
    arbre = ast.parse(fichier.read_text(encoding="utf-8"))
    for noeud in arbre.body:
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not noeud.name.startswith("_"):
            yield noeud


def test_be061_ca2_chaque_fonction_publique_du_domaine_a_une_docstring():
    # CA-2 : docstring obligatoire sur toute fonction ou classe publique du domaine.
    sans_docstring = []
    for fichier in sorted(DOMAINE_DIR.rglob("*.py")):
        for noeud in _definitions_publiques(fichier):
            if ast.get_docstring(noeud) is None:
                sans_docstring.append(f"{fichier.relative_to(BACKEND_ROOT)}:{noeud.name}")
    assert not sans_docstring, f"{len(sans_docstring)} sans docstring : {sans_docstring}"


def test_be061_ca3_non_defini_renvoie_a_un_qe():
    # CA-3 : toute valeur NON DÉFINIE du domaine porte son renvoi QE-MOD-nn sur la même ligne.
    fautes = []
    for fichier in sorted(DOMAINE_DIR.rglob("*.py")):
        for numero, ligne in enumerate(fichier.read_text(encoding="utf-8").splitlines(), start=1):
            if "NON DÉFINI" in ligne and not re.search(r"QE-MOD-\d{2}", ligne):
                fautes.append(f"{fichier.relative_to(BACKEND_ROOT)}:{numero}")
    assert not fautes, f"NON DÉFINI sans QE-MOD-nn : {fautes}"


def test_be061_ca4_documents_lies_existent():
    # CA-4 : chaque document Markdown lié depuis routes.md existe (liens relatifs à docs/modules/).
    texte = ROUTES_DOC.read_text(encoding="utf-8")
    cibles = re.findall(r"\]\(([^)#\s]+\.md)\)", texte)
    assert cibles, "routes.md doit citer au moins la doc de module du domaine"
    absents = [cible for cible in cibles if not (ROUTES_DOC.parent / cible).resolve().exists()]
    assert not absents, f"documents liés absents : {absents}"
