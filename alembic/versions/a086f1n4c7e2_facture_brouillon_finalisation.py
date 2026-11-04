"""BE-086 : facture brouillon et finalisation (append-only).

Ajoute à `invoice` les colonnes `taxSnapshot` (JSON), `total` (BIGINT) et `finalizedAt`
(TIMESTAMPTZ), toutes NULLABLE : les factures émises avant BE-086 restent valides.

Pose aussi un trigger PostgreSQL `invoice_proteger_finalisee` : une fois `finalizedAt`
renseigné, la base refuse toute modification du contenu (montant, devise, abonnement,
total, taxe, date de finalisation) et toute suppression. Le statut reste modifiable,
pour que les transitions de paiement (`open`, `partially_paid`, `paid`) restent possibles
sans rouvrir le contenu. C'est la garantie de la base, en plus du contrôle du service
(app/billing/invoices.py) : une écriture directe ne peut pas contourner l'append-only.

Revision ID: a086f1n4c7e2
Revises: 12b9bd0b8c15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a086f1n4c7e2"
down_revision: Union[str, None] = "12b9bd0b8c15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoice", sa.Column("taxSnapshot", postgresql.JSONB(), nullable=True))
    op.add_column("invoice", sa.Column("total", sa.BigInteger(), nullable=True))
    op.add_column("invoice", sa.Column("finalizedAt", sa.DateTime(timezone=True), nullable=True))
    op.execute("""
        CREATE OR REPLACE FUNCTION invoice_proteger_finalisee() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD."finalizedAt" IS NOT NULL THEN
                    RAISE EXCEPTION 'facture finalisée : suppression refusée' USING ERRCODE = 'check_violation';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD."finalizedAt" IS NOT NULL AND (
                NEW."total" IS DISTINCT FROM OLD."total"
                OR NEW."taxSnapshot" IS DISTINCT FROM OLD."taxSnapshot"
                OR NEW."amountCents" IS DISTINCT FROM OLD."amountCents"
                OR NEW."currency" IS DISTINCT FROM OLD."currency"
                OR NEW."subscriptionId" IS DISTINCT FROM OLD."subscriptionId"
                OR NEW."finalizedAt" IS DISTINCT FROM OLD."finalizedAt"
            ) THEN
                RAISE EXCEPTION 'facture finalisée : modification du contenu refusée' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute(
        "CREATE TRIGGER invoice_proteger_finalisee BEFORE UPDATE OR DELETE ON invoice "
        "FOR EACH ROW EXECUTE FUNCTION invoice_proteger_finalisee();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS invoice_proteger_finalisee ON invoice;")
    op.execute("DROP FUNCTION IF EXISTS invoice_proteger_finalisee();")
    op.drop_column("invoice", "finalizedAt")
    op.drop_column("invoice", "total")
    op.drop_column("invoice", "taxSnapshot")
