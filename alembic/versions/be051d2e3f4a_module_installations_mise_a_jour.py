"""BE-051 : colonnes de mise à jour de version sur module_installations.

Ajoute `upgradeTargetVersionId` (FK vers `module_version`, version cible de la mise à jour en cours
ou échouée) et `upgradeState` (running, failed, completed). Les deux colonnes sont nulles pour une
installation qui n'a jamais été mise à jour, ce qui garde la migration sans effet sur les lignes
existantes.

Downgrade : supprime la clé étrangère puis les deux colonnes. Les valeurs de mise à jour sont perdues
au retour arrière ; c'est acceptable car ce sont des informations d'opération, la version installée
(`moduleVersionId`) n'est pas touchée.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "be051d2e3f4a"
down_revision: Union[str, None] = "d5624b3c990f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOM_CLE_CIBLE = "fk_module_installations_upgrade_target_version"


def upgrade() -> None:
    op.add_column(
        "module_installations",
        sa.Column(
            "upgradeTargetVersionId",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Version cible de la mise à jour en cours ou échouée (BE-051) ; nulle sinon.",
        ),
    )
    op.create_foreign_key(
        NOM_CLE_CIBLE,
        "module_installations",
        "module_version",
        ["upgradeTargetVersionId"],
        ["id"],
    )
    op.add_column(
        "module_installations",
        sa.Column(
            "upgradeState",
            sa.String(length=50),
            nullable=True,
            comment="État de la mise à jour (running, failed, completed) ; nul sans mise à jour (BE-051).",
        ),
    )


def downgrade() -> None:
    op.drop_column("module_installations", "upgradeState")
    op.drop_constraint(NOM_CLE_CIBLE, "module_installations", type_="foreignkey")
    op.drop_column("module_installations", "upgradeTargetVersionId")
