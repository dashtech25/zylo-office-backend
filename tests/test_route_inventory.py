"""Inventaire des routes protégées (T-023).

Intention : échouer dès qu'une route métier n'a ni garde d'appartenance à
l'organisation, ni exception publique justifiée (ROUTES_PUBLIQUES), et dès
qu'une route de module apparaît sans garde de permission hors de la liste
connue (tests/route_baseline_sans_permission.txt). La liste connue ne doit
que diminuer : une route corrigée doit en être retirée.
"""

from pathlib import Path

from app.main import app
from tests.route_inventory import PREFIXES_MODULE, ROUTES_PUBLIQUES, inventaire, matrice_markdown

BASELINE = Path(__file__).with_name("route_baseline_sans_permission.txt")
MATRICE = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "securite" / "matrice-autorisation.md"


def _baseline() -> set[str]:
    return {
        ligne.strip()
        for ligne in BASELINE.read_text(encoding="utf-8").splitlines()
        if ligne.strip() and not ligne.startswith("#")
    }


def test_inventaire_couvre_les_routes_de_modules():
    """Garde contre un test vide : l'inventaire doit voir les routes des modules."""
    infos = inventaire(app)
    assert len(infos) > 200
    assert any(i.module_routes for i in infos)


def test_toute_route_sans_appartenance_est_publique_et_justifiee():
    """Aucune route sans garde d'appartenance hors de ROUTES_PUBLIQUES."""
    fautives = [i.cle for i in inventaire(app) if not i.appartenance and i.cle not in ROUTES_PUBLIQUES]
    assert fautives == [], f"Routes sans garde d'appartenance et non listées publiques : {fautives}"


def test_exceptions_publiques_correspondent_a_des_routes_existantes():
    """Une exception qui ne correspond plus à une route doit être retirée."""
    cles = {i.cle for i in inventaire(app)}
    perimees = sorted(c for c in ROUTES_PUBLIQUES if c not in cles)
    assert perimees == [], f"Exceptions publiques sans route correspondante : {perimees}"


def test_route_de_module_sans_permission_hors_liste_connue():
    """Une route de module nouvelle doit avoir une garde de permission."""
    sans_permission = {i.cle for i in inventaire(app) if i.module_routes and not i.permissions}
    nouvelles = sorted(sans_permission - _baseline())
    assert nouvelles == [], f"Routes de module sans garde de permission (non connues) : {nouvelles}"


def test_liste_connue_ne_contient_que_des_routes_encore_sans_garde():
    """La dette ne grossit pas et ne reste pas figée : une route corrigée sort de la liste."""
    infos = {i.cle: i for i in inventaire(app)}
    corrigees = sorted(c for c in _baseline() if c in infos and infos[c].permissions)
    absentes = sorted(c for c in _baseline() if c not in infos)
    assert corrigees == [], f"Routes désormais gardées, à retirer de la liste connue : {corrigees}"
    assert absentes == [], f"Routes disparues, à retirer de la liste connue : {absentes}"


def test_prefixes_modules_couvrent_les_modules_actuels():
    chemins = [i.path for i in inventaire(app) if i.module_routes]
    for prefixe in PREFIXES_MODULE:
        assert any(c.startswith(prefixe) for c in chemins), prefixe


def test_matrice_documentee_a_jour():
    """La matrice versionnée est celle que produit le code (relancer le script si ce test échoue)."""
    assert MATRICE.read_text(encoding="utf-8") == matrice_markdown(inventaire(app))
