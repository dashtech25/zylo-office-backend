"""Contexte tenant serveur (BE-225).

Rôle : fournir à toute route tenant un contexte résolu côté serveur, dont le
tenant vient toujours de l'adhésion active de l'utilisateur, jamais d'une
valeur que le navigateur a choisie librement.

Ce module ne contient aucune règle de sécurité nouvelle. Il s'appuie sur les
fonctions déjà en place dans `app/rbac/service.py` :
- `get_current_organization_id` : lit le sélecteur (en-tête `X-Organization-Id`
  ou chemin `{organization_id}`), refuse toute incohérence entre les deux, puis
  exige une adhésion active (`assert_active_membership`) ;
- `organisation_introuvable` : l'erreur uniforme 404 `organization_not_found`,
  identique pour « inexistant », « sans adhésion » et « incohérent », afin
  qu'aucun identifiant de tenant ne puisse être énuméré.

Ce qui est ajouté ici :
- `TenantContext`, valeur immuable transmise aux routes ;
- `get_tenant_context`, dépendance FastAPI unique à utiliser par les routes
  qui ont besoin du tenant et de l'utilisateur ensemble ;
- `valider_tenant_du_corps`, revalidation d'un tenant cité dans le corps d'une
  requête contre le contexte serveur (CA-2).

Invariants :
- le tenant du contexte est toujours celui de l'adhésion active au moment de
  la requête ; aucun cache n'est tenu entre requêtes, donc un retrait
  d'adhésion (CA-4) prend effet immédiatement, sans étape d'invalidation ;
- un tenant cité dans le corps n'est jamais utilisé à la place du contexte :
  il est seulement comparé, et toute différence est refusée.

Dépendances : ce module est un point de passage du socle. Il importe
`app.rbac.service` ; l'inverse n'est pas vrai, car `rbac` n'importe jamais ce
module.
"""

import uuid
from dataclasses import dataclass

from fastapi import Depends

from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.service import get_current_organization_id, organisation_introuvable


@dataclass(frozen=True)
class TenantContext:
    """Contexte d'une requête tenant, validé par `get_tenant_context`.

    `organization_id` est le tenant sur lequel la requête agit ; `user_id` est
    l'utilisateur authentifié qui agit. Les deux valeurs sont immuables pour la
    durée de la requête.
    """

    organization_id: uuid.UUID
    user_id: uuid.UUID


async def get_tenant_context(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
) -> TenantContext:
    """Dépendance FastAPI : construit le contexte tenant de la requête.

    Erreurs :
    - 401 si le jeton est absent ou invalide (levé par `get_current_user`) ;
    - 404 `organization_not_found` si l'en-tête ou le chemin ne désigne pas une
      organisation dont l'utilisateur est membre actif (levé par
      `get_current_organization_id`).

    FastAPI met en cache chaque dépendance par requête : la résolution de
    l'organisation n'est faite qu'une fois, même si plusieurs dépendances la
    demandent.
    """
    return TenantContext(organization_id=organization_id, user_id=current_user.id)


def valider_tenant_du_corps(contexte: TenantContext, organization_id_corps: uuid.UUID | None) -> None:
    """Revalide le tenant cité dans le corps d'une requête (CA-2).

    Règles :
    - corps sans tenant (`None`) : accepté, le contexte fait foi ;
    - corps citant le tenant du contexte : accepté ;
    - corps citant un autre tenant : refus 404 `organization_not_found`, même
      réponse que pour un tenant inexistant ou sans adhésion. Le corps n'est
      jamais utilisé pour changer de tenant.

    Cette fonction doit être appelée avant toute lecture ou écriture qui se
    fonde sur le tenant du corps.
    """
    if organization_id_corps is None:
        return
    if organization_id_corps != contexte.organization_id:
        raise organisation_introuvable()
