"""BE-238 : table des tentatives d'envoi des notifications (notification_delivery).

Revision ID: b238d1e2f3a4
Revises: f9d7ef17ec72
Create Date: 2026-11-05

Ajoute `notification_delivery` : une ligne par tentative d'envoi d'une notification
sur un canal, avec le résultat (`envoyee` ou `echec`), le numéro de tentative et
l'horodatage. La contrainte `(notificationId, canal, tentative)` interdit d'écraser
une tentative précédente. Aucune donnée existante n'est modifiée.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b238d1e2f3a4"
down_revision: Union[str, None] = "f9d7ef17ec72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_delivery",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notificationId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canal", sa.String(length=40), nullable=False),
        sa.Column("resultat", sa.String(length=20), nullable=False),
        sa.Column("tentative", sa.Integer(), nullable=False),
        sa.Column("horodatage", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("resultat IN ('envoyee', 'echec')", name="ck_notification_delivery_resultat"),
        sa.CheckConstraint("tentative >= 1", name="ck_notification_delivery_tentative_positive"),
        sa.ForeignKeyConstraint(["notificationId"], ["notification.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notificationId", "canal", "tentative", name="uq_notification_delivery_tentative"),
        comment="Tentatives d'envoi par canal et résultat (BE-238).",
    )
    op.create_index(
        op.f("ix_notification_delivery_notificationId"), "notification_delivery", ["notificationId"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_delivery_notificationId"), table_name="notification_delivery")
    op.drop_table("notification_delivery")
