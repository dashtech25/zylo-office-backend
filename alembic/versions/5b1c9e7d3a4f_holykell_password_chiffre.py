"""chiffrement du mot de passe Holykell : colonne chiffrée, colonne en clair rendue nullable (T-027)

Revision ID: 5b1c9e7d3a4f
Revises: a9b8c7d6e5f4
Create Date: 2026-10-09

Intention : migration purement additive pour la transition.
- ajoute `holykellPasswordChiffre` (Text, nullable) ;
- rend `holykellPassword` nullable : une nouvelle écriture ne renseigne plus que la
  colonne chiffrée. L'ancienne colonne n'est PAS supprimée (tâche distincte).

Retour arrière : le downgrade déchiffre les valeurs écrites depuis la migration
(clé requise, sinon échec sans modification) pour réremplir la colonne en clair,
puis rétablit NOT NULL et retire la colonne chiffrée. Une valeur sans aucune
forme lisible fait échouer le downgrade plutôt que d'être perdue.
"""
import sqlalchemy as sa
from alembic import op

from app.core.field_crypto import dechiffrer

# revision identifiers, used by Alembic.
revision = "5b1c9e7d3a4f"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None

TABLE = "zyloLiquidHolykellAccount"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("holykellPasswordChiffre", sa.Text(), nullable=True))
    op.alter_column(TABLE, "holykellPassword", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    lignes = bind.execute(
        sa.text(f'SELECT id, "holykellPasswordChiffre" FROM "{TABLE}" WHERE "holykellPassword" IS NULL')
    ).all()
    for ligne_id, chiffre in lignes:
        if not chiffre:
            raise RuntimeError(
                f"downgrade refusé : le compte {ligne_id} n'a ni valeur chiffrée ni valeur en clair."
            )
        # Erreur de clé : l'exception remonte, la transaction Alembic est annulée.
        clair = dechiffrer(chiffre)
        bind.execute(
            sa.text(f'UPDATE "{TABLE}" SET "holykellPassword" = :clair WHERE id = :id'),
            {"clair": clair, "id": ligne_id},
        )
    op.alter_column(TABLE, "holykellPassword", existing_type=sa.String(length=255), nullable=False)
    op.drop_column(TABLE, "holykellPasswordChiffre")
