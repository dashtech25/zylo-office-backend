"""alert lifecycle and source refonte

Revision ID: b7c4e9f21a03
Revises: 69a55c682c0a
Create Date: 2026-09-11

Refonte alertes Étape 2 (décisions D2/D3/D4, voir chat) :
- `stationId` (NOT NULL, backfillé depuis `tankId` -> `Tank.stationId`
  pour les lignes existantes), `tankId` devient nullable (types sans cuve,
  ex. `price_missing`), `productId` nullable (nouveau).
- `severity` (NOT NULL, backfillée depuis `type` — mapping ci-dessous,
  reprend exactement la logique `CRITICAL_TYPES` qui vivait côté frontend
  avant cette refonte).
- `sourceType`/`sourceId` (référence logique, jamais une FK stricte —
  polymorphe par nature).
- Cycle de vie à 3 états : `status` CHECK étendu avec `acknowledged`,
  `acknowledgedAt`/`acknowledgedByUserId` (nouveaux, nullable),
  `resolvedByUserId`/`resolutionMethod` (nouveaux, nullable — les lignes
  déjà résolues sont rétroactivement marquées `manual_justified`, seule
  méthode qui existait avant cette refonte ; `resolvedByUserId` reste NULL,
  inconnu historiquement, jamais inventé).
- `type` CHECK étendu avec 3 nouveaux types (`price_missing`,
  `sensor_mapping_missing`, `calibration_missing`).

Écrite à la main (comme 69a55c682c0a) — `alembic revision --autogenerate`
mêle un bruit de renommage d'index préexistant sans rapport.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b7c4e9f21a03"
down_revision = "69a55c682c0a"
branch_labels = None
depends_on = None

SEVERITY_BY_TYPE = {
    "level_high": "critical",
    "leak": "critical",
    "delivery_discrepancy": "critical",
    "delivery_undeclared": "critical",
    "level_high_pre_alarm": "high",
    "level_low": "high",
    "water": "high",
    "sensor_offline": "medium",
    "delivery_declaration_pending": "low",
}


def upgrade() -> None:
    # --- Colonnes additives (nullable dans un premier temps pour permettre le backfill) ---
    op.add_column("zyloLiquidAlert", sa.Column("stationId", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("zyloLiquidAlert", sa.Column("productId", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("zyloLiquidAlert", sa.Column("severity", sa.String(10), nullable=True))
    op.add_column("zyloLiquidAlert", sa.Column("sourceType", sa.String(40), nullable=True))
    op.add_column("zyloLiquidAlert", sa.Column("sourceId", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("zyloLiquidAlert", sa.Column("acknowledgedAt", sa.DateTime(), nullable=True))
    op.add_column("zyloLiquidAlert", sa.Column("acknowledgedByUserId", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("zyloLiquidAlert", sa.Column("resolvedByUserId", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("zyloLiquidAlert", sa.Column("resolutionMethod", sa.String(20), nullable=True))

    # --- Backfill stationId depuis Tank.stationId (toutes les lignes existantes ont un tankId) ---
    op.execute(
        'UPDATE "zyloLiquidAlert" a SET "stationId" = t."stationId" '
        'FROM "zyloLiquidTank" t WHERE t.id = a."tankId"'
    )

    # --- Backfill severity depuis type (reprend CRITICAL_TYPES du frontend, plus de duplication) ---
    for alert_type, severity in SEVERITY_BY_TYPE.items():
        op.execute(
            f"UPDATE \"zyloLiquidAlert\" SET severity = '{severity}' WHERE type = '{alert_type}' AND severity IS NULL"
        )
    # Filet de sécurité si un type imprévu existait déjà (jamais laisser NULL) :
    op.execute("UPDATE \"zyloLiquidAlert\" SET severity = 'medium' WHERE severity IS NULL")

    # --- Backfill resolutionMethod : toute alerte déjà résolue l'a été par un clic
    # déclaratif (seule méthode qui existait avant cette refonte) ---
    op.execute(
        "UPDATE \"zyloLiquidAlert\" SET \"resolutionMethod\" = 'manual_justified' WHERE status = 'resolved'"
    )

    # --- Contraintes NOT NULL une fois le backfill fait ---
    op.alter_column("zyloLiquidAlert", "stationId", nullable=False)
    op.alter_column("zyloLiquidAlert", "severity", nullable=False)
    op.alter_column("zyloLiquidAlert", "tankId", nullable=True)

    # --- FK ---
    op.create_foreign_key(
        "zyloLiquidAlert_stationId_fkey", "zyloLiquidAlert", "zyloLiquidStation",
        ["stationId"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "zyloLiquidAlert_productId_fkey", "zyloLiquidAlert", "zyloLiquidFuelProduct",
        ["productId"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "zyloLiquidAlert_acknowledgedByUserId_fkey", "zyloLiquidAlert", "user",
        ["acknowledgedByUserId"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "zyloLiquidAlert_resolvedByUserId_fkey", "zyloLiquidAlert", "user",
        ["resolvedByUserId"], ["id"], ondelete="SET NULL",
    )

    # --- Index ---
    op.create_index("ix_zyloLiquidAlert_stationId", "zyloLiquidAlert", ["stationId"])
    op.create_index("ix_zyloLiquidAlert_productId", "zyloLiquidAlert", ["productId"])
    op.create_index("ix_zyloLiquidAlert_severity", "zyloLiquidAlert", ["severity"])

    # --- CHECK constraints : drop + recreate avec les nouvelles valeurs ---
    op.drop_constraint("ck_zlAlert_type", "zyloLiquidAlert", type_="check")
    op.create_check_constraint(
        "ck_zlAlert_type", "zyloLiquidAlert",
        "type IN ('level_high','level_high_pre_alarm','level_low','water','leak','sensor_offline',"
        "'delivery_discrepancy','delivery_undeclared','delivery_declaration_pending',"
        "'price_missing','sensor_mapping_missing','calibration_missing')",
    )
    op.drop_constraint("ck_zlAlert_status", "zyloLiquidAlert", type_="check")
    op.create_check_constraint(
        "ck_zlAlert_status", "zyloLiquidAlert", "status IN ('active','acknowledged','resolved')",
    )
    op.create_check_constraint(
        "ck_zlAlert_severity", "zyloLiquidAlert", "severity IN ('critical','high','medium','low')",
    )
    op.create_check_constraint(
        "ck_zlAlert_resolutionMethod", "zyloLiquidAlert",
        "\"resolutionMethod\" IS NULL OR \"resolutionMethod\" IN ('auto_verified','manual_justified')",
    )
    # status='acknowledged' impliquait status jusqu'ici NOT NULL(10) — la colonne
    # elle-même passe à VARCHAR(12) pour porter "acknowledged" (12 caractères).
    op.alter_column("zyloLiquidAlert", "status", type_=sa.String(12), existing_type=sa.String(10))


def downgrade() -> None:
    op.drop_constraint("ck_zlAlert_resolutionMethod", "zyloLiquidAlert", type_="check")
    op.drop_constraint("ck_zlAlert_severity", "zyloLiquidAlert", type_="check")
    op.drop_constraint("ck_zlAlert_status", "zyloLiquidAlert", type_="check")
    op.create_check_constraint("ck_zlAlert_status", "zyloLiquidAlert", "status IN ('active','resolved')")
    op.drop_constraint("ck_zlAlert_type", "zyloLiquidAlert", type_="check")
    op.create_check_constraint(
        "ck_zlAlert_type", "zyloLiquidAlert",
        "type IN ('level_high','level_high_pre_alarm','level_low','water','leak','sensor_offline',"
        "'delivery_discrepancy','delivery_undeclared','delivery_declaration_pending')",
    )
    op.alter_column("zyloLiquidAlert", "status", type_=sa.String(10), existing_type=sa.String(12))

    op.drop_index("ix_zyloLiquidAlert_severity", table_name="zyloLiquidAlert")
    op.drop_index("ix_zyloLiquidAlert_productId", table_name="zyloLiquidAlert")
    op.drop_index("ix_zyloLiquidAlert_stationId", table_name="zyloLiquidAlert")

    op.drop_constraint("zyloLiquidAlert_resolvedByUserId_fkey", "zyloLiquidAlert", type_="foreignkey")
    op.drop_constraint("zyloLiquidAlert_acknowledgedByUserId_fkey", "zyloLiquidAlert", type_="foreignkey")
    op.drop_constraint("zyloLiquidAlert_productId_fkey", "zyloLiquidAlert", type_="foreignkey")
    op.drop_constraint("zyloLiquidAlert_stationId_fkey", "zyloLiquidAlert", type_="foreignkey")

    op.alter_column("zyloLiquidAlert", "tankId", nullable=False)

    op.drop_column("zyloLiquidAlert", "resolutionMethod")
    op.drop_column("zyloLiquidAlert", "resolvedByUserId")
    op.drop_column("zyloLiquidAlert", "acknowledgedByUserId")
    op.drop_column("zyloLiquidAlert", "acknowledgedAt")
    op.drop_column("zyloLiquidAlert", "sourceId")
    op.drop_column("zyloLiquidAlert", "sourceType")
    op.drop_column("zyloLiquidAlert", "severity")
    op.drop_column("zyloLiquidAlert", "productId")
    op.drop_column("zyloLiquidAlert", "stationId")
