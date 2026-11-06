"""Droit plateforme de gestion des tenants (BE-185, CA-2).

`platform.tenant.manage` couvre la création d'un tenant et chaque transition.
Il est de portée plateforme : il n'appartient à aucune organisation, donc il ne
passe pas par `rbac.service.user_has_permission`.

Attribution : allowlist d'environnement `PLATFORM_TENANT_MANAGE_USER_IDS`, liste
d'identifiants d'utilisateurs séparés par des virgules. Même principe que les
droits plateforme du catalogue (BE-042, `app/modules_registry/platform_rights.py`),
repris ici sans import croisé entre packages.

Refus par défaut : variable absente ou vide, valeur mal formée ignorée. La
variable est relue à chaque appel, pour qu'un changement de configuration prenne
effet sans redéploiement.
"""

import os
import uuid

from app.core.errors import AppError

PLATFORM_TENANT_MANAGE = "platform.tenant.manage"
VARIABLE_ALLOWLIST = "PLATFORM_TENANT_MANAGE_USER_IDS"


def a_droit_gestion_tenant(user_id: uuid.UUID) -> bool:
    """Vrai si `user_id` figure dans l'allowlist de `platform.tenant.manage`."""
    autorises: set[uuid.UUID] = set()
    for brut in os.getenv(VARIABLE_ALLOWLIST, "").split(","):
        try:
            if brut.strip():
                autorises.add(uuid.UUID(brut.strip()))
        except ValueError:
            continue
    return user_id in autorises


def exiger_gestion_tenant(user_id: uuid.UUID) -> None:
    """Lève `PERMISSION_DENIED` (403) si le compte n'a pas `platform.tenant.manage`."""
    if not a_droit_gestion_tenant(user_id):
        raise AppError(
            code="PERMISSION_DENIED",
            message="Droit plateforme requis pour gérer les tenants.",
            status_code=403,
        )
