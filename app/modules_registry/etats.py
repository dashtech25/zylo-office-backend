"""États d'un module dans le registre (BE-021).

Un module a exactement un état, décidé par le registre seul, dans cet ordre de priorité :

- `inconnu` : le code n'est pas reconnu par l'application (`CODES_MODULES_CONNUS`), que la ligne
  existe ou non ;
- `absent` : le code est reconnu, mais le registre (`module`) n'a aucune ligne pour lui ;
- `incompatible` : la ligne existe, mais son `manifestVersion` n'est pas supporté ;
- `disponible` : la ligne existe et son manifeste est lisible.

Règle dure : seul `disponible` ouvre l'accès au module. Les trois autres états refusent l'accès
même si une ligne `organizationModule` est active : aucun droit n'est déduit d'un état non
disponible. L'activation par organisation (`organizationModule.status`) reste une condition
séparée, vérifiée par `service.is_module_active`.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules_registry.manifeste import CODES_MODULES_CONNUS, VERSIONS_MANIFESTE_SUPPORTEES
from app.modules_registry.models import Module

ETAT_DISPONIBLE = "disponible"
ETAT_ABSENT = "absent"
ETAT_INCONNU = "inconnu"
ETAT_INCOMPATIBLE = "incompatible"
ETATS_MODULE: tuple[str, ...] = (ETAT_DISPONIBLE, ETAT_ABSENT, ETAT_INCONNU, ETAT_INCOMPATIBLE)


def etat_depuis_ligne(module_code: str, ligne: Module | None) -> str:
    """Calcule l'état d'un module à partir de sa ligne de registre, sans accès base.

    `ligne` vaut None quand le registre n'a aucune ligne pour `module_code`. Fonction pure :
    l'appelant qui a déjà chargé les lignes (ex. `rbac.module_rights`) s'en sert sans requête."""
    if module_code not in CODES_MODULES_CONNUS:
        return ETAT_INCONNU
    if ligne is None:
        return ETAT_ABSENT
    if ligne.manifestVersion not in VERSIONS_MANIFESTE_SUPPORTEES:
        return ETAT_INCOMPATIBLE
    return ETAT_DISPONIBLE


async def etat_module(db: AsyncSession, module_code: str) -> str:
    """Renvoie l'état registre de `module_code` (un des `ETATS_MODULE`), en une requête."""
    ligne = (await db.execute(select(Module).where(Module.code == module_code))).scalar_one_or_none()
    return etat_depuis_ligne(module_code, ligne)


def etat_ouvre_acces(etat: str) -> bool:
    """Vrai seulement pour `disponible` : aucun autre état ne donne accès au module."""
    return etat == ETAT_DISPONIBLE
