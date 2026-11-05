"""BE-238 : livraison, préférences et résultat d'envoi des notifications.

Tests écrits d'après la définition `### BE-238` de
implementation-backend/tasks-exploitation-architecture.md, avant le code.

Couverture (un test par critère d'acceptation, plus les refus) :
- CA-1 : un destinataire est résolu dans le bon tenant ; un membre d'un autre
  tenant ne peut pas recevoir l'item (test d'isolation) ;
- CA-2 : un doublon d'événement source est supprimé par la clé de déduplication ;
- CA-3 : un envoi en échec enregistre le résultat `echec` dans
  `notification_delivery` et ne déclare pas l'envoi (`statut` de la notification) ;
- CA-4 : lecture et modification de la notification d'autrui donnent 404 ;
- CA-5 : un canal sans consentement n'est pas utilisé (aucun appel au canal,
  aucune ligne de livraison).

Écarts de contrat relevés (QE, pas présumés ici) :
- la définition nomme `PATCH /api/v1/notifications/{id}` et
  `PUT /api/v1/notifications/preferences` ; le code existant sert
  `PATCH /api/v1/notifications/inbox/{itemId}` (BE-035) et
  `PUT /api/v1/notifications/preferences/{categorie}` (BE-168). Les tests suivent
  le contrat existant : la route de la définition n'est pas ajoutée ici ;
- la définition nomme `notification_preferences` avec une colonne `canal` ; la table
  existante `preference_notification` n'a pas de canal (QE-PAR-04, non tranché). Le
  consentement est donc porté par catégorie, comme en BE-168.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.core.security import hash_password
from app.identity.models import OrganizationUser, User
from app.identity.schemas import CreateOrganizationRequest
from app.identity.service import create_organization
from app.notifications import service as notifications_service
from app.notifications.categories import creer_categorie
from app.notifications.livraison import livrer_notification
from app.notifications.models import Notification, NotificationDelivery, NotificationInboxItem
from app.notifications.preferences import modifier_preference

INBOX_URL = "/api/v1/notifications/inbox"
CANAL = "web_push"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé avant et après."""
    await engine.dispose()
    yield
    await engine.dispose()


def _suffixe() -> str:
    return uuid.uuid4().hex[:10]


async def _utilisateur(db, label: str) -> User:
    user = User(
        email=f"be238-{label}-{_suffixe()}@example.com",
        hashedPassword=hash_password("x"),
        fullName=label,
        status="active",
    )
    db.add(user)
    await db.flush()
    return user


async def _organisation(db, owner: User) -> uuid.UUID:
    org = await create_organization(
        db, owner, CreateOrganizationRequest(name=f"BE238 {_suffixe()}", slug=f"be238-{_suffixe()}")
    )
    await db.commit()
    return org.id


async def _membre(db, organization_id: uuid.UUID, user: User) -> None:
    db.add(OrganizationUser(organizationId=organization_id, userId=user.id))
    await db.flush()


async def _item(db, organization_id: uuid.UUID, recipient_id: uuid.UUID, event_id: uuid.UUID) -> NotificationInboxItem:
    return await notifications_service.create_inbox_item(
        db,
        organization_id=organization_id,
        recipient_user_id=recipient_id,
        source_event_type="BE238.Test",
        source_event_id=event_id,
        category="test",
        title="Titre",
        body="Corps",
    )


async def _notification(db, destinataire_id: uuid.UUID) -> Notification:
    """Une notification moteur (BE-169) rattachée à une catégorie de test."""
    code = f"BE238-{_suffixe()}"
    await creer_categorie(db, code=code, libelle="Catégorie BE-238", audience_regle="membres_organisation")
    notification = Notification(
        eventId=uuid.uuid4(),
        categorieCode=code,
        destinataireId=destinataire_id,
        statut="en_attente",
    )
    db.add(notification)
    await db.commit()
    return notification


async def _livraisons(notification_id: uuid.UUID) -> list[NotificationDelivery]:
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(
            select(NotificationDelivery).where(NotificationDelivery.notificationId == notification_id)
        )
        return list(resultat.scalars().all())


async def test_ca1_destinataire_resolu_dans_le_bon_tenant_et_isole():
    """CA-1 : l'item est porté par le tenant de l'événement et par un membre de ce tenant.
    Un utilisateur qui n'est membre que d'un autre tenant ne peut pas le recevoir."""
    async with AsyncSessionLocal() as db:
        proprietaire_a = await _utilisateur(db, "a")
        org_a = await _organisation(db, proprietaire_a)
        proprietaire_b = await _utilisateur(db, "b")
        org_b = await _organisation(db, proprietaire_b)
        etranger = await _utilisateur(db, "etranger")
        await _membre(db, org_b, etranger)
        await db.commit()

        item = await _item(db, org_a, proprietaire_a.id, uuid.uuid4())
        assert item.organizationId == org_a
        assert item.recipientUserId == proprietaire_a.id

        with pytest.raises(AppError):
            await _item(db, org_a, etranger.id, uuid.uuid4())


async def test_ca2_doublon_supprime_par_cle_de_deduplication():
    """CA-2 : le même événement source pour le même destinataire ne produit qu'une ligne."""
    async with AsyncSessionLocal() as db:
        owner = await _utilisateur(db, "dedup")
        org = await _organisation(db, owner)
        evenement = uuid.uuid4()

        premier = await _item(db, org, owner.id, evenement)
        second = await _item(db, org, owner.id, evenement)
        await db.commit()

        assert premier.id == second.id
        compte = await db.scalar(
            select(func.count()).select_from(NotificationInboxItem).where(
                NotificationInboxItem.organizationId == org,
                NotificationInboxItem.recipientUserId == owner.id,
                NotificationInboxItem.sourceEventId == evenement,
            )
        )
        assert compte == 1


async def test_ca3_echec_de_canal_enregistre_le_resultat_sans_declarer_lenvoi():
    """CA-3 : un canal en échec laisse une ligne `echec` dans `notification_delivery`
    et la notification n'est pas marquée `envoyee`."""
    async with AsyncSessionLocal() as db:
        destinataire = await _utilisateur(db, "echec")
        await db.commit()
        notification = await _notification(db, destinataire.id)
        notification_id = notification.id

    appels: list[uuid.UUID] = []

    def canal_en_panne(notification_recue: Notification) -> None:
        appels.append(notification_recue.id)
        raise ConnectionError("canal indisponible")

    async with AsyncSessionLocal() as db:
        notification = await db.get(Notification, notification_id)
        await livrer_notification(db, notification=notification, canal=CANAL, envoi=canal_en_panne)
        await db.refresh(notification)
        assert notification.statut == "echec"

    assert appels == [notification_id]
    livraisons = await _livraisons(notification_id)
    assert len(livraisons) == 1
    assert livraisons[0].canal == CANAL
    assert livraisons[0].resultat == "echec"
    assert livraisons[0].tentative == 1
    assert livraisons[0].horodatage is not None


async def test_ca4_notification_dautrui_donne_404_en_lecture_et_en_modification(client, registered_user, organization):
    """CA-4 : un autre membre de la même organisation ne lit ni ne modifie l'item : 404."""
    proprietaire = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    org_id = uuid.UUID(organization["id"])
    async with AsyncSessionLocal() as db:
        owner_id = await db.scalar(select(User.id).where(User.email == registered_user["email"]))
        item = await _item(db, org_id, owner_id, uuid.uuid4())
        item_id = item.id
        await db.commit()

    # Second compte de la même organisation, connecté par l'API (mot de passe connu).
    email_autre = f"be238-autre-{_suffixe()}@example.com"
    mot_de_passe = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email_autre, "password": mot_de_passe, "fullName": "Autre"})
    login = (await client.post("/api/v1/auth/login", json={"email": email_autre, "password": mot_de_passe})).json()
    async with AsyncSessionLocal() as db:
        autre_id = await db.scalar(select(User.id).where(User.email == email_autre))
        db.add(OrganizationUser(organizationId=org_id, userId=autre_id))
        await db.commit()
    autre = {"Authorization": f"Bearer {login['accessToken']}", "X-Organization-Id": organization["id"]}

    assert (await client.get(f"{INBOX_URL}/{item_id}", headers=proprietaire)).status_code == 200
    assert (await client.get(f"{INBOX_URL}/{item_id}", headers=autre)).status_code == 404
    assert (await client.patch(f"{INBOX_URL}/{item_id}", headers=autre)).status_code == 404


async def test_ca5_canal_sans_consentement_nest_pas_utilise():
    """CA-5 : après désinscription de la catégorie, le canal n'est pas appelé et
    aucune ligne de livraison n'est écrite ; l'erreur est CONSENT_SUPPRESSED."""
    async with AsyncSessionLocal() as db:
        owner = await _utilisateur(db, "consent")
        org = await _organisation(db, owner)
        await _membre(db, org, owner)
        await db.commit()
        notification = await _notification(db, owner.id)
        await modifier_preference(
            db,
            organization_id=org,
            acteur_id=owner.id,
            utilisateur_id=owner.id,
            categorie_code=notification.categorieCode,
            consentement=False,
        )
        notification_id = notification.id

    appels: list[uuid.UUID] = []

    async with AsyncSessionLocal() as db:
        notification = await db.get(Notification, notification_id)
        with pytest.raises(AppError) as erreur:
            await livrer_notification(db, notification=notification, canal=CANAL, envoi=lambda n: appels.append(n.id))

    assert erreur.value.code == "CONSENT_SUPPRESSED"
    assert appels == []
    assert await _livraisons(notification_id) == []
