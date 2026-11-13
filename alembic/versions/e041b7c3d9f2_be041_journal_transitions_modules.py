"""BE-041 : journal append-only des transitions d'état des modules.

Crée la table `module_state_transitions`, son enum PostgreSQL `module_transition_origin` et les
deux contraintes d'unicité : `(subjectType, subjectId, idempotencyKey)` (idempotence) et
`(subjectType, subjectId, stateVersionAfter)` (une seule transition par version d'état).

Downgrade : supprime la table puis l'enum. Le journal n'existe qu'à partir de cette révision :
le retour arrière efface les transitions journalisées, à n'utiliser que sur une base de test.

Revision ID: e041b7c3d9f2
Revises: d4e5f6a7b8c9
Create Date: 2026-11-04 00:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e041b7c3d9f2"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ORIGINES = ("client", "commercial", "security", "support", "automation", "platform")


def upgrade() -> None:
    origine = postgresql.ENUM(*ORIGINES, name="module_transition_origin", create_type=False)
    origine.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "module_state_transitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subjectType", sa.String(length=100), nullable=False),
        sa.Column("subjectId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fromState", sa.String(length=50), nullable=False),
        sa.Column("toState", sa.String(length=50), nullable=False),
        sa.Column("actorId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("origin", origine, nullable=False, comment="Origine de la transition."),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("operationId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotencyKey", sa.String(length=200), nullable=False),
        sa.Column("stateVersionBefore", sa.Integer(), nullable=False),
        sa.Column("stateVersionAfter", sa.Integer(), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organizationId"], ["organization.id"]),
        sa.UniqueConstraint(
            "subjectType", "subjectId", "idempotencyKey", name="uq_module_state_transitions_idempotence"
        ),
        sa.UniqueConstraint(
            "subjectType", "subjectId", "stateVersionAfter", name="uq_module_state_transitions_version"
        ),
        comment="Journal append-only des transitions d'état des modules (BE-041).",
    )
    op.create_index(op.f("ix_module_state_transitions_subjectType"), "module_state_transitions", ["subjectType"])
    op.create_index(op.f("ix_module_state_transitions_subjectId"), "module_state_transitions", ["subjectId"])
    op.create_index(op.f("ix_module_state_transitions_organizationId"), "module_state_transitions", ["organizationId"])
    op.create_index(op.f("ix_module_state_transitions_operationId"), "module_state_transitions", ["operationId"])


def downgrade() -> None:
    op.drop_index(op.f("ix_module_state_transitions_operationId"), table_name="module_state_transitions")
    op.drop_index(op.f("ix_module_state_transitions_organizationId"), table_name="module_state_transitions")
    op.drop_index(op.f("ix_module_state_transitions_subjectId"), table_name="module_state_transitions")
    op.drop_index(op.f("ix_module_state_transitions_subjectType"), table_name="module_state_transitions")
    op.drop_table("module_state_transitions")
    postgresql.ENUM(name="module_transition_origin").drop(op.get_bind(), checkfirst=True)
