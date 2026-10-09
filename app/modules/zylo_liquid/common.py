"""Helpers et état partagés entre les sous-domaines de zylo_liquid et `service.py`.

Pas de règle de domaine ici. Ce module n'importe jamais `service.py` ni un sous-domaine
(`stations/`, `tanks/`) : cycle.
"""

import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AppError
from app.shared.simple_cache import TTLCache
from app.rbac.service import user_has_permission
from app.modules.zylo_liquid.models import Station


# Cache TTL 60s pour les listes de produits carburant — quasi statique,
# refetché sans cache sur chaque requête sinon (Phase 1 audit, problème #3).
# Clé par organisation (`organizationId` : donnée scopée, jamais globale,
# voir commentaire de `FuelProduct.__table_args__`). Invalidé explicitement
# dans `create_fuel_product`/`update_fuel_product` ci-dessous — jamais de
# valeur périmée survivant une écriture dans le même process.
fuel_product_list_cache = TTLCache(default_ttl_seconds=60.0)


async def _check_declaration_scope(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station: Station, permission_code: str) -> None:
    allowed = await user_has_permission(db, actor_user_id, organization_id, permission_code, "station", station.id)
    if not allowed:
        raise AppError(code="permission_denied", message=f"Permission manquante : {permission_code}.", status_code=403)
