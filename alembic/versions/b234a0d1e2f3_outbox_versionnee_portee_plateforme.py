"""BE-234 : outbox versionnée, portée tenant ou plateforme, acteur et correlationId.

Ajoute à `outbox_evenement` les colonnes `portee`, `acteur`, `correlationId` et `tentatives`,
rend `tenantId` nullable pour les événements plateforme, et ajoute deux contraintes :
la portée est `tenant` ou `plateforme`, et un événement de tenant porte un `tenantId`
alors qu'un événement plateforme n'en porte pas.

Les lignes existantes (toutes de portée tenant, par construction de BE-166) reçoivent les
valeurs par défaut `portee = 'tenant'`, `acteur = {}`, `tentatives = 0`.

Downgrade : les événements plateforme ne sont pas représentables avant BE-234. Le downgrade
supprime donc leurs lignes et leurs consommations, puis rétablit `tenantId NOT NULL`. C'est une
perte de données volontaire, à ne lancer qu'en connaissance de cause.

Revision ID: b234a0d1e2f3
Revises: 5e31981cf46c
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b234a0d1e2f3"
down_revision: Union[str, None] = "5e31981cf46c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outbox_evenement",
        sa.Column("portee", sa.String(20), server_default="tenant", nullable=False),
    )
    op.add_column(
        "outbox_evenement",
        sa.Column("acteur", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column("outbox_evenement", sa.Column("correlationId", sa.String(200), nullable=True))
    op.add_column(
        "outbox_evenement",
        sa.Column("tentatives", sa.Integer(), server_default="0", nullable=False),
    )
    op.alter_column("outbox_evenement", "tenantId", existing_type=sa.UUID(), nullable=True)
    op.create_check_constraint("ck_outbox_evenement_portee", "outbox_evenement", "portee IN ('tenant', 'plateforme')")
    op.create_check_constraint(
        "ck_outbox_evenement_portee_tenant",
        "outbox_evenement",
        "(portee = 'tenant' AND \"tenantId\" IS NOT NULL) OR (portee = 'plateforme' AND \"tenantId\" IS NULL)",
    )


def downgrade() -> None:
    # Les consommations d'abord (clé étrangère sur eventId), puis les événements plateforme.
    op.execute(
        "DELETE FROM consommation_evenement WHERE \"eventId\" IN "
        "(SELECT \"eventId\" FROM outbox_evenement WHERE portee = 'plateforme')"
    )
    op.execute("DELETE FROM outbox_evenement WHERE portee = 'plateforme'")
    op.drop_constraint("ck_outbox_evenement_portee_tenant", "outbox_evenement", type_="check")
    op.drop_constraint("ck_outbox_evenement_portee", "outbox_evenement", type_="check")
    op.alter_column("outbox_evenement", "tenantId", existing_type=sa.UUID(), nullable=False)
    op.drop_column("outbox_evenement", "tentatives")
    op.drop_column("outbox_evenement", "correlationId")
    op.drop_column("outbox_evenement", "acteur")
    op.drop_column("outbox_evenement", "portee")
