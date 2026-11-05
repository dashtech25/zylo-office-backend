"""BE-258 CA-1 : une migration interrompue à chaque étape est reprise sans corruption.

Tests écrits d'après la définition `### BE-258` de implementation-backend/tasks-exploitation-architecture.md,
avant le code.

Mécanisme testé : la chaîne Alembic de l'outil de migration (transaction par révision) est jouée sur la
base de test avec une chaîne SYNTHÉTIQUE de trois révisions, écrite dans un dossier temporaire et suivie
dans une table de version dédiée (`alembic_version_be258`). Les migrations du dépôt ne sont jamais jouées
ici. Pour chaque étape, la révision interrompue lève une erreur APRÈS sa DDL : la transaction de cette
révision doit être annulée (sa table absente), les révisions précédentes restent appliquées, et la reprise
depuis cet état amène la base à la tête sans table en double.

Base : `zylo_t258_test` (via DATABASE_URL, posée par tests/conftest.py). Les tables `be258_etape_*` et la
table de version sont supprimées avant et après chaque test.
"""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

REVISIONS = ["r1", "r2", "r3"]
TABLE_VERSION = "alembic_version_be258"
VARIABLE_INTERRUPTION = "BE258_INTERROMPRE_APRES"

# env.py minimal : même schéma que alembic/env.py (connexion asynchrone, run_sync), mais avec la table
# de version passée par la configuration et une transaction par révision.
ENV_PY = '''
import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine


def _executer(connexion):
    context.configure(
        connection=connexion,
        version_table=context.config.attributes["version_table"],
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _lancer():
    moteur = create_async_engine(context.config.attributes["url"], poolclass=pool.NullPool)
    async with moteur.connect() as connexion:
        await connexion.run_sync(_executer)
    await moteur.dispose()


asyncio.run(_lancer())
'''

# Révision synthétique : crée une table, puis lève une erreur APRÈS sa DDL si elle est désignée.
MODELE_REVISION = '''
import os

import sqlalchemy as sa
from alembic import op

revision = "{rev}"
down_revision = {parent}
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("be258_etape_{numero}", sa.Column("id", sa.Integer(), primary_key=True))
    if os.environ.get("BE258_INTERROMPRE_APRES") == revision:
        raise RuntimeError("interruption simulée BE-258")


def downgrade():
    op.drop_table("be258_etape_{numero}")
'''


def _sql(instructions: list[str]) -> None:
    """Exécute des instructions SQL dans une transaction, sur la base de test."""

    async def _executer() -> None:
        moteur = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        try:
            async with moteur.begin() as connexion:
                for instruction in instructions:
                    await connexion.execute(text(instruction))
        finally:
            await moteur.dispose()

    asyncio.run(_executer())


def _reinitialiser() -> None:
    """Supprime les tables synthétiques et la table de version."""
    _sql(
        [f"DROP TABLE IF EXISTS be258_etape_{n} CASCADE" for n in range(1, len(REVISIONS) + 1)]
        + [f"DROP TABLE IF EXISTS {TABLE_VERSION}"]
    )


def _etat() -> tuple[list[str], list[str]]:
    """Révisions enregistrées et tables synthétiques présentes, lues sur la base de test."""

    async def _lire():
        moteur = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        try:
            async with moteur.connect() as connexion:
                existe = (await connexion.execute(text(f"SELECT to_regclass('{TABLE_VERSION}')"))).scalar()
                versions = []
                if existe is not None:
                    versions = list(
                        (await connexion.execute(text(f"SELECT version_num FROM {TABLE_VERSION} ORDER BY version_num")))
                        .scalars()
                        .all()
                    )
                tables = list(
                    (
                        await connexion.execute(
                            text(
                                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                                "AND tablename LIKE 'be258_etape_%' ORDER BY tablename"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                return versions, tables
        finally:
            await moteur.dispose()

    return asyncio.run(_lire())


@pytest.fixture
def chaine_synthetique(tmp_path: Path) -> Config:
    """Écrit un dossier de migrations à trois révisions et renvoie sa configuration Alembic."""
    versions = tmp_path / "versions"
    versions.mkdir()
    (tmp_path / "env.py").write_text(ENV_PY, encoding="utf-8")
    parents = [None, *REVISIONS[:-1]]
    for numero, (rev, parent) in enumerate(zip(REVISIONS, parents), start=1):
        contenu = MODELE_REVISION.format(rev=rev, parent=repr(parent), numero=numero)
        (versions / f"{rev}_be258.py").write_text(contenu, encoding="utf-8")
    cfg = Config()
    cfg.set_main_option("script_location", str(tmp_path))
    cfg.attributes["url"] = os.environ["DATABASE_URL"]
    cfg.attributes["version_table"] = TABLE_VERSION
    return cfg


@pytest.fixture
def base_synthetique_propre(monkeypatch):
    """Base sans table synthétique avant et après le test ; aucune interruption armée."""
    monkeypatch.delenv(VARIABLE_INTERRUPTION, raising=False)
    _reinitialiser()
    yield
    _reinitialiser()


@pytest.mark.parametrize("etape_interrompue", REVISIONS)
def test_be258_ca1_migration_interrompue_puis_reprise_sans_corruption(
    chaine_synthetique, base_synthetique_propre, monkeypatch, etape_interrompue
):
    """CA-1 : interruption à chaque étape, état annulé proprement, reprise contrôlée jusqu'à la tête."""
    rang = REVISIONS.index(etape_interrompue)

    monkeypatch.setenv(VARIABLE_INTERRUPTION, etape_interrompue)
    with pytest.raises(RuntimeError, match="interruption simulée BE-258"):
        command.upgrade(chaine_synthetique, "head")

    # Après interruption : les révisions avant l'étape sont appliquées, l'étape interrompue est annulée.
    versions, tables = _etat()
    assert versions == REVISIONS[:rang][-1:], "Alembic ne garde que la révision courante"
    assert tables == [f"be258_etape_{n}" for n in range(1, rang + 1)]

    # Reprise contrôlée : sans interruption, la base atteint la tête, sans table en double.
    monkeypatch.delenv(VARIABLE_INTERRUPTION)
    command.upgrade(chaine_synthetique, "head")
    versions, tables = _etat()
    assert versions == REVISIONS[-1:]
    assert tables == [f"be258_etape_{n}" for n in range(1, len(REVISIONS) + 1)]

    # Relance à la tête : aucun effet supplémentaire.
    command.upgrade(chaine_synthetique, "head")
    assert _etat() == (REVISIONS[-1:], [f"be258_etape_{n}" for n in range(1, len(REVISIONS) + 1)])
