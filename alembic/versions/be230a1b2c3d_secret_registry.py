"""BE-230 : registre des secrets de l'exploitation (métadonnées, aucune valeur).

Revision ID: be230a1b2c3d
Revises: 73136cdbf00b
Create Date: 2026-11-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "be230a1b2c3d"
down_revision: Union[str, None] = "73136cdbf00b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "secret_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, comment="Identifiant UUID généré côté application."),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True, comment="Nom de la variable d'environnement du secret."),
        sa.Column("owner", sa.String(length=120), nullable=False, comment="Équipe ou rôle responsable de la rotation."),
        sa.Column("scope", sa.String(length=40), nullable=False, server_default="environment", comment="Portée du secret (environment)."),
        sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=True, comment="Échéance du secret ; NULL si inconnue."),
        sa.Column("lastRotatedAt", sa.DateTime(timezone=True), nullable=True, comment="Dernière rotation confirmée."),
        sa.Column("consumer", sa.String(length=200), nullable=False, comment="Composant qui consomme le secret."),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true"), comment="Secret obligatoire hors développement."),
        comment="Registre des secrets (BE-230) : aucune valeur de secret n'est stockée.",
    )


def downgrade() -> None:
    op.drop_table("secret_registry")
