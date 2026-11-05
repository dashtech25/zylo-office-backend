"""BE-169 : table `notification` du moteur de notification

Revision ID: 9a4f1c6d2e75
Revises: 290f30a9bcbf
Create Date: 2026-11-05 12:00:00.000000

Crée `notification` : une ligne par (événement d'origine, catégorie, destinataire),
produite par le moteur (app/notifications/moteur.py). Unicité sur ce triplet (CA-4) ;
contrainte CHECK sur le statut et cohérence entre `statut = supprimee` et
`motifSuppression` renseigné. Downgrade : suppression de la table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9a4f1c6d2e75"
down_revision: Union[str, None] = "290f30a9bcbf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("eventId", sa.UUID(), nullable=False),
        sa.Column("categorieCode", sa.String(length=80), nullable=False),
        sa.Column("destinataireId", sa.UUID(), nullable=False),
        sa.Column("statut", sa.String(length=20), nullable=False),
        sa.Column("motifSuppression", sa.String(length=80), nullable=True),
        sa.Column("creeAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("statut IN ('en_attente', 'supprimee', 'envoyee', 'echec')", name="ck_notification_statut"),
        sa.CheckConstraint(
            "(statut = 'supprimee') = (\"motifSuppression\" IS NOT NULL)",
            name="ck_notification_motif_suppression",
        ),
        sa.ForeignKeyConstraint(["categorieCode"], ["categorie_notification.code"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["destinataireId"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("eventId", "categorieCode", "destinataireId", name="uq_notification_event_categorie_destinataire"),
        comment="Notification produite par le moteur (BE-169) : audience résolue à l'envoi, déduplication par événement.",
    )
    op.create_index(op.f("ix_notification_eventId"), "notification", ["eventId"], unique=False)
    op.create_index(op.f("ix_notification_destinataireId"), "notification", ["destinataireId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_destinataireId"), table_name="notification")
    op.drop_index(op.f("ix_notification_eventId"), table_name="notification")
    op.drop_table("notification")
