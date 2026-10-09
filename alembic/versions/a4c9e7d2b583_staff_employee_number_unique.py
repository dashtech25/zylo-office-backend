"""staff employee number unique per station

Revision ID: a4c9e7d2b583
Revises: 5b8d3f1a6c24
Create Date: 2026-10-01

Scénario A4 (personnel et rôles), décision D14 : le N° d'employé est unique
par station d'affectation SI renseigné. Index unique PARTIEL (les fiches sans
numéro ne se bloquent pas entre elles). Migration écrite à la main ; aucune
donnée n'est modifiée (si des doublons existent déjà, la création de l'index
échoue volontairement : à arbitrer par un humain, jamais corrigé en silence).
"""

from alembic import op
import sqlalchemy as sa

revision = "a4c9e7d2b583"
down_revision = "5b8d3f1a6c24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_zlStationStaffProfile_station_employeeNumber",
        "zyloLiquidStationStaffProfile",
        ["assignedStationId", "employeeNumber"],
        unique=True,
        postgresql_where=sa.text('"employeeNumber" IS NOT NULL AND "assignedStationId" IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index("uq_zlStationStaffProfile_station_employeeNumber", table_name="zyloLiquidStationStaffProfile")
