"""BE-237 : registre des réglages et historique des modifications.

Revision ID: a237b1c0d9e8
Revises: 290f30a9bcbf
Create Date: 2026-11-05

Crée `settings_registry` (déclarations) et `settings_history` (modifications). Les CHECK
ferment la portée, le propriétaire, l'effet et le motif. Downgrade : suppression des deux
tables, historique compris ; à n'exécuter qu'en base de test ou après sauvegarde.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a237b1c0d9e8"
down_revision: Union[str, None] = "290f30a9bcbf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PORTEES = "'platform', 'tenant', 'membership', 'workspace'"


def upgrade() -> None:
    op.create_table(
        "settings_registry",
        sa.Column("key", sa.String(length=150), nullable=False),
        sa.Column("scopeKind", sa.String(length=20), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("secret", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("effect", sa.String(length=40), nullable=False),
        sa.Column("effectiveAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("defaultValue", sa.JSON(), nullable=True),
        sa.CheckConstraint(f'"scopeKind" IN ({_PORTEES})', name="ck_settings_registry_scopeKind"),
        sa.CheckConstraint("length(btrim(owner)) > 0", name="ck_settings_registry_owner_non_vide"),
        sa.CheckConstraint("length(btrim(effect)) > 0", name="ck_settings_registry_effect_non_vide"),
        sa.CheckConstraint("length(btrim(key)) > 0", name="ck_settings_registry_key_non_vide"),
        sa.PrimaryKeyConstraint("key"),
        comment="Registre des réglages : clé, propriétaire, portée, sensibilité, effet et défaut.",
    )
    op.create_table(
        "settings_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("settingKey", sa.String(length=150), nullable=False),
        sa.Column("scopeKind", sa.String(length=20), nullable=False),
        sa.Column("scopeId", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("oldValue", sa.JSON(), nullable=True),
        sa.Column("newValue", sa.JSON(), nullable=True),
        sa.Column("actorId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_settings_history_reason_non_vide"),
        sa.ForeignKeyConstraint(["settingKey"], ["settings_registry.key"]),
        sa.ForeignKeyConstraint(["actorId"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="Historique des modifications des réglages : ancienne et nouvelle valeur, acteur, motif.",
    )
    op.create_index("ix_settings_history_settingKey", "settings_history", ["settingKey"])
    op.create_index("ix_settings_history_scopeId", "settings_history", ["scopeId"])
    op.create_index("ix_settings_history_actorId", "settings_history", ["actorId"])


def downgrade() -> None:
    op.drop_index("ix_settings_history_actorId", table_name="settings_history")
    op.drop_index("ix_settings_history_scopeId", table_name="settings_history")
    op.drop_index("ix_settings_history_settingKey", table_name="settings_history")
    op.drop_table("settings_history")
    op.drop_table("settings_registry")
