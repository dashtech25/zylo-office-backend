"""Table des compensations de mutations passées (BE-252).

Objectif : annuler l'effet d'une mutation asynchrone déjà produite (défaut injecté après
coup) sans réécrire l'historique, avec une clé d'idempotence unique pour qu'une reprise
ne crée ni doublon de compensation ni second effet.

Réversibilité : oui. Le downgrade supprime la table entière ; il est destructif pour
l'historique des compensations, à n'exécuter qu'avec le marqueur de confirmation habituel.
Migration additive : aucune table existante n'est modifiée.

Revision ID: b252c3d4e5f6
Revises: f6bf39c21bf7
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b252c3d4e5f6"
down_revision: Union[str, None] = "f6bf39c21bf7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compensations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("operation_origine", sa.String(length=255), nullable=False),
        sa.Column("action_compensation", sa.String(length=64), nullable=False),
        sa.Column("etat", sa.String(length=16), nullable=False),
        sa.Column("cle_idempotence", sa.String(length=128), nullable=False),
        sa.Column("demandeur_id", sa.UUID(), nullable=False),
        sa.Column("approbateur_id", sa.UUID(), nullable=False),
        sa.Column("demandee_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("realisee_le", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cle_idempotence", name="uq_compensations_cle_idempotence"),
        comment="Compensations de mutations passées : opération d'origine, action, état et idempotence.",
    )
    op.create_index(op.f("ix_compensations_operation_origine"), "compensations", ["operation_origine"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_compensations_operation_origine"), table_name="compensations")
    op.drop_table("compensations")
