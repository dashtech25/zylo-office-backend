"""BE-231 : table des versions de clés de chiffrement (matériel enveloppé uniquement).

Revision ID: be231a1b2c3d
Revises: 169de7fb56af
Create Date: 2026-11-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "be231a1b2c3d"
down_revision: Union[str, None] = "169de7fb56af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "encryption_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, comment="Identifiant UUID généré côté application."),
        sa.Column("version", sa.Integer(), nullable=False, unique=True, comment="Numéro de version N référencé par les valeurs chiffrées."),
        sa.Column("statut", sa.String(length=20), nullable=False, comment="active, retiree ou revoquee."),
        sa.Column("wrappedKey", sa.Text(), nullable=True, comment="Clé de données enveloppée par la clé maître ; NULL une fois révoquée."),
        sa.Column("createdAt", sa.DateTime(timezone=True), nullable=False, comment="Date de création de la version."),
        sa.Column("retiredAt", sa.DateTime(timezone=True), nullable=True, comment="Date de passage en retiree."),
        sa.Column("revokedAt", sa.DateTime(timezone=True), nullable=True, comment="Date de révocation."),
        sa.CheckConstraint("statut IN ('active', 'retiree', 'revoquee')", name="ck_encryption_keys_statut"),
        comment="Versions des clés de données (BE-231) : seule la forme enveloppée par la clé maître est stockée.",
    )
    # Invariant : une seule version courante à la fois.
    op.create_index(
        "uq_encryption_keys_une_active",
        "encryption_keys",
        ["statut"],
        unique=True,
        postgresql_where=sa.text("statut = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_encryption_keys_une_active", table_name="encryption_keys")
    op.drop_table("encryption_keys")
