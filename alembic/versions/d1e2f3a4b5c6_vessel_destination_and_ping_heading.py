"""vessel destination et heading sur les positions GPS (ETA/statut navire)

Revision ID: d1e2f3a4b5c6
Revises: f4a7c2d891be
Create Date: 2026-09-17

Écrit à la main (même raison que les migrations précédentes du tracking :
l'autogenerate sur cette base mêle systématiquement du bruit de
renommage d'index sans rapport avec le changement réel).

Contenu :
- `zyloTankerVessel` : quatre colonnes nullable pour la destination fixée
  manuellement (`destinationLatitude`/`destinationLongitude`/
  `destinationLabel`/`destinationSetAt`) — voir la docstring de
  `app/modules/zylo_tanker/models.py::Vessel`.
- `zyloLiquidTruckPositionPing` : nouvelle colonne `headingDeg` nullable
  (cap/route GPS/AIS, 0-360°) — voir la docstring de
  `app/location/models.py::TruckPositionPing`. Utilisée pour le calcul
  d'ETA/statut d'un navire (`app/location/service.py`), jamais
  recalculée à partir de deux positions successives.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'f4a7c2d891be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('zyloTankerVessel', sa.Column('destinationLatitude', sa.Numeric(precision=10, scale=7), nullable=True, comment="Destination fixée manuellement — null si aucune destination n'est actuellement définie."))
    op.add_column('zyloTankerVessel', sa.Column('destinationLongitude', sa.Numeric(precision=10, scale=7), nullable=True, comment="Destination fixée manuellement — null si aucune destination n'est actuellement définie."))
    op.add_column('zyloTankerVessel', sa.Column('destinationLabel', sa.String(length=150), nullable=True, comment="Libellé libre de la destination (ex. nom du port) — optionnel même quand une destination est fixée."))
    op.add_column('zyloTankerVessel', sa.Column('destinationSetAt', sa.DateTime(), nullable=True, comment="Horodatage de la dernière fixation de destination — null si aucune destination n'est actuellement définie."))

    op.add_column('zyloLiquidTruckPositionPing', sa.Column('headingDeg', sa.Numeric(precision=6, scale=2), nullable=True, comment="Cap/route en degrés (0-360, 0=nord), fourni par le GPS/AIS du boîtier — jamais recalculé ici."))


def downgrade() -> None:
    op.drop_column('zyloLiquidTruckPositionPing', 'headingDeg')

    op.drop_column('zyloTankerVessel', 'destinationSetAt')
    op.drop_column('zyloTankerVessel', 'destinationLabel')
    op.drop_column('zyloTankerVessel', 'destinationLongitude')
    op.drop_column('zyloTankerVessel', 'destinationLatitude')
