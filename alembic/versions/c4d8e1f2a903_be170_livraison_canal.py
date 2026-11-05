"""BE-170 : table `livraison` de l'adaptateur de canal

Revision ID: c4d8e1f2a903
Revises: 7c0052761f05
Create Date: 2026-11-05 13:00:00.000000

Crée `livraison` : une ligne par tentative de remise d'une notification à un canal
(app/notifications/canal.py). Unicité de `(notificationId, tentativeNo)`, CHECK sur le
résultat et sur le numéro de tentative. Aucune colonne destinataire (CA-4). Le canal
reste un nom opaque sans liste de valeurs (QE-PAR-04). Downgrade : suppression de la table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4d8e1f2a903"
down_revision: Union[str, None] = "7c0052761f05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "livraison",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("notificationId", sa.UUID(), nullable=False),
        sa.Column("canal", sa.String(length=40), nullable=False),
        sa.Column("tentativeNo", sa.Integer(), nullable=False),
        sa.Column("resultat", sa.String(length=20), nullable=False),
        sa.Column("codeErreur", sa.String(length=80), nullable=True),
        sa.Column("prochaineTentativeAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creeAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "resultat IN ('accepte', 'livre', 'retarde', 'rebond', 'plainte', 'echec')",
            name="ck_livraison_resultat",
        ),
        sa.CheckConstraint('"tentativeNo" >= 1', name="ck_livraison_tentative_positive"),
        sa.ForeignKeyConstraint(["notificationId"], ["notification.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notificationId", "tentativeNo", name="uq_livraison_notification_tentative"),
        comment="Tentatives de livraison d'une notification par canal (BE-170), sans donnée destinataire.",
    )
    op.create_index(op.f("ix_livraison_notificationId"), "livraison", ["notificationId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_livraison_notificationId"), table_name="livraison")
    op.drop_table("livraison")
