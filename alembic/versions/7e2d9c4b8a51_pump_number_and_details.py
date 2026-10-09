"""pump number and details

Revision ID: 7e2d9c4b8a51
Revises: 1c6f436f3b4d
Create Date: 2026-10-01

Scénario A1 (configurer les pompes) : numéro d'ordre par station, marque,
numéro de série et date d'installation (facultatifs), plus unicité du numéro
et du nom par station. Migration écrite à la main (pas d'autogenerate, qui
mêle du bruit de renommage d'index sans rapport).

Reprise des pompes existantes : `pumpNumber` = ROW_NUMBER() par station
(ordre createdAt puis id) ; leur nom est volontairement conservé tel quel
(il ne change qu'à la prochaine modification du numéro/de la cuve). Les
contraintes uniques ne sont créées qu'après le backfill.
"""

from alembic import op
import sqlalchemy as sa

revision = "7e2d9c4b8a51"
down_revision = "1c6f436f3b4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("zyloLiquidPump", sa.Column("pumpNumber", sa.SmallInteger(), nullable=True, comment="Numéro d'ordre de la pompe, unique par station."))
    op.add_column("zyloLiquidPump", sa.Column("brand", sa.String(length=100), nullable=True))
    op.add_column("zyloLiquidPump", sa.Column("serialNumber", sa.String(length=100), nullable=True))
    op.add_column("zyloLiquidPump", sa.Column("installedOn", sa.Date(), nullable=True))

    op.execute(
        """
        UPDATE "zyloLiquidPump" AS p
        SET "pumpNumber" = n.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY "stationId" ORDER BY "createdAt", id) AS rn
            FROM "zyloLiquidPump"
        ) AS n
        WHERE p.id = n.id
        """
    )
    op.alter_column("zyloLiquidPump", "pumpNumber", nullable=False)

    op.create_unique_constraint("uq_zlPump_station_number", "zyloLiquidPump", ["stationId", "pumpNumber"])
    op.create_unique_constraint("uq_zlPump_station_name", "zyloLiquidPump", ["stationId", "name"])


def downgrade() -> None:
    op.drop_constraint("uq_zlPump_station_name", "zyloLiquidPump", type_="unique")
    op.drop_constraint("uq_zlPump_station_number", "zyloLiquidPump", type_="unique")
    op.drop_column("zyloLiquidPump", "installedOn")
    op.drop_column("zyloLiquidPump", "serialNumber")
    op.drop_column("zyloLiquidPump", "brand")
    op.drop_column("zyloLiquidPump", "pumpNumber")
