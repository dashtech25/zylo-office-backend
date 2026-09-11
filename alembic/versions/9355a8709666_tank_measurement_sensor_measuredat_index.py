"""tank measurement sensor measuredAt index

Revision ID: 9355a8709666
Revises: 00e30f42d09d
Create Date: 2026-09-11

Ajoute l'index composite manquant `(hkSensorId, measuredAt DESC)` sur
`zyloLiquidTankMeasurement` (Phase 1 — audit performance, `docs/architecture/
performance/phase-1-audit.md`, problème #5). Preuve : `EXPLAIN ANALYZE` sur
le pattern de requête `_measurement_at_or_before` (service.py ~L2441,
`WHERE hkSensorId IN (...) AND measuredAt <= X ORDER BY measuredAt DESC
LIMIT 1`) montrait un balayage quasi complet de la table (index measuredAt
seul, hkSensorId filtré après coup : Rows Removed by Filter proche du
total). Écrit à la main comme les migrations précédentes de cette mission
(autogenerate mêle un bruit de renommage d'index sans rapport). Additif
seul, aucune table existante modifiée hors ajout d'index.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '9355a8709666'
down_revision: Union[str, None] = '00e30f42d09d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_zyloLiquidTankMeasurement_hkSensorId_measuredAt',
        'zyloLiquidTankMeasurement',
        ['hkSensorId', sa.text('"measuredAt" DESC')],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_zyloLiquidTankMeasurement_hkSensorId_measuredAt',
        table_name='zyloLiquidTankMeasurement',
    )
