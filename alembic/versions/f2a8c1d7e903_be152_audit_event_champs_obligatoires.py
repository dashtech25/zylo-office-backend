"""BE-152 : champs obligatoires non vides du journal `audit_event`

Revision ID: f2a8c1d7e903
Revises: d5624b3c990f
Create Date: 2026-11-05

Table visée : `audit_event` (BE-007). Aucune table d'audit n'est créée.

Les colonnes `actorUserId`, `entityType`, `action`, `request_id` et `eventId`
sont déjà NOT NULL (BE-007). Une chaîne vide ou faite d'espaces passait
pourtant. Cette migration ajoute trois contraintes CHECK qui refusent, côté
base, une ligne dont l'action, la cible (`entityType`) ou la corrélation
(`request_id`) est vide après retrait des espaces (CA-3 de BE-152). La présence
de l'acteur reste garantie par la contrainte NOT NULL existante.

Données existantes : une ligne déjà vide ferait échouer la pose des contraintes.
Aucune écriture applicative ne produit de chaîne vide (service
`record_audit_event`), donc la migration n'attend pas de nettoyage ; en cas
d'échec, il faut corriger ou supprimer ces lignes avant de relancer.

Downgrade : retire les trois contraintes. Aucune donnée n'est modifiée.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f2a8c1d7e903"
down_revision: Union[str, None] = "d5624b3c990f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONTRAINTES = [
    ("ck_audit_event_action_non_vide", "length(btrim(action)) > 0"),
    ("ck_audit_event_entityType_non_vide", 'length(btrim("entityType")) > 0'),
    ("ck_audit_event_request_id_non_vide", 'length(btrim("request_id")) > 0'),
]


def upgrade() -> None:
    for nom, expression in _CONTRAINTES:
        op.create_check_constraint(nom, "audit_event", expression)


def downgrade() -> None:
    for nom, _ in reversed(_CONTRAINTES):
        op.drop_constraint(nom, "audit_event", type_="check")
