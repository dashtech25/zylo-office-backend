"""BE-102 : créateur de l'organisation (`organization.createdByUserId`).

Revision ID: be102c0de0102
Revises: b189c0de0189
Create Date: 2026-11-06

Ajoute `organization.createdByUserId` (FK vers `user.id`, nullable) : le créateur d'une
organisation, utilisé par POST /api/v1/organizations pour refuser un doublon (même nom
normalisé, même créateur). Migration purement additive : les organisations existantes
restent sans créateur renseigné (NULL), donc hors de la déduplication.

Downgrade : suppression de la clé étrangère puis de la colonne.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "be102c0de0102"
down_revision: Union[str, None] = "b189c0de0189"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organization",
        sa.Column(
            "createdByUserId",
            sa.UUID(as_uuid=True),
            nullable=True,
            comment="Créateur de l'organisation (BE-102) ; NULL pour les organisations antérieures.",
        ),
    )
    op.create_foreign_key(
        "fk_organization_createdByUserId_user",
        "organization",
        "user",
        ["createdByUserId"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_organization_createdByUserId_user", "organization", type_="foreignkey")
    op.drop_column("organization", "createdByUserId")
