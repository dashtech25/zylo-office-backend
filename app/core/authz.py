"""Moteur d'autorisation unique et enforcement (BE-226).

Intention : une seule fonction décide si une action est permise, `decide`.
Toute route, tâche, export et action d'intégration passe par elle (directement
ou via la garde FastAPI `exiger_acces`). Aucune autre couche ne refait ce calcul.
Ce module ne crée aucune règle de droit nouvelle : il assemble, dans un ordre
fixe, les briques déjà en place (rbac/service.py, rbac/module_policy.py,
modules_registry/service.py, billing/entitlements via modules_registry).

Formule appliquée, dans cet ordre ; la première porte qui échoue donne le motif :

    authenticated AND active_membership AND tenant_scope AND role_permission
    AND entitlement AND module_state AND quota AND policy

Table des décisions (motif normalisé -> réponse HTTP) :

| Motif                     | Porte              | Statut | Code d'erreur                    |
|---------------------------|--------------------|--------|----------------------------------|
| `ok`                      | toutes passées     | 200    | (aucun)                          |
| `authentication_required` | authenticated      | 401    | `authentication_required`        |
| `membership_inactive`     | active_membership  | 404    | `organization_not_found`         |
| `out_of_scope`            | tenant_scope       | 404    | `resource_not_found`             |
| `permission_missing`      | role_permission    | 403    | `permission_denied`              |
| `entitlement_missing`     | entitlement        | 403    | `module_entitlement_unavailable` |
| `module_inactive`         | module_state       | 403    | `module_inactive`                |
| `quota_exceeded`          | quota              | 403    | `quota_exceeded`                 |
| `policy_denied`           | policy             | 403    | `policy_denied`                  |

Règles de réponse :
- 404 quand la ressource est hors du tenant, inexistante, ou quand l'utilisateur
  n'est pas membre actif : aucune énumération possible (même réponse que
  `organisation_introuvable` dans rbac/guards.py).
- 403 quand la ressource est dans le tenant mais l'action n'est pas permise.
- Une décision n'utilise jamais une information venant de l'interface : pas de
  paramètre de rôle ou de droit affiché. Seul l'état serveur compte.
- Aucun cache : chaque décision relit la base, donc un retrait de permission
  prend effet à l'action suivante (CA-2).

Quota : la porte est branchée par l'appelant (`quota`, awaitable qui retourne
un booléen). Le comptage réel des usages par type de quota n'est PAS implémenté
ici : c'est une question ouverte à traiter séparément. Sans `quota` fourni, la
porte n'est pas évaluée ; ce choix est explicite, pas un oubli silencieux.

Tâches asynchrones : `decide_pour_tache` juge la tâche sur les droits de son
initiateur, relus à l'exécution. Aucun repli sur le propriétaire ni sur un
compte système : une tâche sans initiateur n'a aucun droit (CA-4).

Tests de référence : tests/test_be226_moteur_autorisation.py.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import Organization, OrganizationUser, User
from app.modules_registry.service import get_module_entitlement_access, is_module_active
from app.rbac.guards import get_current_organization_id
from app.rbac.models import Permission
from app.rbac.module_policy import permission_belongs_to_module
from app.rbac.service import user_has_permission

# Motifs normalisés. Stables : les journaux (BE-227) et les tests les utilisent.
MOTIF_OK = "ok"
AUTHENTIFICATION_REQUISE = "authentication_required"
ADHESION_INACTIVE = "membership_inactive"
HORS_PORTEE = "out_of_scope"
PERMISSION_ABSENTE = "permission_missing"
ENTITLEMENT_ABSENT = "entitlement_missing"
MODULE_INACTIF = "module_inactive"
QUOTA_DEPASSE = "quota_exceeded"
POLITIQUE_REFUSEE = "policy_denied"


@dataclass(frozen=True)
class Decision:
    """Résultat d'une décision. `status_code` et `error_code` ne sont renseignés
    que si l'accès est refusé ; `reason` est le motif normalisé ci-dessus."""

    allowed: bool
    reason: str
    status_code: int | None = None
    error_code: str | None = None


def _refus(reason: str, status_code: int, error_code: str) -> Decision:
    return Decision(allowed=False, reason=reason, status_code=status_code, error_code=error_code)


_ACCORDEE = Decision(allowed=True, reason=MOTIF_OK)


async def _membre_actif(db: AsyncSession, user_id: uuid.UUID, organization_id: uuid.UUID) -> bool:
    """Vrai si l'utilisateur a une adhésion à une organisation non supprimée.
    Version booléenne de rbac/guards.assert_active_membership (qui lève)."""
    stmt = (
        select(OrganizationUser.id)
        .join(Organization, Organization.id == OrganizationUser.organizationId)
        .where(
            OrganizationUser.organizationId == organization_id,
            OrganizationUser.userId == user_id,
            Organization.deletedAt.is_(None),
        )
    )
    return (await db.execute(stmt)).first() is not None


async def decide(
    db: AsyncSession,
    *,
    user: User | None,
    organization_id: uuid.UUID,
    permission_code: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    resource_organization_id: uuid.UUID | None = None,
    module_code: str | None = None,
    quota: Callable[[], Awaitable[bool]] | None = None,
) -> Decision:
    """Décide si `user` peut exercer `permission_code` dans `organization_id`.

    Paramètres :
    - `user` : utilisateur authentifié, ou None (refus 401).
    - `resource_type` / `resource_id` : ressource visée, pour la portée des rôles
      et grants (rbac/service.py). Facultatifs : sans eux, la décision porte sur
      l'organisation entière.
    - `resource_organization_id` : tenant réel de la ressource, résolu par
      l'appelant. None avec `resource_id` renseigné signifie « ressource
      inexistante » (404).
    - `module_code` : module auquel l'action appartient. Active les portes
      entitlement, état de module et politique de module.
    - `quota` : porte optionnelle, awaitable qui retourne True si l'usage reste
      dans la limite.

    Retour : `Decision` ; ne lève jamais d'exception pour un refus.
    """
    # 1. authenticated
    if user is None:
        return _refus(AUTHENTIFICATION_REQUISE, 401, "authentication_required")

    # 2. active_membership : non-membre = même réponse qu'un tenant inexistant.
    if not await _membre_actif(db, user.id, organization_id):
        return _refus(ADHESION_INACTIVE, 404, "organization_not_found")

    # 3. tenant_scope : la ressource doit appartenir à ce tenant.
    if resource_id is not None and resource_organization_id != organization_id:
        return _refus(HORS_PORTEE, 404, "resource_not_found")

    # 4. role_permission : rôles, grants allow/deny, portée d'attribution.
    if not await user_has_permission(db, user.id, organization_id, permission_code, resource_type, resource_id):
        return _refus(PERMISSION_ABSENTE, 403, "permission_denied")

    if module_code is not None:
        # 5. entitlement : l'abonnement couvre-t-il le module ?
        _etat, entitlement_ok = await get_module_entitlement_access(db, organization_id, module_code)
        if not entitlement_ok:
            return _refus(ENTITLEMENT_ABSENT, 403, "module_entitlement_unavailable")

        # 6. module_state : module disponible au registre et activé pour l'organisation.
        if not await is_module_active(db, organization_id, module_code):
            return _refus(MODULE_INACTIF, 403, "module_inactive")

    # 7. quota : porte branchée par l'appelant, non évaluée si absente.
    if quota is not None and not await quota():
        return _refus(QUOTA_DEPASSE, 403, "quota_exceeded")

    # 8. policy : la permission doit appartenir au module ou au socle partagé.
    if module_code is not None:
        permission_module = (
            await db.execute(select(Permission.moduleCode).where(Permission.code == permission_code))
        ).scalar_one_or_none()
        if permission_module is None or not permission_belongs_to_module(
            permission_code, permission_module, module_code
        ):
            return _refus(POLITIQUE_REFUSEE, 403, "policy_denied")

    return _ACCORDEE


async def decide_pour_tache(
    db: AsyncSession,
    *,
    initiateur_id: uuid.UUID | None,
    organization_id: uuid.UUID,
    permission_code: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    resource_organization_id: uuid.UUID | None = None,
    module_code: str | None = None,
    quota: Callable[[], Awaitable[bool]] | None = None,
) -> Decision:
    """Décision pour une tâche asynchrone (CA-4).

    La tâche est jugée sur les droits de son initiateur, relus au moment de
    l'exécution. Sans initiateur identifié, aucun droit n'est accordé. Le
    propriétaire ou un compte système n'est jamais utilisé en repli : une tâche
    ne peut pas dépasser le compte qui l'a lancée.
    """
    if initiateur_id is None:
        return _refus(AUTHENTIFICATION_REQUISE, 401, "authentication_required")
    initiateur = (await db.execute(select(User).where(User.id == initiateur_id))).scalar_one_or_none()
    return await decide(
        db,
        user=initiateur,
        organization_id=organization_id,
        permission_code=permission_code,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_organization_id=resource_organization_id,
        module_code=module_code,
        quota=quota,
    )


_ERREURS_HTTP = {
    AUTHENTIFICATION_REQUISE: ("authentication_required", "Authentification requise.", 401),
    ADHESION_INACTIVE: ("organization_not_found", "Organisation introuvable.", 404),
    HORS_PORTEE: ("resource_not_found", "Ressource introuvable.", 404),
    PERMISSION_ABSENTE: ("permission_denied", "Permission manquante.", 403),
    ENTITLEMENT_ABSENT: ("module_entitlement_unavailable", "Module non couvert par l'abonnement.", 403),
    MODULE_INACTIF: ("module_inactive", "Module inactif pour cette organisation.", 403),
    QUOTA_DEPASSE: ("quota_exceeded", "Quota atteint.", 403),
    POLITIQUE_REFUSEE: ("policy_denied", "Action non autorisée par la politique du module.", 403),
}


def exiger_acces(
    permission_code: str,
    *,
    resource_type: str | None = None,
    resource_param: str | None = None,
    resolve_resource_org: Callable[[AsyncSession, uuid.UUID | None], Awaitable[uuid.UUID | None]] | None = None,
    module_code: str | None = None,
):
    """Garde FastAPI : appelle `decide` et lève une `AppError` si l'accès est refusé.

    - `resource_param` : nom du paramètre de chemin qui désigne la ressource ;
    - `resolve_resource_org` : fonction `(db, resource_id) -> tenant réel`, fournie
      par le domaine qui possède la ressource ; None si inexistante.

    La garde ne lit aucun en-tête d'interface (CA-5). Le tenant vient de
    `get_current_organization_id`, qui exige déjà une adhésion active.
    """

    async def dependency(
        request: Request,
        current_user: User = Depends(get_current_user),
        organization_id: uuid.UUID = Depends(get_current_organization_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        resource_id: uuid.UUID | None = None
        resource_org: uuid.UUID | None = None
        if resource_param is not None:
            brut = request.path_params.get(resource_param)
            if brut is not None:
                resource_id = uuid.UUID(str(brut))
                if resolve_resource_org is not None:
                    resource_org = await resolve_resource_org(db, resource_id)
        decision = await decide(
            db,
            user=current_user,
            organization_id=organization_id,
            permission_code=permission_code,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_organization_id=resource_org,
            module_code=module_code,
        )
        if not decision.allowed:
            code, message, status = _ERREURS_HTTP[decision.reason]
            raise AppError(code=code, message=message, status_code=status)

    return dependency
