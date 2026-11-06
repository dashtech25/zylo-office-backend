"""organisation : tenant racine et identifiants légaux chiffrés (BE-186)

Revision ID: d186a0c1e2f3
Revises: b108c4a1d2e3
Create Date: 2026-11-06 00:00:00.000000

Ajoute à `organization` :
- `tenantId` : clé étrangère vers `tenant.id`, unique (CA-1 : un tenant porte une
  seule organisation). Renseignée pour chaque organisation existante : la
  migration crée le tenant racine manquant (`status` = `active`, `version` = 1)
  et le rattache. Aucune organisation n'est laissée sans tenant.
- `legalRegistrationNumberChiffre` et `legalTaxNumberChiffre` : identifiants
  légaux confidentiels, chiffrés par l'application (app.core.field_crypto).
  Vides pour les organisations existantes ; aucune donnée n'est déchiffrée ici.

Downgrade : retire la contrainte, la clé étrangère et les colonnes. Les lignes
`tenant` créées par le remplissage restent en place (aucune ne peut être
distinguée à coup sûr d'un tenant créé par BE-185 après coup).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d186a0c1e2f3"
down_revision: Union[str, None] = "b108c4a1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("tenantId", sa.UUID(), nullable=True, comment="Tenant racine de l'organisation (BE-186)"))
    op.add_column(
        "organization",
        sa.Column("legalRegistrationNumberChiffre", sa.Text(), nullable=True, comment="Numéro d'immatriculation légal, chiffré (BE-186)"),
    )
    op.add_column(
        "organization",
        sa.Column("legalTaxNumberChiffre", sa.Text(), nullable=True, comment="Numéro fiscal légal, chiffré (BE-186)"),
    )
    op.create_foreign_key("fk_organization_tenantId", "organization", "tenant", ["tenantId"], ["id"])
    op.create_unique_constraint("uq_organization_tenantId", "organization", ["tenantId"])

    # Remplissage : un tenant racine par organisation existante, puis rattachement.
    op.execute(
        """
        INSERT INTO tenant (id, "organizationId", status, version, "createdAt", "updatedAt")
        SELECT gen_random_uuid(), o.id, 'active', 1, now(), now()
        FROM organization o
        WHERE NOT EXISTS (SELECT 1 FROM tenant t WHERE t."organizationId" = o.id)
        """
    )
    op.execute(
        """
        UPDATE organization o
        SET "tenantId" = t.id
        FROM tenant t
        WHERE t."organizationId" = o.id AND o."tenantId" IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("uq_organization_tenantId", "organization", type_="unique")
    op.drop_constraint("fk_organization_tenantId", "organization", type_="foreignkey")
    op.drop_column("organization", "legalTaxNumberChiffre")
    op.drop_column("organization", "legalRegistrationNumberChiffre")
    op.drop_column("organization", "tenantId")
