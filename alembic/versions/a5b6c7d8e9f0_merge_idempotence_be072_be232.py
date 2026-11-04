"""Fusion des deux têtes d'idempotence (BE-072 et BE-232).

Revision ID: a5b6c7d8e9f0
Revises: e072b1c2d3a4, c1d2e3f4a5b6
"""
from typing import Sequence, Union

revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, None] = ("e072b1c2d3a4", "c1d2e3f4a5b6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
