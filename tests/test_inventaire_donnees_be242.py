"""BE-242 : inventaire des données et classes de rétention.

Intention : prouver par des tests que
- chaque table de l'application (schéma réellement migré) figure dans
  l'inventaire `data_inventory` (CA-1) ;
- un champ sans classe ou sans propriétaire fait échouer le contrôle (CA-2) ;
- une classe sans durée de rétention décidée est marquée NON DÉFINI et bloque
  la suppression automatique (CA-3) ;
- la lecture de l'inventaire sans permission `donnees.inventaire.lire` donne
  403 (CA-4).

La base de test est celle de tests/conftest.py (zylo_t<NNN>_test) ; aucune
base de développement n'est lue ni modifiée.
"""

import uuid

import pytest

from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.data_inventory.permissions import DONNEES_INVENTAIRE_LIRE
from app.data_inventory.service import (
    NON_DEFINI,
    ENTREES_TABLES,
    lire_inventaire,
    retention_decidee,
    suppression_automatique_autorisee,
    tables_du_schema,
    tables_sans_inventaire,
    valider_champ,
)


@pytest.fixture
async def pool_de_boucle_courante():
    """Repart d'un pool neuf lié à la boucle d'événements du test.

    Même précaution que la fixture `client` de conftest.py : l'engine est un
    singleton dont les connexions restent liées à la boucle qui les a ouvertes.
    """
    await engine.dispose()
    yield


async def test_chaque_table_du_schema_figure_dans_l_inventaire(pool_de_boucle_courante):
    """CA-1 : aucune table migrée n'est absente du registre d'inventaire."""
    async with AsyncSessionLocal() as db:
        manquantes = await tables_sans_inventaire(db)
        schema = await tables_du_schema(db)
    assert schema, "le schéma migré ne contient aucune table"
    assert "data_inventory" in schema
    assert manquantes == [], f"tables absentes de l'inventaire : {manquantes}"


def test_champ_sans_classe_ni_proprietaire_fait_echouer_le_controle():
    """CA-2 : un champ sans classe ou sans propriétaire est signalé comme anomalie."""
    anomalies = valider_champ({"objet": "user", "champ": "email", "classe": None, "proprietaire": ""})
    assert set(anomalies) == {"classe", "proprietaire"}

    anomalies_completes = valider_champ({"objet": "user", "champ": "email", "classe": "personnelle", "proprietaire": "socle-identite"})
    assert anomalies_completes == []


def test_entrees_du_registre_ont_toutes_classe_et_proprietaire():
    """CA-2 (registre réel) : aucune entrée livrée ne viole le contrôle de champ."""
    for table, entree in ENTREES_TABLES.items():
        assert valider_champ({"objet": table, "champ": "*", **entree}) == [], table


def test_classe_sans_duree_decidee_est_non_definie_et_bloque_la_suppression():
    """CA-3 : sans durée décidée, la rétention vaut NON DÉFINI et la suppression automatique est refusée."""
    assert retention_decidee(None) is False
    assert NON_DEFINI == "NON DÉFINI"
    assert suppression_automatique_autorisee("personnelle", None) is False
    assert suppression_automatique_autorisee("personnelle", 365) is True


async def test_lecture_inventaire_sans_permission_donne_403(pool_de_boucle_courante):
    """CA-4 : un utilisateur sans la permission d'inventaire reçoit 403."""
    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await lire_inventaire(db, uuid.uuid4(), uuid.uuid4())
    assert erreur.value.status_code == 403
    assert erreur.value.code == "permission_denied"
    assert DONNEES_INVENTAIRE_LIRE == "donnees.inventaire.lire"
