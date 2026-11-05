"""Droits plateforme sur le catalogue de modules (BE-042).

Les droits `platform.module.write` (créer une fiche et une version) et `platform.module.publish`
(publier une version) sont de portée plateforme : ils n'appartiennent à aucune organisation, donc
ne peuvent pas passer par `rbac.service.user_has_permission`.

Attribution, en attendant une gouvernance du catalogue (QE-MOD-16) : deux allowlists d'environnement,
listes d'identifiants d'utilisateurs séparées par des virgules.

- `PLATFORM_MODULE_WRITE_USER_IDS` : comptes autorisés à créer fiches et versions ;
- `PLATFORM_MODULE_PUBLISH_USER_IDS` : comptes autorisés à publier une version ;
- `PLATFORM_RECONCILIATION_RESOLVE_USER_IDS` : comptes autorisés à lire et résoudre les cas de
  réconciliation (BE-052) ;
- `PLATFORM_MODULE_SUSPEND_USER_IDS` : comptes autorisés à suspendre ou reprendre un module d'origine
  `commercial` ou `security` (BE-049).

Refus par défaut : variable absente ou vide, valeur mal formée ignorée (jamais un élargissement).
Les variables sont relues à chaque appel, pour qu'un changement de configuration prenne effet sans
réécriture de code. Un refus lève `PERMISSION_DENIED` (403).
"""

import os
import uuid

from app.core.errors import AppError
from app.modules_registry.permissions import (
    PLATFORM_MODULE_PUBLISH,
    PLATFORM_MODULE_SUSPEND,
    PLATFORM_MODULE_WRITE,
    PLATFORM_RECONCILIATION_RESOLVE,
)

_VARIABLE_PAR_DROIT: dict[str, str] = {
    PLATFORM_MODULE_WRITE: "PLATFORM_MODULE_WRITE_USER_IDS",
    PLATFORM_MODULE_PUBLISH: "PLATFORM_MODULE_PUBLISH_USER_IDS",
    PLATFORM_RECONCILIATION_RESOLVE: "PLATFORM_RECONCILIATION_RESOLVE_USER_IDS",
    PLATFORM_MODULE_SUSPEND: "PLATFORM_MODULE_SUSPEND_USER_IDS",
}


def _identifiants_autorises(code: str) -> set[uuid.UUID]:
    """Lit l'allowlist du droit `code` ; les valeurs mal formées sont ignorées."""
    resultat: set[uuid.UUID] = set()
    for brut in os.getenv(_VARIABLE_PAR_DROIT[code], "").split(","):
        try:
            if brut.strip():
                resultat.add(uuid.UUID(brut.strip()))
        except ValueError:
            continue
    return resultat


def a_droit_plateforme(user_id: uuid.UUID, code: str) -> bool:
    """Vrai si `user_id` figure dans l'allowlist du droit plateforme `code`."""
    if code not in _VARIABLE_PAR_DROIT:
        return False
    return user_id in _identifiants_autorises(code)


def exiger_droit_plateforme(user_id: uuid.UUID, code: str) -> None:
    """Lève `PERMISSION_DENIED` (403) si le compte ne détient pas le droit plateforme `code`."""
    if not a_droit_plateforme(user_id, code):
        raise AppError(
            code="PERMISSION_DENIED",
            message="Droit plateforme requis pour cette action sur le catalogue de modules.",
            status_code=403,
        )
