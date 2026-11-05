"""BE-049 : colonnes de suspension sur module_installations.

Revises: 934346a13edd
Create Date: 2026-11-05

Ajoute à `module_installations` trois colonnes nullables décrivant la suspension courante :
`suspensionOrigin` (client, commercial, security), `suspensionReason` (motif) et `suspendedBy`
(acteur, clé étrangère vers `user`). Aucune nouvelle table : l'historique reste dans le journal
`module_state_transitions`. Les lignes existantes reçoivent NULL, ce qui est correct hors suspension.

Le downgrade supprime les trois colonnes ; il fait perdre les motifs de suspension courants, mais
le journal conserve la trace des transitions.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "be049a1b2c3d"
down_revision: Union[str, None] = "934346a13edd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "module_installations",
        sa.Column(
            "suspensionOrigin", sa.String(length=20), nullable=True,
            comment="Origine de la suspension courante (client, commercial, security) ; nulle hors suspension (BE-049).",
        ),
    )
    op.add_column(
        "module_installations",
        sa.Column(
            "suspensionReason", sa.Text(), nullable=True,
            comment="Motif de la suspension courante ; nul hors suspension (BE-049).",
        ),
    )
    op.add_column(
        "module_installations",
        sa.Column(
            "suspendedBy", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True,
            comment="Acteur qui a posé la suspension courante ; nul hors suspension (BE-049).",
        ),
    )


def downgrade() -> None:
    op.drop_column("module_installations", "suspendedBy")
    op.drop_column("module_installations", "suspensionReason")
    op.drop_column("module_installations", "suspensionOrigin")
