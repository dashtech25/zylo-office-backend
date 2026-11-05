"""Tentatives de paiement sur checkout (BE-082) : colonnes ajoutées à `paymentAttempt`.

Revision ID: b082a1c2d3e4
Revises: 934346a13edd
Create Date: 2026-11-05

La table `paymentAttempt` existe déjà (BE-028, rattachée à une facture). BE-082 la réutilise
au lieu d'en créer une seconde : `invoiceId` devient optionnel, et une tentative peut porter
un `checkoutId`. Ajouts : `checkoutId`, `installmentRef`, `version` (verrou optimiste, BE-072),
`submittedAt`. Aucune colonne de donnée de carte (CA-5).

Downgrade : les tentatives de checkout (sans facture) ne peuvent pas survivre à la remise
en `NOT NULL` de `invoiceId`, elles sont donc supprimées avant. Ce downgrade détruit ces lignes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b082a1c2d3e4"
down_revision: Union[str, None] = "934346a13edd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("paymentAttempt", "invoiceId", existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("paymentAttempt", sa.Column("checkoutId", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True,
                                              comment="Checkout soumis (BE-082) ; NULL pour une tentative de facture."))
    op.create_foreign_key("fk_paymentAttempt_checkoutId", "paymentAttempt", "checkout", ["checkoutId"], ["id"])
    op.create_index("ix_paymentAttempt_checkoutId", "paymentAttempt", ["checkoutId"])
    op.add_column("paymentAttempt", sa.Column("installmentRef", sa.String(length=80), nullable=True,
                                              comment="Référence de l'échéance payée (NON DÉFINI, QE-FAC-04)."))
    op.add_column("paymentAttempt", sa.Column("version", sa.Integer(), nullable=False, server_default="1",
                                              comment="Verrou optimiste (BE-072)."))
    op.add_column("paymentAttempt", sa.Column("submittedAt", sa.DateTime(timezone=True), nullable=True,
                                              comment="Instant de l'appel au fournisseur (état `submitted`)."))


def downgrade() -> None:
    op.execute('DELETE FROM "paymentAttempt" WHERE "invoiceId" IS NULL')
    op.drop_column("paymentAttempt", "submittedAt")
    op.drop_column("paymentAttempt", "version")
    op.drop_column("paymentAttempt", "installmentRef")
    op.drop_index("ix_paymentAttempt_checkoutId", table_name="paymentAttempt")
    op.drop_constraint("fk_paymentAttempt_checkoutId", "paymentAttempt", type_="foreignkey")
    op.drop_column("paymentAttempt", "checkoutId")
    op.alter_column("paymentAttempt", "invoiceId", existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=False)
