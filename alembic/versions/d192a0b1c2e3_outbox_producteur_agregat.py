"""BE-192 : colonnes d'agrégat et de producteur dans l'outbox.

Ajoute à `outbox_evenement` les colonnes `aggregateType`, `aggregateId`, `aggregateVersion` et
`producer`, toutes nullables : les lignes existantes (écrites avant BE-192) n'ont pas d'agrégat
connu, et l'historique ne doit pas être réécrit.

Écart consigné : la définition BE-192 nomme la table `event_outbox`. La table existante
`outbox_evenement` (BE-166, BE-234) tient déjà ce rôle ; on l'étend au lieu d'en créer une seconde.

Downgrade : suppression des quatre colonnes. Les valeurs d'agrégat écrites depuis BE-192 sont
perdues ; les événements, eux, restent dans leur payload et leur `schemaVersion`.

Revision ID: d192a0b1c2e3
Revises: 52e99f1b21b5
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d192a0b1c2e3"
down_revision: Union[str, None] = "52e99f1b21b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outbox_evenement", sa.Column("aggregateType", sa.String(100), nullable=True))
    op.add_column("outbox_evenement", sa.Column("aggregateId", sa.String(200), nullable=True))
    op.add_column("outbox_evenement", sa.Column("aggregateVersion", sa.Integer(), nullable=True))
    op.add_column("outbox_evenement", sa.Column("producer", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("outbox_evenement", "producer")
    op.drop_column("outbox_evenement", "aggregateVersion")
    op.drop_column("outbox_evenement", "aggregateId")
    op.drop_column("outbox_evenement", "aggregateType")
