"""Ajoute la colonne de version de l'organisation (BE-233).

Revision ID: c7ecfe8a11be
Revises: b7c8d9e0f123
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7ecfe8a11be"
down_revision: Union[str, None] = "b7c8d9e0f123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Les lignes existantes reçoivent la version 1 (VERSION_INITIALE de app/core/versioning.py).
    op.add_column(
        "organization",
        sa.Column(
            "version",
            sa.Integer(),
            server_default="1",
            nullable=False,
            comment="Version de l'agrégat (BE-233) ; incrémentée à chaque mutation, verrou de conflit.",
        ),
    )


def downgrade() -> None:
    op.drop_column("organization", "version")
