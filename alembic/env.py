import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.core.config import settings
from app.core.database import Base

# Chaque module (socle ou futur) doit importer ses modèles ici pour que
# `alembic revision --autogenerate` les détecte — l'import seul suffit, aucun
# appel de code n'est nécessaire, l'enregistrement se fait via Base.metadata.
from app.alerts import models as alerts_models  # noqa: F401
from app.audit import models as audit_models  # noqa: F401
from app.auth import models as auth_models  # noqa: F401
from app.billing import models as billing_models  # noqa: F401
from app.files import models as files_models  # noqa: F401
from app.identity import models as identity_models  # noqa: F401
from app.location import models as location_models  # noqa: F401
from app.modules.zylo_liquid import models as zylo_liquid_models  # noqa: F401
from app.modules.zylo_tanker import models as zylo_tanker_models  # noqa: F401
from app.modules_registry import models as modules_registry_models  # noqa: F401
from app.rbac import models as rbac_models  # noqa: F401
from app.shared import geo as shared_geo_models  # noqa: F401
from app.shared import currency as shared_currency_models  # noqa: F401

# Généralisation Zylo Tanker (2026-09-16) — `app.alerts`/`app.files`/
# `app.location`/`app.modules.zylo_tanker` manquaient ici (gap pré-existant,
# probablement laissé par l'extraction Files/Location/Alertes hors de
# zylo_liquid.models — Phases 1-3 de la migration monolithe modulaire,
# voir ARCHITECTURE.md) : sans l'import de leurs modèles, `target_metadata`
# ne les connaît pas et `alembic revision --autogenerate` échoue en triant
# les tables par dépendances de FK (`NoReferencedTableError` sur
# `zyloLiquidAlert`, constaté en générant la migration de ce chantier) —
# ou pire, verrait ces tables comme "en trop" et proposerait de les
# supprimer. Corrigé ici une bonne fois : tout futur module devra faire de
# même (voir le commentaire au-dessus de `target_metadata`).

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# URL de connexion pilotée par la config applicative (.env), jamais codée en
# dur dans alembic.ini — la même variable DATABASE_URL sert en local et une
# fois déployé.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Toutes les tables des modules socle/futurs déclarent leurs modèles sur cette
# même Base : autogenerate détecte donc automatiquement les nouvelles tables
# dès qu'un module importe ses modèles ici.
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
