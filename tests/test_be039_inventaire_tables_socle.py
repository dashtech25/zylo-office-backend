"""Contrôle l'inventaire du socle contre les modèles chargés par l'application.

Le périmètre est lu dans un processus Python neuf (générateur avec ``--noms-tables``),
et non dans le registre SQLAlchemy de la session pytest : pendant l'exécution des
tests, d'autres modules peuvent enregistrer des tables qui ne font pas partie du
montage de l'application. Le document est comparé au rendu du générateur, lancé
lui aussi dans un processus neuf.
"""

import json
import subprocess
import sys
from pathlib import Path

import app.main  # noqa: F401 — enregistre les modèles réellement montés par l'application.
from app.core.database import Base
from app.core.table_inventory import MODULES_ORM_SOCLE_HORS_APP


RACINE_BACKEND = Path(__file__).resolve().parents[1]
FICHIER_INVENTAIRE = (
    RACINE_BACKEND / "docs/architecture/inventaire-tables-socle.md"
)
GENERATEUR = RACINE_BACKEND / "scripts/docs/generer_inventaire_tables_socle.py"

COLONNES_ATTENDUES = (
    "table",
    "propriétaire",
    "portée",
    "routes http",
    "tests associés",
)
PORTÉES_NON_DÉFINIES = {
    "non défini",
    "non définie",
    "à déterminer",
    "nd",
    "n/a",
    "—",
}

# Importe en session les modules hors montage de app.main, pour que les
# colonnes des tables du périmètre soient disponibles dans Base.metadata.
for _module in MODULES_ORM_SOCLE_HORS_APP:
    __import__(_module)


def _noms_tables_socle() -> set[str]:
    """Retourne les noms des tables du socle, lus dans un processus neuf.

    Le processus neuf reproduit exactement le périmètre du générateur : application
    montée plus modules ORM hors montage listés dans ``MODULES_ORM_SOCLE_HORS_APP``.
    """
    resultat = subprocess.run(
        [sys.executable, str(GENERATEUR), "--noms-tables"],
        cwd=RACINE_BACKEND,
        capture_output=True,
        text=True,
        check=True,
    )
    return set(json.loads(resultat.stdout))


def _lignes_inventaire() -> dict[str, dict[str, str]]:
    """Lit les lignes de données du tableau Markdown de l'inventaire."""
    assert FICHIER_INVENTAIRE.is_file(), (
        "Document d'inventaire BE-039 absent : "
        "docs/architecture/inventaire-tables-socle.md"
    )
    texte = FICHIER_INVENTAIRE.read_text(encoding="utf-8")
    lignes = [ligne for ligne in texte.splitlines() if ligne.strip().startswith("|")]
    assert len(lignes) >= 2, "Le document doit contenir un tableau Markdown"

    entetes = [cellule.strip().strip("`").lower() for cellule in lignes[0].strip().strip("|").split("|")]
    assert entetes == list(COLONNES_ATTENDUES), (
        f"Colonnes attendues: {COLONNES_ATTENDUES}; trouvées: {entetes}"
    )

    resultat: dict[str, dict[str, str]] = {}
    for ligne in lignes[2:]:  # Ignore l'en-tête et la ligne de séparation.
        cellules = [cellule.strip() for cellule in ligne.strip().strip("|").split("|")]
        assert len(cellules) == len(entetes), f"Ligne de tableau invalide: {ligne}"
        valeurs = dict(zip(entetes, cellules))
        nom_table = valeurs["table"].strip("`")
        assert nom_table, f"Nom de table vide: {ligne}"
        assert nom_table not in resultat, f"Table répétée dans l'inventaire: {nom_table}"
        resultat[nom_table] = valeurs
    return resultat


def test_inventaire_couvre_les_tables_mappées_du_socle() -> None:
    """CA-3 : chaque table mappée du socle apparaît dans le document."""
    noms_socle = _noms_tables_socle()
    lignes = _lignes_inventaire()

    assert lignes.keys() == noms_socle, (
        f"Tables absentes: {sorted(noms_socle - lignes.keys())}; "
        f"tables hors périmètre: {sorted(lignes.keys() - noms_socle)}"
    )


def test_document_est_identique_au_rendu_de_generation() -> None:
    """CA-3 : le document versionné est le rendu canonique du générateur (contrôle --check)."""
    resultat = subprocess.run(
        [sys.executable, str(GENERATEUR), "--check"],
        cwd=RACINE_BACKEND,
        capture_output=True,
        text=True,
    )
    assert resultat.returncode == 0, resultat.stderr.strip()


def test_inventaire_renseigne_proprietaire_portee_routes_et_tests() -> None:
    """CA-1 : chaque ligne nomme propriétaire, portée, routes et tests."""
    lignes = _lignes_inventaire()
    assert lignes, "L'inventaire doit contenir au moins une table"

    champs = COLONNES_ATTENDUES[1:]
    incomplets = {
        nom: [champ for champ in champs if not valeurs[champ].strip()]
        for nom, valeurs in lignes.items()
    }
    incomplets = {nom: manquants for nom, manquants in incomplets.items() if manquants}
    assert not incomplets, f"Champs non renseignés: {incomplets}"


def test_tables_avec_tenant_id_ont_une_portee_definie() -> None:
    """CA-2 : les variantes de colonnes tenant imposent une portée définie."""
    noms_socle = _noms_tables_socle()
    lignes = _lignes_inventaire()
    colonnes_tenant = {
        "tenantid",
        "tenant_id",
        "beneficiarytenantid",
        "beneficiary_tenant_id",
    }
    sans_portee = [
        nom
        for nom in sorted(noms_socle)
        if any(
            colonne.name.lower() in colonnes_tenant
            for colonne in Base.metadata.tables[nom].columns
        )
        and lignes[nom]["portée"].strip().lower() in PORTÉES_NON_DÉFINIES
    ]

    assert not sans_portee, f"Tables avec tenantId sans portée: {sorted(sans_portee)}"
