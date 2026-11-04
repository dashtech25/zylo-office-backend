"""BE-223 : migrations de schéma versionnées et contrôlées.

Intention : prouver par des tests que
- la chaîne Alembic du dépôt a une seule tête, une seule base (CA-1) ;
- chaque révision porte une fonction downgrade() (réversibilité déclarée) ;
- le contrôle de la tête refuse une chaîne à plusieurs têtes ;
- upgrade puis downgrade jusqu'à la base socle puis upgrade de retour
  réussissent sur la base de test jetable (CA-2) ;
- une migration destructive factice sans confirmation ni sauvegarde échoue
  le contrôle (CA-5).

Les tests d'interruption (CA-3, lié à BE-258) et de compatibilité N/N-1
(CA-4) ne sont pas couverts ici : ils relèvent de leurs propres tâches.
La base de test est celle de tests/conftest.py (zylo_t<NNN>_test) : aucune
base de développement n'est lue ni modifiée.
"""

import ast
from pathlib import Path

import pytest
from alembic import command

from app.core import migrations
from app.core.migrations import (
    REVISIONS_DESTRUCTIVES,
    MigrationError,
    config_alembic,
    garde_destructive,
    revisions_attendues,
)

RACINE = Path(__file__).resolve().parent.parent
BASE_SOCLE = "ab0ecf05c6ca"


def test_chaine_de_migrations_a_une_seule_tete_et_une_seule_base():
    """CA-1 : le dépôt n'a qu'une tête Alembic et part d'une seule base."""
    script = migrations.script_directory()
    tetes = script.get_heads()
    assert len(tetes) == 1, f"plusieurs têtes Alembic : {tetes}"
    assert script.get_bases() == [BASE_SOCLE]


def test_chaque_revision_porte_une_fonction_downgrade():
    """Chaque migration déclare downgrade() : la réversibilité est explicite."""
    manquantes = []
    for fichier in sorted((RACINE / "alembic" / "versions").glob("*.py")):
        arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        if not any(isinstance(n, ast.FunctionDef) and n.name == "downgrade" for n in arbre.body):
            manquantes.append(fichier.name)
    assert not manquantes, f"migrations sans downgrade() : {manquantes}"


def test_controle_de_tete_refuse_plusieurs_tetes_et_accepte_une_tete():
    """Le contrôle de la tête lève MigrationError si la chaîne a plusieurs têtes."""
    with pytest.raises(MigrationError, match="plusieurs têtes"):
        migrations.verifie_tete_unique({"aaaa11112222", "bbbb33334444"})
    assert migrations.verifie_tete_unique({"aaaa11112222"}) == "aaaa11112222"
    assert migrations.verifie_tete_unique() == next(iter(revisions_attendues()))


def test_aller_retour_upgrade_downgrade_sur_base_de_test():
    """CA-2 : downgrade jusqu'à la base socle puis upgrade de retour à la tête."""
    cfg = config_alembic()
    tete = migrations.verifie_tete_unique()
    command.downgrade(cfg, BASE_SOCLE)
    command.upgrade(cfg, "head")
    assert revisions_attendues() == {tete}


def test_migration_destructive_factice_sans_marqueur_echoue(monkeypatch):
    """CA-5 : une migration destructive sans confirmation ni sauvegarde est refusée."""
    factice = "fac0000000ab"
    monkeypatch.setitem(REVISIONS_DESTRUCTIVES, factice, "migration factice de test")
    with pytest.raises(MigrationError, match="confirmation explicite"):
        garde_destructive([factice], base_vide=False, confirmation=False, sauvegarde=None)
    with pytest.raises(MigrationError, match="--sauvegarde"):
        garde_destructive([factice], base_vide=False, confirmation=True, sauvegarde=None)
