"""table price_rule : prix, devise et taxe par tenant, objet et scénario (BE-078)

Revision ID: c078a1b2d3e4
Revises: 169de7fb56af
Create Date: 2026-11-04

Migration additive. Crée la table `price_rule` : id, organizationId, objectCode,
scenario, amountMinor, currency, taxRateBps, createdAt, updatedAt. Les trois
valeurs financières sont NULLABLE : aucune règle n'est insérée, et une règle
partielle bloque la résolution (CA-1 de BE-078). Aucune donnée existante n'est
modifiée.

Retour arrière : suppression de la table. Les règles saisies sont perdues ; elles
ne sont pas recalculables, car elles viennent d'une saisie de la finance.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c078a1b2d3e4"
down_revision: Union[str, None] = "169de7fb56af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "price_rule",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", sa.UUID(as_uuid=True), nullable=False,
                  comment="Tenant propriétaire de la règle."),
        sa.Column("objectCode", sa.String(length=100), nullable=False,
                  comment="Code de l'offre tarifée."),
        sa.Column("scenario", sa.String(length=50), nullable=False,
                  comment="Scénario de tarification (valeurs NON DÉFINI, QE-FAC-10)."),
        sa.Column("amountMinor", sa.BigInteger(), nullable=True,
                  comment="Montant en unités mineures ; NULL = non configuré."),
        sa.Column("currency", sa.String(length=3), nullable=True,
                  comment="Devise ISO ; NULL = non configurée."),
        sa.Column("taxRateBps", sa.Integer(), nullable=True,
                  comment="Taux de taxe en points de base ; NULL = non configuré."),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organizationId"], ["organization.id"]),
        sa.ForeignKeyConstraint(["objectCode"], ["plan.code"]),
        sa.UniqueConstraint("organizationId", "objectCode", "scenario", name="uq_price_rule_org_objet_scenario"),
        comment="Règle de prix, devise et taxe par tenant, objet et scénario (BE-078). Valeurs non définies.",
    )
    op.create_index("ix_price_rule_organizationId", "price_rule", ["organizationId"])


def downgrade() -> None:
    op.drop_index("ix_price_rule_organizationId", table_name="price_rule")
    op.drop_table("price_rule")
