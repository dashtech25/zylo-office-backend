"""BE-168 : préférences et consentement par catégorie de notification

Revision ID: 8e5a2c1d9f3b
Revises: 7b3cdbc1efc8
Create Date: 2026-11-05 12:00:00.000000

Crée `preference_notification` : consentement d'un utilisateur à une catégorie, avec
horodatage et origine de la décision. Unicité (utilisateurId, categorieCode). Pas de
colonne `canal` (QE-PAR-04) ni de plage de silence (CA-4). Downgrade : suppression de
la table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "8e5a2c1d9f3b"
down_revision: Union[str, None] = "7b3cdbc1efc8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "preference_notification",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("utilisateurId", sa.UUID(), nullable=False),
        sa.Column("categorieCode", sa.String(length=80), nullable=False),
        sa.Column("consentement", sa.Boolean(), nullable=False),
        sa.Column("horodatageConsentement", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sourceConsentement", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["utilisateurId"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["categorieCode"], ["categorie_notification.code"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("utilisateurId", "categorieCode", name="uq_preference_notification_utilisateur_categorie"),
        comment="Consentement par utilisateur et catégorie de notification (BE-168).",
    )
    op.create_index(
        op.f("ix_preference_notification_utilisateurId"), "preference_notification", ["utilisateurId"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_preference_notification_utilisateurId"), table_name="preference_notification")
    op.drop_table("preference_notification")
