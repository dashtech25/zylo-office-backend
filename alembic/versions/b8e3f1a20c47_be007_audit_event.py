"""BE-007 : renommage de auditLog en audit_event et colonnes du journal métier

Revision ID: b8e3f1a20c47
Revises: e072b1c2d3a4
Create Date: 2026-11-03

Décision D2 : une seule table d'audit. Cette migration renomme `auditLog` en
`audit_event`, renomme ses index, puis ajoute les colonnes demandées par
BE-007 (QE-SOC-22 et BE-122, BE-152, BE-227).

Reprise des lignes existantes (la requête d'origine n'était pas tracée) :
- `request_id` = identifiant de la ligne (valeur de substitution, documentée) ;
- `eventId` = identifiant de la ligne (unique, comme pour toute nouvelle ligne) ;
- `result` = 'success' ; `actorType` = 'humain' ; `schemaVersion` = 1.

`organizationId` devient nullable pour la portée plateforme. Les colonnes
`visibility` et `dataClassification` restent nullables (valeurs NON DÉFINIES).

Downgrade : retire les colonnes ajoutées, renomme la table et les index en
retour. ATTENTION : le downgrade supprime les entrées sans organisation (portée
plateforme), car `organizationId` redevient obligatoire, et perd les colonnes
`request_id`, `result`, `eventId`, `actorType`, `reason`, `approvalId`,
`schemaVersion`, `visibility`, `dataClassification` de toutes les lignes.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8e3f1a20c47"
down_revision: Union[str, None] = "e072b1c2d3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Index créés par la migration d'origine d77282efbbb2 sur auditLog. Leur nom
# suit la convention ix_<table>_<colonne> ; le renommage les aligne sur audit_event.
_INDEX_RENOMMES = [
    ("ix_auditLog_action", "ix_audit_event_action"),
    ("ix_auditLog_actorUserId", "ix_audit_event_actorUserId"),
    ("ix_auditLog_createdAt", "ix_audit_event_createdAt"),
    ("ix_auditLog_entityId", "ix_audit_event_entityId"),
    ("ix_auditLog_organizationId", "ix_audit_event_organizationId"),
    ("ix_auditLog_scopeResourceId", "ix_audit_event_scopeResourceId"),
    ("ix_auditLog_scopeResourceType", "ix_audit_event_scopeResourceType"),
]

_COMMENTAIRE_TABLE = "Journal d'audit métier unique : qui a fait quoi, sur quel élément, quand, avec quel résultat."
_COMMENTAIRE_AVANT = "Journal d'audit — qui a fait quoi, sur quel élément, quand."


def upgrade() -> None:
    # 1. Renommage de la table et des index : aucune donnée n'est copiée.
    op.rename_table("auditLog", "audit_event")
    for ancien, nouveau in _INDEX_RENOMMES:
        op.execute(f'ALTER INDEX "{ancien}" RENAME TO "{nouveau}"')

    # 2. Colonnes ajoutées, d'abord nullables pour la reprise des lignes existantes.
    op.add_column("audit_event", sa.Column("request_id", sa.String(length=128), nullable=True))
    op.add_column("audit_event", sa.Column("result", sa.String(length=16), nullable=True))
    op.add_column("audit_event", sa.Column("eventId", sa.String(length=64), nullable=True))
    op.add_column("audit_event", sa.Column("actorType", sa.String(length=16), nullable=True))
    op.add_column("audit_event", sa.Column("reason", sa.String(length=500), nullable=True))
    op.add_column("audit_event", sa.Column("approvalId", sa.String(length=64), nullable=True))
    op.add_column("audit_event", sa.Column("schemaVersion", sa.Integer(), nullable=True))
    op.add_column("audit_event", sa.Column("visibility", sa.String(length=32), nullable=True))
    op.add_column("audit_event", sa.Column("dataClassification", sa.String(length=32), nullable=True))

    # 3. Reprise des lignes existantes : valeurs de substitution, documentées dans l'en-tête.
    op.execute(
        """
        UPDATE audit_event
        SET request_id = id::text,
            "eventId" = id::text,
            result = 'success',
            "actorType" = 'humain',
            "schemaVersion" = 1
        """
    )

    # 4. Contraintes définitives : valeurs par défaut pour les écritures futures.
    op.alter_column("audit_event", "request_id", nullable=False)
    op.alter_column("audit_event", "result", nullable=False, server_default="success")
    op.alter_column("audit_event", "eventId", nullable=False)
    op.alter_column("audit_event", "actorType", nullable=False, server_default="humain")
    op.alter_column("audit_event", "schemaVersion", nullable=False, server_default="1")
    op.alter_column("audit_event", "organizationId", nullable=True)

    op.create_unique_constraint("audit_event_eventId_key", "audit_event", ["eventId"])
    op.create_index("ix_audit_event_request_id", "audit_event", ["request_id"], unique=False)
    op.create_check_constraint(
        "ck_audit_event_result", "audit_event", "result IN ('success', 'refused', 'error')"
    )
    op.create_check_constraint(
        "ck_audit_event_actorType", "audit_event", "\"actorType\" IN ('humain', 'service', 'systeme')"
    )

    op.create_table_comment(
        "audit_event", _COMMENTAIRE_TABLE, existing_comment=_COMMENTAIRE_AVANT, schema=None
    )


def downgrade() -> None:
    # Les entrées de portée plateforme (sans organisation) ne peuvent pas
    # survivre au retour à `organizationId NOT NULL` : elles sont supprimées.
    op.execute('DELETE FROM audit_event WHERE "organizationId" IS NULL')

    op.create_table_comment(
        "audit_event", _COMMENTAIRE_AVANT, existing_comment=_COMMENTAIRE_TABLE, schema=None
    )

    op.drop_constraint("ck_audit_event_actorType", "audit_event", type_="check")
    op.drop_constraint("ck_audit_event_result", "audit_event", type_="check")
    op.drop_index("ix_audit_event_request_id", table_name="audit_event")
    op.drop_constraint("audit_event_eventId_key", "audit_event", type_="unique")

    op.alter_column("audit_event", "organizationId", nullable=False)

    op.drop_column("audit_event", "dataClassification")
    op.drop_column("audit_event", "visibility")
    op.drop_column("audit_event", "schemaVersion")
    op.drop_column("audit_event", "approvalId")
    op.drop_column("audit_event", "reason")
    op.drop_column("audit_event", "actorType")
    op.drop_column("audit_event", "eventId")
    op.drop_column("audit_event", "result")
    op.drop_column("audit_event", "request_id")

    for ancien, nouveau in _INDEX_RENOMMES:
        op.execute(f'ALTER INDEX "{nouveau}" RENAME TO "{ancien}"')
    op.rename_table("audit_event", "auditLog")
