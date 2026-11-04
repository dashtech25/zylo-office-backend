"""BE-076 : table consent_record (consentements versionnés, append-only)

Revision ID: c076a1b2c3d4
Revises: 169de7fb56af
Create Date: 2026-11-04

Crée `consent_record` : une ligne par consentement ou correction (`correctionOfId`).
Un trigger PostgreSQL BEFORE UPDATE OR DELETE refuse toute modification de ligne : la
preuve d'un consentement ne peut plus être réécrite ni effacée, même par SQL direct
(CA-2 de BE-076). Les colonnes sont en camelCase, la table en snake_case (décision
du propriétaire).

Downgrade : retire le trigger, sa fonction, puis la table.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c076a1b2c3d4"
down_revision: Union[str, None] = "169de7fb56af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "consent_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False,
                  comment="Identifiant du consentement."),
        sa.Column("personId", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False,
                  comment="Personne qui consent."),
        sa.Column("accountId", postgresql.UUID(as_uuid=True), sa.ForeignKey("billing_payer.id"), nullable=False,
                  comment="Compte payeur concerné."),
        sa.Column("consentTextVersion", sa.String(length=64), nullable=False,
                  comment="Identifiant de version du texte accepté."),
        sa.Column("scope", sa.String(length=30), nullable=False,
                  comment="Périmètre du consentement (payeur, tenant, beneficiaire)."),
        sa.Column("recordedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False,
                  comment="Heure d'enregistrement serveur."),
        sa.Column("correctionOfId", postgresql.UUID(as_uuid=True), sa.ForeignKey("consent_record.id"), nullable=True,
                  comment="Entrée d'origine corrigée, nulle hors correction."),
        comment="Consentement versionné d'une personne pour un compte payeur, append-only (BE-076).",
    )
    op.create_index("ix_consent_record_personId", "consent_record", ["personId"])
    op.create_index("ix_consent_record_accountId", "consent_record", ["accountId"])
    op.create_index("ix_consent_record_correctionOfId", "consent_record", ["correctionOfId"])
    op.execute(
        """
        CREATE OR REPLACE FUNCTION consent_record_immuable()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'consent_record : entrée de consentement immuable (BE-076)'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER consent_record_immuable
        BEFORE UPDATE OR DELETE ON consent_record
        FOR EACH ROW
        EXECUTE FUNCTION consent_record_immuable();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS consent_record_immuable ON consent_record")
    op.execute("DROP FUNCTION IF EXISTS consent_record_immuable()")
    op.drop_index("ix_consent_record_correctionOfId", table_name="consent_record")
    op.drop_index("ix_consent_record_accountId", table_name="consent_record")
    op.drop_index("ix_consent_record_personId", table_name="consent_record")
    op.drop_table("consent_record")
