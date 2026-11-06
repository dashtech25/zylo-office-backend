"""Contrôle l'inventaire du socle contre les modèles chargés par l'application."""

from pathlib import Path

import app.main  # noqa: F401 — enregistre les modèles réellement montés par l'application.
from app.core.database import Base


RACINE_BACKEND = Path(__file__).resolve().parents[1]
FICHIER_INVENTAIRE = (
    RACINE_BACKEND / "docs/architecture/inventaire-tables-socle.md"
)

# Ces deux paquets sont des modules métier. Les capacités transversales comme
# fichiers, alertes ou localisation restent dans l'inventaire, même si leurs
# noms de table contiennent « zyloLiquid ».
PAQUETS_METIER_EXCLUS = (
    "app.modules.zylo_liquid.",
    "app.modules.zylo_tanker.",
)

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


def _tables_metier_exclues() -> set[str]:
    """Retourne les tables attribuées aux deux paquets métier exclus."""
    tables = set()
    for mapper in Base.registry.mappers:
        module = mapper.class_.__module__
        if any(module.startswith(prefix) for prefix in PAQUETS_METIER_EXCLUS):
            tables.add(mapper.local_table.name)
    return tables


def _tables_du_socle() -> dict[str, object]:
    """Retourne toutes les tables SQLAlchemy hors paquets métier exclus."""
    tables_metier = _tables_metier_exclues()
    return {
        table.name: table
        for table in Base.metadata.tables.values()
        if table.name not in tables_metier
    }


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
    tables_socle = _tables_du_socle()
    lignes = _lignes_inventaire()

    assert lignes.keys() == tables_socle.keys(), (
        f"Tables absentes: {sorted(tables_socle.keys() - lignes.keys())}; "
        f"tables hors périmètre: {sorted(lignes.keys() - tables_socle.keys())}"
    )


def test_document_est_identique_au_rendu_de_generation() -> None:
    """CA-3 : le document versionné est le rendu canonique du générateur."""
    from app.core.table_inventory import render_inventory_markdown

    document = FICHIER_INVENTAIRE.read_text(encoding="utf-8")
    assert document == render_inventory_markdown()


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
    tables_socle = _tables_du_socle()
    lignes = _lignes_inventaire()
    colonnes_tenant = {
        "tenantid",
        "tenant_id",
        "beneficiarytenantid",
        "beneficiary_tenant_id",
    }
    sans_portee = [
        nom
        for nom, table in tables_socle.items()
        if any(colonne.name.lower() in colonnes_tenant for colonne in table.columns)
        and lignes[nom]["portée"].strip().lower() in PORTÉES_NON_DÉFINIES
    ]

    assert not sans_portee, f"Tables avec tenantId sans portée: {sorted(sans_portee)}"
