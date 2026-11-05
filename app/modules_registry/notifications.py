"""Notifications de suspension, fin et changement de disponibilité d'un module (BE-057).

Rôle : à partir de l'événement de transition publié par BE-056 (`audit_event`), écrire un élément
de la boîte de réception (capacité partagée `app.notifications`) pour chaque membre de
l'organisation qui détient `organization.module.read`. La notification est produite dans la même
transaction que la transition, par `publier_evenement_transition`.

Invariants :
- la notification ne contourne aucun droit : seul un membre qui a `organization.module.read`
  (calcul de `user_has_permission`, jamais une copie de la règle) reçoit un élément ;
- l'audience est tirée des membres de l'organisation de l'événement : une notification n'est
  jamais adressée à un membre d'une autre organisation (isolation) ;
- le contenu est un gabarit fixe : libellé de l'événement et états `fromState` -> `toState`.
  Le motif libre de la transition et tout secret sont absents ; l'événement ne les porte pas ;
- une même notification par (événement, destinataire) : l'idempotence est portée par la contrainte
  unique de `create_inbox_item` (`ON CONFLICT DO NOTHING`), un rejeu ne crée donc aucun doublon ;
- les transitions d'installation internes (préflight, provisionnement, mise à jour) ne notifient
  pas : seules les transitions visibles par le client (ci-dessous) produisent un élément.

Décisions (questions, à consigner en QE) :
- QE-MOD-17 : la file « module_notifications » recommandée par la définition (statut
  pending/sent/failed, tentatives) n'est pas créée. La boîte de réception existante fournit déjà
  l'idempotence et l'audience ; elle n'a pas d'état d'envoi. Un canal push ou une relance restent
  hors périmètre tant que le catalogue d'événements (PH-13) et la frontière Notifications/Alertes
  (ARC-007) ne sont pas validés (voir la docstring de `app.notifications.service`).
- Événements notifiés : `ModuleSuspended` (suspension), `ModuleReactivated` (reprise),
  `ModuleUninstalled` (fin) et `TenantModuleAvailabilityChanged` (active <-> inactive). Le choix
  des événements est une recommandation appliquée, faute de règle écrite dans la définition.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.identity.models import OrganizationUser
from app.modules_registry.permissions import ORGANIZATION_MODULE_READ
from app.notifications.models import NotificationInboxItem
from app.notifications.service import create_inbox_item
from app.rbac.service import user_has_permission

CATEGORIE_NOTIFICATION_MODULE = "modules"

# Événements de BE-056 dont un membre autorisé est informé. Les autres transitions restent
# silencieuses (voir la docstring du module).
EVENEMENTS_NOTIFIES: dict[str, str] = {
    "ModuleSuspended": "Module suspendu",
    "ModuleReactivated": "Module réactivé",
    "ModuleUninstalled": "Module désinstallé",
    "TenantModuleAvailabilityChanged": "Disponibilité du module modifiée",
}


def titre_notification(nom_evenement: str) -> str | None:
    """Libellé du titre pour `nom_evenement`, ou `None` si l'événement n'est pas notifié."""
    return EVENEMENTS_NOTIFIES.get(nom_evenement)


def corps_notification(payload: dict) -> str:
    """Corps du gabarit : seuls les états de la transition, jamais de motif ni d'acteur."""
    de_etat = payload.get("fromState", "?")
    vers_etat = payload.get("toState", "?")
    return f"État du module : {de_etat} -> {vers_etat}."


async def notifier_destinataires_evenement(db: AsyncSession, evenement: AuditEvent) -> list[NotificationInboxItem]:
    """Écrit un élément par membre autorisé pour un événement de transition notifié.

    Renvoie les éléments créés ou déjà présents (idempotence). Un événement sans organisation
    (transition de plateforme) ou non notifié ne produit rien. Les destinataires sont les membres
    de l'organisation de l'événement dont `user_has_permission(organization.module.read)` est vrai.
    """
    titre = titre_notification(evenement.eventName)
    if titre is None or evenement.organizationId is None:
        return []

    membres = (
        (await db.execute(select(OrganizationUser.userId).where(OrganizationUser.organizationId == evenement.organizationId)))
        .scalars()
        .all()
    )
    elements: list[NotificationInboxItem] = []
    for membre_id in membres:
        if not await user_has_permission(db, membre_id, evenement.organizationId, ORGANIZATION_MODULE_READ):
            continue
        elements.append(
            await create_inbox_item(
                db,
                organization_id=evenement.organizationId,
                recipient_user_id=membre_id,
                source_event_type=evenement.eventName,
                source_event_id=uuid.UUID(evenement.eventId),
                category=CATEGORIE_NOTIFICATION_MODULE,
                title=titre,
                body=corps_notification(evenement.payloadMinimal or {}),
            )
        )
    return elements
