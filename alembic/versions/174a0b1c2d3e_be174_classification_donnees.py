"""BE-174 : classification des champs d'événement et colonne dataClassification de l'outbox.

Crée `classification_champ` (un champ par type d'événement, classification et permissions de
consommation) et ajoute `outbox_evenement.dataClassification`. La colonne est nullable : les
lignes écrites avant cette migration n'ont pas de classification connue, et aucune valeur n'est
inventée pour elles.

Revision ID: 174a0b1c2d3e
Revises: 5e31981cf46c
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "174a0b1c2d3e"
down_revision: Union[str, None] = "5e31981cf46c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CLASSIFICATIONS = ("public", "internal", "confidential", "payment")


def upgrade() -> None:
    op.create_table(
        "classification_champ",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("typeEvenement", sa.String(150), nullable=False),
        sa.Column("champ", sa.String(100), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("consommablePar", sa.JSON(), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "classification IN (" + ", ".join(f"'{c}'" for c in CLASSIFICATIONS) + ")",
            name="ck_classification_champ_classification",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("typeEvenement", "champ", name="uq_classification_champ_type_champ"),
        comment="Classification des champs de payload d'événement et permissions de consommation (BE-174).",
    )
    op.create_index("ix_classification_champ_typeEvenement", "classification_champ", ["typeEvenement"])

    op.add_column("outbox_evenement", sa.Column("dataClassification", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("outbox_evenement", "dataClassification")
    op.drop_index("ix_classification_champ_typeEvenement", table_name="classification_champ")
    op.drop_table("classification_champ")
