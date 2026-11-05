"""BE-057 : notifications de suspension, fin et changement d'état d'un module.

Tests écrits d'après la définition (implementation-backend/tasks-modules-droits.md, section BE-057)
avant le code. Critères couverts :
- CA-1 : une suspension produit une notification par destinataire autorisé, une seule fois
  (test de doublon : rejouer la notification ne crée aucun élément de plus) ;
- CA-2 : un destinataire sans `organization.module.read` ne reçoit aucune notification (refus) ;
- CA-3 : une notification ne contient ni secret ni contenu métier (motif libre absent, gabarit) ;
- CA-4 : une notification d'une organisation n'est jamais adressée à un membre d'une autre
  organisation (isolation).

Chemin testé : les transitions passent par `transitionner` (BE-041), qui publie l'événement de
transition (BE-056) ; la notification est produite à partir de cet événement, une fois par
transition réussie. Les éléments sont écrits via `app.notifications.service.create_inbox_item`
(boîte de réception existante, idempotence sur `(organisation, destinataire, type, eventId)`).

Points de la définition non tranchés dans ces tests :
- QE-MOD-17 : la file de notifications n'est pas définie. Le recommandé (table `module_notifications`
  avec `status pending|sent|failed` et `attempts`) n'est pas créé : la boîte de réception existante
  est réutilisée, sans état d'envoi ni relance. Les tests ne vérifient donc ni `status` ni `attempts`.
- QE-MOD-16 : `organization.module.read` est déclaré dans `permissions.py` ; la ligne de permission
  est créée ici par `get_or_create_permission`, comme le fait le seed du module.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser, User
from app.modules_registry.permissions import ORGANIZATION_MODULE_READ
from app.notifications.models import NotificationInboxItem
from app.rbac.models import UserPermissionGrant
from app.rbac.service import get_or_create_permission

MOT_DE_PASSE = "TestPassword123!"
TYPE_SUJET = "tenant_module"
MOTIF_SECRET = "MOTIF-CONFIDENTIEL-BE057-7731"
CLES_SENSIBLES = ("password", "token", "secret", "cookie", "apikey", "hash")


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _membre(client: AsyncClient, organisation: uuid.UUID, avec_lecture_module: bool) -> uuid.UUID:
    """Crée un utilisateur rattaché à `organisation`. Si `avec_lecture_module`, lui accorde
    `organization.module.read` par un grant individuel `allow` sur toute l'organisation."""
    email = f"be057-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Membre BE-057"})
    identifiant = await _id_utilisateur(email)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organisation, userId=identifiant))
        if avec_lecture_module:
            permission = await get_or_create_permission(db, ORGANIZATION_MODULE_READ, "modules", "Lecture des modules")
            db.add(
                UserPermissionGrant(
                    organizationId=organisation, userId=identifiant, permissionId=permission.id, effect="allow",
                    resourceType=None, resourceId=None,
                )
            )
        await db.commit()
    return identifiant


async def _cycle_jusqu_a_suspension(organisation: uuid.UUID, acteur: uuid.UUID, module: uuid.UUID, sujet: uuid.UUID,
                                    motif: str | None = None) -> str:
    """Enchaîne not_installed -> provisioning -> installed -> active -> suspended. Renvoie l'identifiant
    de l'événement de suspension (eventId de la ligne `audit_event`)."""
    from app.modules_registry.transitions import transitionner

    etapes = [("provisioning", 0), ("installed", 1), ("active", 2), ("suspended", 3)]
    async with AsyncSessionLocal() as db:
        for indice, (vers_etat, version) in enumerate(etapes):
            await transitionner(
                db, type_sujet=TYPE_SUJET, id_sujet=sujet, vers_etat=vers_etat, version_attendue=version,
                acteur_id=acteur, origine="client", cle_idempotence=f"be057-{sujet}-{indice}",
                organisation_id=organisation, module_id=module,
                motif=motif if vers_etat == "suspended" else None,
            )
        await db.commit()
    from app.audit.models import AuditEvent

    async with AsyncSessionLocal() as db:
        evenement = (
            await db.execute(
                select(AuditEvent).where(AuditEvent.subjectId == sujet, AuditEvent.eventName == "ModuleSuspended")
            )
        ).scalar_one()
        return evenement.eventId


async def _elements_du_evenement(evenement_id: str) -> list[NotificationInboxItem]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(NotificationInboxItem).where(NotificationInboxItem.sourceEventId == uuid.UUID(evenement_id))
                )
            ).scalars().all()
        )


async def test_ca1_suspension_une_notification_par_destinataire_autorise(client: AsyncClient, registered_user: dict, organization: dict):
    organisation = uuid.UUID(organization["id"])
    acteur = await _id_utilisateur(registered_user["email"])
    destinataire_a = await _membre(client, organisation, avec_lecture_module=True)
    destinataire_b = await _membre(client, organisation, avec_lecture_module=True)
    sans_droit = await _membre(client, organisation, avec_lecture_module=False)

    evenement_id = await _cycle_jusqu_a_suspension(organisation, acteur, uuid.uuid4(), uuid.uuid4())

    elements = await _elements_du_evenement(evenement_id)
    destinataires = {element.recipientUserId for element in elements}
    assert len(elements) == 2
    assert destinataires == {destinataire_a, destinataire_b}
    assert sans_droit not in destinataires


async def test_ca1_rejeu_de_la_notification_ne_cree_aucun_doublon(client: AsyncClient, registered_user: dict, organization: dict):
    from app.audit.models import AuditEvent
    from app.modules_registry.notifications import notifier_destinataires_evenement

    organisation = uuid.UUID(organization["id"])
    acteur = await _id_utilisateur(registered_user["email"])
    await _membre(client, organisation, avec_lecture_module=True)
    evenement_id = await _cycle_jusqu_a_suspension(organisation, acteur, uuid.uuid4(), uuid.uuid4())
    avant = len(await _elements_du_evenement(evenement_id))

    async with AsyncSessionLocal() as db:
        evenement = (await db.execute(select(AuditEvent).where(AuditEvent.eventId == evenement_id))).scalar_one()
        await notifier_destinataires_evenement(db, evenement)
        await notifier_destinataires_evenement(db, evenement)
        await db.commit()

    assert avant == 1
    assert len(await _elements_du_evenement(evenement_id)) == avant


async def test_ca2_destinataire_sans_permission_ne_recoit_aucune_notification(client: AsyncClient, registered_user: dict, organization: dict):
    organisation = uuid.UUID(organization["id"])
    acteur = await _id_utilisateur(registered_user["email"])
    sans_droit = await _membre(client, organisation, avec_lecture_module=False)

    evenement_id = await _cycle_jusqu_a_suspension(organisation, acteur, uuid.uuid4(), uuid.uuid4())

    async with AsyncSessionLocal() as db:
        recus = await db.scalar(
            select(func.count()).select_from(NotificationInboxItem).where(NotificationInboxItem.recipientUserId == sans_droit)
        )
    assert recus == 0
    assert await _elements_du_evenement(evenement_id) == []


async def test_ca3_notification_sans_secret_ni_motif_libre(client: AsyncClient, registered_user: dict, organization: dict):
    organisation = uuid.UUID(organization["id"])
    acteur = await _id_utilisateur(registered_user["email"])
    await _membre(client, organisation, avec_lecture_module=True)

    evenement_id = await _cycle_jusqu_a_suspension(organisation, acteur, uuid.uuid4(), uuid.uuid4(), motif=MOTIF_SECRET)

    elements = await _elements_du_evenement(evenement_id)
    assert elements
    for element in elements:
        contenu = f"{element.title} {element.body}".lower()
        assert MOTIF_SECRET.lower() not in contenu
        assert not any(cle in contenu for cle in CLES_SENSIBLES)
        assert len(element.body) <= 5000


async def test_ca4_notification_jamais_adressee_a_une_autre_organisation(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_a = uuid.UUID(organization["id"])
    acteur = await _id_utilisateur(registered_user["email"])
    membre_a = await _membre(client, organisation_a, avec_lecture_module=True)

    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Org B BE-057", "slug": f"be057-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    assert res.status_code in (200, 201), res.text
    organisation_b = uuid.UUID(res.json()["id"])
    membre_b = await _membre(client, organisation_b, avec_lecture_module=True)

    evenement_id = await _cycle_jusqu_a_suspension(organisation_a, acteur, uuid.uuid4(), uuid.uuid4())

    elements = await _elements_du_evenement(evenement_id)
    assert {element.recipientUserId for element in elements} == {membre_a}
    assert all(element.organizationId == organisation_a for element in elements)
    assert membre_b not in {element.recipientUserId for element in elements}
