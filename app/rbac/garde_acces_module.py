"""Garde de route `require_module_action` : applique le moteur d'accessibilité (BE-053).

Intention : toute route de module qui porte son tenant dans le chemin
(`/organizations/{organization_id}/modules/{module_id}/...`) passe par UNE seule
dépendance FastAPI. Elle appelle `evaluer_acces_effectif` (rbac/acces_effectif.py) et
n'ajoute aucune règle de droit : elle traduit la décision en réponse HTTP.

Invariants appliqués :
- Le tenant est lu dans le chemin uniquement. Ni le corps, ni un en-tête client ne
  désignent l'organisation (invariant 1). Les seuls paramètres lus sont
  `organization_id` et `module_id` du chemin.
- Le module est résolu depuis `module_id` (catalogue `modules`). Un module inconnu
  renvoie 404 `resource_not_found`, avant toute évaluation.
- Sans session valide, `get_current_user` lève 401 avant tout accès aux données : la
  dépendance d'utilisateur est déclarée en premier, donc résolue en premier.

Réponses :
- non-membre de l'organisation (tenant absent ou sans appartenance active) : 404
  `organization_not_found`, réponse identique à celle des autres gardes d'organisation
  (aucune énumération) ;
- refus du moteur (permission, module inactif, entitlement, réconciliation, politique) :
  403 `ACCESS_DENIED`. Le motif stable (`reason` du moteur) n'est pas exposé à l'appelant
  non administrateur ; il reste dans l'évaluation de diagnostic (BE-053) ;
- accord : la route s'exécute.

Capacité : `exige_entitlement` déclare si l'action exige un abonnement. Une valeur absente
(None) est traitée comme « exige » : c'est le fail closed de QE-MOD-14 (une capacité non
déclarée ne doit jamais ouvrir l'accès). Une route qui ne dépend pas de l'abonnement doit
le déclarer explicitement (False).

Le moteur ne persiste rien : la garde est sans effet de bord (CA-4).
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.modules_registry.models import Module
from app.rbac.acces_effectif import MOTIF_NON_MEMBRE, evaluer_acces_effectif


def require_module_action(
    action: str,
    *,
    exige_entitlement: bool | None = None,
    module_actif_requis: bool = True,
) -> Callable[..., Coroutine[Any, Any, None]]:
    """Fabrique la dépendance FastAPI qui applique le moteur à `action` sur le module du chemin.

    `action` : code de permission `domaine.entite.action` de la route.
    `exige_entitlement` : True / False déclaré pour cette action ; None = non déclaré (fail closed).
    `module_actif_requis` : False pour la seule réactivation d'un module suspendu (QE-BE054-05) ;
    l'appartenance, la permission et la politique restent contrôlées.
    """

    async def dependency(
        organization_id: uuid.UUID,
        module_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        module_code = (await db.execute(select(Module.code).where(Module.id == module_id))).scalar_one_or_none()
        if module_code is None:
            raise AppError(code="resource_not_found", message="Ressource introuvable.", status_code=404)

        capacites = None if exige_entitlement is None else {action: exige_entitlement}
        evaluation = await evaluer_acces_effectif(
            db,
            user_id=current_user.id,
            organization_id=organization_id,
            module_code=module_code,
            action=action,
            capacites=capacites,
            module_actif_requis=module_actif_requis,
        )
        if evaluation.motif == MOTIF_NON_MEMBRE:
            raise AppError(code="organization_not_found", message="Organisation introuvable.", status_code=404)
        if not evaluation.autorise:
            raise AppError(code="ACCESS_DENIED", message="Accès refusé à ce module.", status_code=403)

    return dependency
