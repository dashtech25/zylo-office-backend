"""Garde transversale anti cross-tenant des routes d'administration (BE-147).

Intention : une ressource d'un tenant n'est accessible qu'à une portée
d'administration qui couvre ce tenant. Deux niveaux de défense :

1. Déclaration de portée (couche routeur) : chaque routeur `/api/v1/admin`
   dépend de `require_admin_scope` (BE-120), monté dans
   `app/api/v1/router.py`. Une route sans portée échoue `tests/test_be147_*`.
2. Contrôle de cible (couche handler) : une route qui lit ou écrit une ressource
   portant un `organizationId` appelle `exiger_portee_sur_tenant` avec la cible.
   Ce module ne sait pas lire une ressource : c'est la route qui fournit
   l'organisation réellement visée.

Règle de couverture (`cross_tenant_autorise`) :

- portée `tenant:<A>` : couvre le seul tenant A ;
- portée plateforme : ne couvre pas le contenu d'un tenant (BE-120 CA-2), sauf
  si la route déclare `plateforme_couvre_tenant=True`, c'est-à-dire qu'elle
  n'expose que des données de console plateforme (ex. vue d'abonnement d'une
  organisation, BE-031), jamais du contenu client.

Refus : 403 `admin_scope_denied`, et une entrée `audit_event` de résultat
`refused` (action `ACTION_REFUS_CROSS_TENANT`) est commitée AVANT la levée :
la session de `get_db` n'a pas de commit automatique, sans ce commit le refus
serait perdu avec la transaction.

Ce module ne dépend pas de `app.operator.scope` (pas de cycle) : il reçoit des
valeurs simples, et `scope.py` l'importe pour journaliser le refus d'adhésion.

Aucune table ni migration : le journal est `audit_event` (BE-007, BE-122).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.admin_audit import ecrire_evenement_admin
from app.core.errors import AppError
from app.core.logging import request_id_ctx

ACTION_REFUS_CROSS_TENANT = "admin.scope.cross_tenant_refused"
TYPE_ENTITE_REFUS = "Organization"
RESUME_REFUS = "Accès d'administration refusé hors de la portée de l'appelant (cross-tenant)."


def cross_tenant_autorise(
    *,
    portee_platforme: bool,
    portee_organisation: uuid.UUID | None,
    organization_id: uuid.UUID,
    plateforme_couvre_tenant: bool = False,
) -> bool:
    """Vrai si la portée couvre la ressource du tenant `organization_id`.

    `portee_platforme` et `portee_organisation` décrivent la portée validée par
    `require_admin_scope` (une seule des deux formes est renseignée).
    """
    if portee_platforme:
        return plateforme_couvre_tenant
    return portee_organisation == organization_id


async def journaliser_refus_cross_tenant(
    db: AsyncSession,
    *,
    acteur_id: uuid.UUID,
    organization_id: uuid.UUID,
    portee: str,
) -> None:
    """Écrit l'entrée d'audit du refus et la commite.

    `organization_id` est le tenant ciblé (celui dont la ressource était
    demandée), `acteur_id` l'appelant. La corrélation vient du contexte de
    requête ; à défaut, un identifiant neuf évite le refus de BE-122 (422).
    `portee` (libellé court, sans secret) est gardé dans le résumé.
    """
    await ecrire_evenement_admin(
        db,
        organization_id=organization_id,
        actor_user_id=acteur_id,
        action=ACTION_REFUS_CROSS_TENANT,
        entity_type=TYPE_ENTITE_REFUS,
        entity_id=organization_id,
        summary=f"{RESUME_REFUS} Portée demandée : {portee}.",
        correlation_id=request_id_ctx.get() or str(uuid.uuid4()),
        result="refused",
    )
    await db.commit()


async def exiger_portee_sur_tenant(
    db: AsyncSession,
    *,
    acteur_id: uuid.UUID,
    portee_platforme: bool,
    portee_organisation: uuid.UUID | None,
    organization_id: uuid.UUID,
    plateforme_couvre_tenant: bool = False,
) -> None:
    """Lève 403 et journalise le refus si la portée ne couvre pas `organization_id`."""
    if cross_tenant_autorise(
        portee_platforme=portee_platforme,
        portee_organisation=portee_organisation,
        organization_id=organization_id,
        plateforme_couvre_tenant=plateforme_couvre_tenant,
    ):
        return
    portee = "plateforme" if portee_platforme else f"tenant:{portee_organisation}"
    await journaliser_refus_cross_tenant(db, acteur_id=acteur_id, organization_id=organization_id, portee=portee)
    raise AppError(
        code="admin_scope_denied",
        message="Accès d'administration refusé pour cette portée.",
        status_code=403,
    )
