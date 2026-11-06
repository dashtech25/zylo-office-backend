"""Garde de portée organisation et autorisation par défaut (BE-101).

Intention : chaque route `/api/v1/organizations/{organization_id}/...` du portail
résout sa portée (`OrgScope`) depuis le chemin seul, la revalide à chaque appel,
et refuse par défaut : une action absente de la politique est refusée. Le
sélecteur envoyé par le navigateur (en-tête `X-Organization-Id`, corps, requête)
n'est pas lu ici ; il ne modifie jamais la portée.

Périmètre distinct de BE-009 (rbac/guards.py, garde générique du contexte) : pas
de comparaison chemin/en-tête, politique propre au portail (QE-POR-27). La
réponse 404 d'une organisation hors appartenance, inexistante ou mal formée est
celle de `rbac.guards.organisation_introuvable` (non-énumération).

Réponses :
- session absente ou invalide : 401 (refusé par `get_current_user`) ;
- organisation hors appartenance, inexistante, supprimée ou identifiant mal formé :
  404 `organization_not_found`, réponse uniforme ;
- action absente de `POLITIQUE_PORTAIL` : 403 `policy_denied` ;
- permission absente pour l'action : 403 `permission_denied`.
"""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import assert_active_membership, organisation_introuvable
from app.rbac.service import user_has_permission

# Politique du portail : action -> permission exigée. Vide tant qu'aucune route du
# portail n'est livrée : toute action est alors refusée par défaut. Chaque tâche
# qui ajoute une route y inscrit son action et la permission correspondante.
# BE-108 : `portail.usage.lire` -> `organization.usage.read` (code porté par app/billing/permissions.py ;
# chaîne écrite ici car rbac ne doit pas importer la facturation).
# BE-105 : `portail.invitation.creer` -> `organization.members.invite` (permission d'invitation
# déjà seedée, identity/permissions.py ; la fiche écrit `members:manage`, voir docs/portail-organisation/invitations.md).
POLITIQUE_PORTAIL: dict[str, str] = {
    "portail.usage.lire": "organization.usage.read",
    # BE-116 : ajout, remplacement et sélection d'un moyen de paiement (chaîne écrite ici, comme BE-108).
    "portail.moyen_paiement.gerer": "billing.payment_method.manage",
    "portail.invitation.creer": "organization.members.invite",
}


@dataclass(frozen=True)
class OrgScope:
    """Portée résolue d'une requête du portail : l'organisation du chemin et
    l'utilisateur authentifié, déjà vérifié membre actif de cette organisation."""

    organization_id: uuid.UUID
    user_id: uuid.UUID


async def require_org_scope(
    organization_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrgScope:
    """Dépendance FastAPI : résout `OrgScope` depuis `{organization_id}` du chemin.

    Ordre : la session est vérifiée d'abord (401), puis l'identifiant est lu (un
    identifiant mal formé suit la réponse 404 d'une organisation absente), puis
    l'appartenance active est exigée. Le chemin est la seule source de la portée.
    """
    try:
        cible = uuid.UUID(organization_id)
    except ValueError:
        raise organisation_introuvable()
    await assert_active_membership(db, current_user.id, cible)
    return OrgScope(organization_id=cible, user_id=current_user.id)


async def evaluer_politique_portail(
    db: AsyncSession,
    scope: OrgScope,
    action: str,
    politique: Mapping[str, str] | None = None,
) -> None:
    """Décide si `scope.user_id` peut exécuter `action` dans `scope.organization_id`.

    Ne retourne rien si l'action est permise, et lève `AppError` sinon. Refus par
    défaut : une action absente de la politique est refusée (403 `policy_denied`),
    sans jamais supposer une permission. La permission exigée est ensuite
    vérifiée par `rbac.service.user_has_permission` (403 `permission_denied`).

    `politique` remplace `POLITIQUE_PORTAIL` ; elle sert aux tests et aux routes
    qui ont leur propre table. Sans elle, la politique du portail est utilisée.
    """
    table = POLITIQUE_PORTAIL if politique is None else politique
    permission = table.get(action)
    if permission is None:
        raise AppError(
            code="policy_denied",
            message="Action non autorisée par la politique du portail.",
            status_code=403,
        )
    if not await user_has_permission(db, scope.user_id, scope.organization_id, permission):
        raise AppError(
            code="permission_denied",
            message="Permission insuffisante pour cette action.",
            status_code=403,
        )


def exiger_action(action: str, politique: Mapping[str, str] | None = None) -> Callable:
    """Fabrique une dépendance FastAPI qui exige la portée et l'action donnée.

    Usage : `@routeur.get(..., dependencies=[Depends(exiger_action("portail.resume.lire"))])`.
    Toute route du portail l'utilise, afin que l'autorisation par défaut ne dépende
    pas d'un oubli dans le corps de la route.
    """

    async def dependance(
        scope: OrgScope = Depends(require_org_scope),
        db: AsyncSession = Depends(get_db),
    ) -> OrgScope:
        """Refuse la requête si l'action n'est pas permise, sinon renvoie la portée."""
        await evaluer_politique_portail(db, scope, action, politique)
        return scope

    return dependance
