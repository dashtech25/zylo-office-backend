"""Enveloppes d'événements de membership d'organisation (BE-106).

Intention : `RoleChanged` et `Removed` sont écrits dans l'outbox par les services qui modifient
un membre (`identity.membres.remove_member`, `rbac.affectation_membres.replace_member_roles`),
dans la même transaction que la modification. Ce module ne fait que construire l'enveloppe de
tenant (BE-150) ; il ne lit ni n'écrit rien. Le payload ne porte que des identifiants et des
listes de rôles, jamais d'adresse e-mail, de jeton ou de secret.
"""

import uuid
from datetime import datetime, timezone

EVENEMENT_ROLE_CHANGED = "RoleChanged"
EVENEMENT_REMOVED = "Removed"


def construire_evenement_membre(
    event_type: str,
    organization_id: uuid.UUID,
    acteur_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: dict,
) -> dict:
    """Enveloppe de tenant (BE-150) pour un membership de `organization_id`.

    `subject` désigne le membership (`organization_user.id`), pas l'utilisateur : le même
    utilisateur peut être membre de plusieurs organisations, chacune avec son propre membership.
    `payload` doit contenir `membershipId` et `userId` ; l'appelant y ajoute le détail utile.
    """
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": event_type,
        "schemaVersion": 1,
        "occurredAt": datetime.now(timezone.utc),
        "tenantId": str(organization_id),
        "scope": {"type": "organization", "id": str(organization_id)},
        "actor": {"type": "user", "id": str(acteur_id)},
        "subject": {"type": "membership", "id": str(membership_id)},
        "dataClassification": "internal",
        "correlationId": None,
        "causationId": None,
        "payload": {"organizationId": str(organization_id), "membershipId": str(membership_id), **payload},
    }
