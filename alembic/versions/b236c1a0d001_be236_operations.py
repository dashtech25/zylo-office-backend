"""BE-236 : table `operations` (opérations asynchrones consultables).

Revision ID: b236c1a0d001
Revises: 290f30a9bcbf
Create Date: 2026-11-05

Crée la table `operations` : une ligne par opération, rattachée à un tenant et à son
initiateur, avec l'état, les transitions horodatées (JSON), le résultat, le motif d'échec
et la date de dernière vérification. La contrainte `ck_operations_statut` borne le statut
aux cinq états de `app/operations/models.py`.

Downgrade : supprime la table et donc toutes les opérations enregistrées. Aucune autre
table n'est modifiée.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b236c1a0d001"
down_revision: Union[str, None] = "290f30a9bcbf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, comment="Identifiant de l'opération (operationId)."),
        sa.Column("tenantId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False, comment="Tenant propriétaire."),
        sa.Column("type", sa.String(length=100), nullable=False, comment="Type d'opération, sous forme domaine.action."),
        sa.Column("statut", sa.String(length=20), nullable=False, comment="État courant parmi recue, en_cours, succes, echec, inconnu."),
        sa.Column("transitions", sa.JSON(), nullable=False, comment="Historique ordonné des transitions, horodatées."),
        sa.Column("acteurId", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False, comment="Initiateur de l'opération."),
        sa.Column("resultat", sa.JSON(), nullable=True, comment="Résultat, renseigné au succès seulement."),
        sa.Column("motifEchec", sa.String(length=500), nullable=True, comment="Motif, renseigné à l'échec seulement."),
        sa.Column("derniereVerificationAt", sa.DateTime(timezone=True), nullable=True, comment="Dernière vérification de l'issue."),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("statut IN ('recue', 'en_cours', 'succes', 'echec', 'inconnu')", name="ck_operations_statut"),
        comment="Opérations asynchrones consultables : état, transitions horodatées, résultat ou motif d'échec (BE-236).",
    )
    op.create_index("ix_operations_tenantId", "operations", ["tenantId"])
    op.create_index("ix_operations_acteurId", "operations", ["acteurId"])
    op.create_index("ix_operations_statut", "operations", ["statut"])


def downgrade() -> None:
    op.drop_index("ix_operations_statut", table_name="operations")
    op.drop_index("ix_operations_acteurId", table_name="operations")
    op.drop_index("ix_operations_tenantId", table_name="operations")
    op.drop_table("operations")
