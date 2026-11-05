"""Enregistrement des permissions du module paramètres en base (BE-157).

Une permission absente de la table `permission` est refusée partout, y compris au propriétaire
(voir CLAUDE.md, section sécurité). Ce module ne rattache la permission à aucun rôle : c'est
une décision d'administration (QE-PAR-03).
"""

from app.core.database import AsyncSessionLocal
from app.parametres.permissions import PARAMETRE_APPLIQUER, PARAMETRE_LIRE
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    """Crée les permissions du module si elles n'existent pas (idempotent)."""
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(db, PARAMETRE_APPLIQUER, "parametres", "Appliquer, restaurer ou rétablir le défaut d'un paramètre (BE-157).")
        await get_or_create_permission(db, PARAMETRE_LIRE, "parametres", "Lire les paramètres résolus d'un scope (BE-158).")
        await db.commit()
