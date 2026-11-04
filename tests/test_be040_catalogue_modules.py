"""BE-040 : schéma du catalogue de modules et de ses versions.

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-modules-droits.md,
section BE-040) avant le code. Décisions de réutilisation : la table `module` du registre
(BE-021) porte le catalogue (`code` joue le rôle de `slug`, unique), et seule la table
`module_version` est nouvelle.
"""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.modules_registry.models import Module, ModuleVersion

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REVISION_BE040 = "73136cdbf00b"


def _erreur_code(exc: pytest.ExceptionInfo) -> str:
    assert isinstance(exc.value, AppError)
    return exc.value.code


async def _module_de_test(db, code: str) -> Module:
    module = Module(code=code, name=f"Module {code}", description=None, version="0.1.0")
    db.add(module)
    await db.flush()
    return module


def _version_complete(module_id: uuid.UUID, version: str = "1.0.0", **surcharges) -> ModuleVersion:
    valeurs = dict(
        moduleId=module_id,
        version=version,
        digest="sha256:" + "a" * 64,
        provenance="depot-interne/build-42",
        licence="proprietary",
        compatibility={"zylo_office": ">=1.0"},
        prerequisites=[],
        stateVersion=1,
        publishedAt=None,
    )
    valeurs.update(surcharges)
    return ModuleVersion(**valeurs)


async def test_ca1_migration_cree_tables_enums_et_contraintes_d_unicite():
    async with AsyncSessionLocal() as db:
        connexion = await db.connection()

        def inspecter(sync_conn):
            insp = inspect(sync_conn)
            tables = set(insp.get_table_names())
            contraintes_module = insp.get_unique_constraints("module")
            index_module = insp.get_indexes("module")
            contraintes_version = insp.get_unique_constraints("module_version")
            return tables, contraintes_module, index_module, contraintes_version

        tables, uniques_module, index_module, uniques_version = await connexion.run_sync(inspecter)
        enums = (
            await db.execute(text("SELECT typname FROM pg_type WHERE typtype = 'e'"))
        ).scalars().all()
        await db.rollback()

    assert {"module", "module_version"} <= tables
    colonnes_uniques_module = [set(c["column_names"]) for c in uniques_module]
    colonnes_index_module = [set(i["column_names"]) for i in index_module if i.get("unique")]
    assert {"code"} in colonnes_uniques_module + colonnes_index_module
    assert {"moduleId", "version"} in [set(c["column_names"]) for c in uniques_version]
    assert "module_publication_state" in enums
    assert "module_visibility" in enums


async def test_ca2_version_publiee_refuse_la_modification_de_digest_ou_compatibility():
    from app.modules_registry.catalogue import modifier_version, publier_version

    async with AsyncSessionLocal() as db:
        module = await _module_de_test(db, "be040_immuable")
        version = _version_complete(module.id)
        db.add(version)
        await db.flush()
        await publier_version(db, version)

        with pytest.raises(AppError) as exc_digest:
            await modifier_version(db, version, digest="sha256:" + "b" * 64)
        with pytest.raises(AppError) as exc_compat:
            await modifier_version(db, version, compatibility={"zylo_office": ">=2.0"})
        await db.rollback()

    assert _erreur_code(exc_digest) == "MODULE_VERSION_IMMUTABLE"
    assert _erreur_code(exc_compat) == "MODULE_VERSION_IMMUTABLE"


async def test_ca2_version_non_publiee_accepte_la_modification_de_digest():
    from app.modules_registry.catalogue import modifier_version

    async with AsyncSessionLocal() as db:
        module = await _module_de_test(db, "be040_brouillon")
        version = _version_complete(module.id)
        db.add(version)
        await db.flush()
        await modifier_version(db, version, digest="sha256:" + "c" * 64)
        await db.rollback()

    assert version.digest == "sha256:" + "c" * 64


def test_ca3_version_sans_digest_ni_provenance_n_est_pas_publiable():
    from app.modules_registry.catalogue import verifier_publiable

    sans_digest = _version_complete(uuid.uuid4(), digest=None)
    sans_provenance = _version_complete(uuid.uuid4(), provenance=None)
    sans_rien = _version_complete(uuid.uuid4(), digest=None, provenance=None)

    for version in (sans_digest, sans_provenance, sans_rien):
        with pytest.raises(AppError) as exc:
            verifier_publiable(version)
        assert _erreur_code(exc) == "MODULE_VERSION_INCOMPLETE"


def test_ca3_version_avec_digest_et_provenance_est_publiable():
    from app.modules_registry.catalogue import verifier_publiable

    verifier_publiable(_version_complete(uuid.uuid4()))


async def test_ca3_publication_sans_digest_laisse_la_version_non_publiee():
    from app.modules_registry.catalogue import publier_version

    async with AsyncSessionLocal() as db:
        module = await _module_de_test(db, "be040_incomplet")
        version = _version_complete(module.id, digest=None)
        db.add(version)
        await db.flush()
        with pytest.raises(AppError) as exc:
            await publier_version(db, version)
        await db.rollback()

    assert _erreur_code(exc) == "MODULE_VERSION_INCOMPLETE"
    assert version.publishedAt is None


def test_ca4_aller_retour_supprime_puis_recree_les_objets_be040():
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def tables_et_enums() -> tuple[set[str], set[str]]:
        engine = create_async_engine(os.environ["DATABASE_URL"])
        try:
            async with engine.connect() as conn:
                tables = set(
                    (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")))
                    .scalars()
                    .all()
                )
                enums = set(
                    (await conn.execute(text("SELECT typname FROM pg_type WHERE typtype='e'"))).scalars().all()
                )
            return tables, enums
        finally:
            await engine.dispose()

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.downgrade(cfg, REVISION_BE040)
    try:
        tables, enums = asyncio.run(tables_et_enums())
        assert "module_version" not in tables
        assert "module_publication_state" not in enums
    finally:
        command.upgrade(cfg, "head")
    tables, enums = asyncio.run(tables_et_enums())
    assert "module_version" in tables
    assert "module_publication_state" in enums
