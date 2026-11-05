"""BE-159 : table `approbation_parametre` des demandes de changement de paramètres sensibles.

Revision ID: 159b5e0a7c31
Revises: 7c0052761f05

Crée la table des demandes d'approbation : une ligne par demande de changement d'un paramètre
sensible, avec le demandeur, l'approbateur (nul tant que la demande est en attente), le statut
parmi `en_attente`, `approuvé`, `rejeté`, la raison de la demande et les dates de création et de
décision. Le CHECK sur le statut, la clé étrangère vers `setting_definition` et les deux clés
étrangères vers `user` sont portés par la base.

Downgrade : supprime la table. Elle ne contient aucune donnée antérieure à cette migration.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "159b5e0a7c31"
down_revision: Union[str, None] = "7c0052761f05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUTS = "'en_attente', 'approuvé', 'rejeté'"


def upgrade() -> None:
    op.create_table(
        "approbation_parametre",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("settingKey", sa.String(length=150), nullable=False),
        sa.Column("scopeKind", sa.String(length=20), nullable=False),
        sa.Column("scopeId", sa.UUID(), nullable=False),
        sa.Column("valeurProposee", sa.JSON(), nullable=False),
        sa.Column("demandeur", sa.UUID(), nullable=False),
        sa.Column("approbateur", sa.UUID(), nullable=True),
        sa.Column("statut", sa.String(length=20), server_default="en_attente", nullable=False),
        sa.Column("motif", sa.String(length=500), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decidedAt", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"statut IN ({_STATUTS})", name="ck_approbation_parametre_statut"),
        sa.CheckConstraint("length(btrim(motif)) > 0", name="ck_approbation_parametre_motif_non_vide"),
        sa.ForeignKeyConstraint(["settingKey"], ["setting_definition.key"]),
        sa.ForeignKeyConstraint(["demandeur"], ["user.id"]),
        sa.ForeignKeyConstraint(["approbateur"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="Demandes d'approbation des changements de paramètres sensibles (BE-159).",
    )
    op.create_index("ix_approbation_parametre_scopeId", "approbation_parametre", ["scopeId"])


def downgrade() -> None:
    op.drop_index("ix_approbation_parametre_scopeId", table_name="approbation_parametre")
    op.drop_table("approbation_parametre")
