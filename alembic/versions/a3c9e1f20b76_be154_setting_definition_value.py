"""BE-154 : tables des paramètres `setting_definition` et `setting_value`.

Revision ID: a3c9e1f20b76
Revises: 12a5bb79f642

Crée les déclarations de paramètres (`setting_definition`) et leurs valeurs
versionnées par portée (`setting_value`), avec l'unicité
`(definitionKey, scopeKind, scopeId, version)`, les CHECK de portée, de version et de
raison non vide, et la clé étrangère `createdBy` vers `user`.

Downgrade : supprime `setting_value` puis `setting_definition`. Les tables ne
contiennent aucune donnée antérieure à cette migration, la perte est donc nulle
au retour arrière.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3c9e1f20b76"
down_revision: Union[str, None] = "12a5bb79f642"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PORTEES = "'plateforme', 'organisation', 'module', 'utilisateur'"


def upgrade() -> None:
    op.create_table(
        "setting_definition",
        sa.Column("key", sa.String(length=150), nullable=False),
        sa.Column("scopeKind", sa.String(length=20), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("valueType", sa.String(length=40), nullable=False),
        sa.Column("defaultValue", sa.JSON(), nullable=True),
        sa.Column("sensitive", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(f'"scopeKind" IN ({_PORTEES})', name="ck_setting_definition_scopeKind"),
        sa.CheckConstraint("length(btrim(key)) > 0", name="ck_setting_definition_key_non_vide"),
        sa.PrimaryKeyConstraint("key"),
        comment="Déclaration des paramètres : clé, portée, type, défaut et sensibilité.",
    )

    op.create_table(
        "setting_value",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("definitionKey", sa.String(length=150), nullable=False),
        sa.Column("scopeKind", sa.String(length=20), nullable=False),
        sa.Column("scopeId", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("applied", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("createdBy", sa.UUID(), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.CheckConstraint(f'"scopeKind" IN ({_PORTEES})', name="ck_setting_value_scopeKind"),
        sa.CheckConstraint("version >= 1", name="ck_setting_value_version_positive"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_setting_value_reason_non_vide"),
        sa.ForeignKeyConstraint(["definitionKey"], ["setting_definition.key"]),
        sa.ForeignKeyConstraint(["createdBy"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "definitionKey", "scopeKind", "scopeId", "version",
            name="uq_setting_value_definitionKey_scopeKind_scopeId_version",
        ),
        comment="Valeurs versionnées des paramètres par portée ; une ligne par version écrite.",
    )
    op.create_index("ix_setting_value_definitionKey", "setting_value", ["definitionKey"])
    op.create_index("ix_setting_value_scopeId", "setting_value", ["scopeId"])
    op.create_index("ix_setting_value_createdBy", "setting_value", ["createdBy"])


def downgrade() -> None:
    op.drop_index("ix_setting_value_createdBy", table_name="setting_value")
    op.drop_index("ix_setting_value_scopeId", table_name="setting_value")
    op.drop_index("ix_setting_value_definitionKey", table_name="setting_value")
    op.drop_table("setting_value")
    op.drop_table("setting_definition")
