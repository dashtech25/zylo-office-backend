"""BE-024 : entitlements d'abonnement (table renommée, colonnes absorbées de BE-261, registre de capacités).

Revision ID: b024e7a1c5d3
Revises: 82b12c50c3f6

Ce que fait la migration :
- crée la table `capability` (registre de capacités rattaché à `module`) ;
- renomme `subscriptionEntitlement` en `subscription_entitlement` (décision du propriétaire,
  snake_case pour BE-024), avec ses index et sa contrainte unique ;
- ajoute `offreId` (FK `planVersion`), `capaciteId` (FK `capability`), `quotaLimite`,
  `niveauApplication` et `sourceAttribution` ;
- rend `organizationId` nullable : une offre globale n'a pas d'organisation, la contrainte
  `ck_subscription_entitlement_org_offre_globale` limite ce cas à `sourceAttribution` = `offre` ;
- ajoute les contraintes CHECK sur les valeurs énumérées, le statut et le quota positif.

Les lignes existantes reçoivent `niveauApplication` = `organisation` et `sourceAttribution` =
`offre` par défaut : elles ont été créées par l'offre d'abonnement (BE-023). `capaciteId` et
`offreId` restent nuls pour elles.

Downgrade : retour au schéma de c0b7d9a2e511 pour la table et ses colonnes. Il échoue si des
lignes sans organisation (offres globales) existent : elles ne peuvent pas être rendues au
schéma précédent sans perte, et la migration refuse de les supprimer en silence.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b024e7a1c5d3"
down_revision: Union[str, None] = "82b12c50c3f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONTRAINTES_CHECK = (
    "ck_subscription_entitlement_niveau",
    "ck_subscription_entitlement_source",
    "ck_subscription_entitlement_status",
    "ck_subscription_entitlement_quota_positif",
    "ck_subscription_entitlement_org_offre_globale",
)


def upgrade() -> None:
    op.create_table(
        "capability",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("moduleCode", sa.String(100), sa.ForeignKey("module.code"), nullable=False),
        sa.Column("code", sa.String(150), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("quotaUnit", sa.String(50), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="Registre des capacités d'un module, cible des entitlements d'abonnement.",
    )
    op.create_index("ix_capability_moduleCode", "capability", ["moduleCode"])

    op.rename_table("subscriptionEntitlement", "subscription_entitlement")
    op.execute('ALTER INDEX "ix_subscriptionEntitlement_organizationId" RENAME TO ix_subscription_entitlement_organizationId')
    op.execute('ALTER INDEX "ix_subscriptionEntitlement_subscriptionId" RENAME TO ix_subscription_entitlement_subscriptionId')
    op.execute(
        "ALTER TABLE subscription_entitlement RENAME CONSTRAINT "
        '"uq_subscriptionEntitlement_subscription_code" TO uq_subscription_entitlement_subscription_code'
    )

    op.alter_column("subscription_entitlement", "organizationId", existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("subscription_entitlement", sa.Column("offreId", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("planVersion.id"), nullable=True))
    op.add_column("subscription_entitlement", sa.Column("capaciteId", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("capability.id"), nullable=True))
    op.add_column("subscription_entitlement", sa.Column("quotaLimite", sa.Integer(), nullable=True))
    op.add_column("subscription_entitlement", sa.Column("niveauApplication", sa.String(20), nullable=False, server_default="organisation"))
    op.add_column("subscription_entitlement", sa.Column("sourceAttribution", sa.String(30), nullable=False, server_default="offre"))
    op.create_index("ix_subscription_entitlement_offreId", "subscription_entitlement", ["offreId"])
    op.create_index("ix_subscription_entitlement_capaciteId", "subscription_entitlement", ["capaciteId"])

    op.create_check_constraint(
        "ck_subscription_entitlement_niveau", "subscription_entitlement",
        "\"niveauApplication\" IN ('organisation', 'utilisateur')",
    )
    op.create_check_constraint(
        "ck_subscription_entitlement_source", "subscription_entitlement",
        "\"sourceAttribution\" IN ('offre', 'achat_additionnel', 'essai', 'allocation_admin', 'usage_reel')",
    )
    op.create_check_constraint(
        "ck_subscription_entitlement_status", "subscription_entitlement",
        "status IN ('active', 'inactive', 'expired', 'blocked')",
    )
    op.create_check_constraint(
        "ck_subscription_entitlement_quota_positif", "subscription_entitlement",
        "\"quotaLimite\" IS NULL OR \"quotaLimite\" > 0",
    )
    op.create_check_constraint(
        "ck_subscription_entitlement_org_offre_globale", "subscription_entitlement",
        "\"organizationId\" IS NOT NULL OR \"sourceAttribution\" = 'offre'",
    )


def downgrade() -> None:
    for nom in CONTRAINTES_CHECK:
        op.drop_constraint(nom, "subscription_entitlement", type_="check")
    op.drop_index("ix_subscription_entitlement_capaciteId", table_name="subscription_entitlement")
    op.drop_index("ix_subscription_entitlement_offreId", table_name="subscription_entitlement")
    op.drop_column("subscription_entitlement", "sourceAttribution")
    op.drop_column("subscription_entitlement", "niveauApplication")
    op.drop_column("subscription_entitlement", "quotaLimite")
    op.drop_column("subscription_entitlement", "capaciteId")
    op.drop_column("subscription_entitlement", "offreId")
    # Échoue si une offre globale (organizationId nul) existe : pas de suppression silencieuse.
    op.alter_column("subscription_entitlement", "organizationId", existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=False)

    op.execute(
        "ALTER TABLE subscription_entitlement RENAME CONSTRAINT "
        'uq_subscription_entitlement_subscription_code TO "uq_subscriptionEntitlement_subscription_code"'
    )
    op.execute('ALTER INDEX ix_subscription_entitlement_subscriptionId RENAME TO "ix_subscriptionEntitlement_subscriptionId"')
    op.execute('ALTER INDEX ix_subscription_entitlement_organizationId RENAME TO "ix_subscriptionEntitlement_organizationId"')
    op.rename_table("subscription_entitlement", "subscriptionEntitlement")

    op.drop_index("ix_capability_moduleCode", table_name="capability")
    op.drop_table("capability")
