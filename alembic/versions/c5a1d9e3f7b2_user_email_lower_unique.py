"""Unicité de l'e-mail sans tenir compte de la casse (T-013).

Contrôle de doublons AVANT l'index : si deux comptes ne diffèrent que par la
casse, la migration s'arrête avec la liste, sans rien modifier. Décision de
nettoyage (fusion ou suppression d'un compte) à prendre par l'opérateur.
Retour arrière : suppression de l'index (additif, aucune donnée touchée).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5a1d9e3f7b2"
down_revision: Union[str, None] = "5b1c9e7d3a4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    doublons = op.get_bind().execute(
        sa.text('SELECT lower("email") AS adresse, count(*) AS nombre FROM "user" GROUP BY lower("email") HAVING count(*) > 1 ORDER BY 1 LIMIT 20')
    ).fetchall()
    if doublons:
        liste = ", ".join(f"{ligne.adresse} ({ligne.nombre})" for ligne in doublons)
        raise RuntimeError(
            "Migration T-013 refusée : des comptes ne diffèrent que par la casse de l'e-mail. "
            f"Corriger avant de relancer : {liste}"
        )
    op.create_index("uq_user_email_lower", "user", [sa.text("lower(email)")], unique=True)


def downgrade() -> None:
    op.drop_index("uq_user_email_lower", table_name="user")
