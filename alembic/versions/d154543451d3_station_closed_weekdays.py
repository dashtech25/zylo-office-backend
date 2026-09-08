"""station closed weekdays

Ajoute `zyloLiquidStation.closedWeekdays` (CSV de jours ISO 1=lundi..7=dimanche,
NULL = ouvert tous les jours) — mission « amélioration zylo liquid »,
page de station.docx : « jour d'ouverture pour chaque [station] permet une
configuration de station ». Colonne additive nullable, non destructive : les
lignes existantes restent valides sans migration de données.

Revision ID: d154543451d3
Revises: f7a8b9c0d1e2
Create Date: 2026-09-08 07:49:40.638669

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd154543451d3'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('zyloLiquidStation', sa.Column('closedWeekdays', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('zyloLiquidStation', 'closedWeekdays')
