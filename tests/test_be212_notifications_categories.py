"""BE-212 : notifications par catégorie.

Tests écrits d'après la définition `### BE-212` de
implementation-backend/tasks-donnees-api-contrats.md, avant le code.

Couverture :
- CA-1 : aucune notification ni préférence ne contient de secret ;
- CA-2 : la préférence d'un autre utilisateur n'est pas accessible ;
- CA-3 : une catégorie inconnue renvoie 422 et n'écrit rien ;
- CA-4 : une notification n'est envoyée qu'aux membres actifs de son tenant ;
- CA-5 : un envoi en échec est repris jusqu'à la limite (5, QE-API-16), puis passe en
  `echec` (état `failed` de la définition, vocabulaire existant de BE-169/BE-238).

Décisions prises à la place des écarts de la définition (voir le rapport) :
- les tables `notification` et `notification_preference` de la définition existent déjà
  sous d'autres formes (`notification` de BE-169, `preference_notification` de BE-168) :
  elles sont réutilisées, sans migration ni table dupliquée ;
- les routes sont `GET` et `PUT /api/v1/notification-preferences`, la catégorie passant
  dans le corps du `PUT` (aucun identifiant d'utilisateur dans le chemin) ;
- la catégorie se valide contre la table `categorie_notification` (liste configurable,
  QE-API-21).
"""

import re
import uuid

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser, User
from app.notifications import livraison, moteur
from app.notifications.categories import creer_categorie
from app.notifications.models import Notification, NotificationDelivery, PreferenceNotification

PREFERENCES_URL = "/api/v1/notification-preferences"
LIMITE_TENTATIVES_ATTENDUE = 5


@pytest.fixture(autouse=True)
async def _pool_neuf():
    """Même remise à zéro que les autres tests de notifications (moteur singleton)."""
    await engine.dispose()
    yield


def _code() -> str:
    return f"BE212-{uuid.uuid4().hex[:12]}"


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _categorie() -> str:
    code = _code()
    async with AsyncSessionLocal() as db:
        await creer_categorie(db, code=code, libelle="Catégorie BE-212", audience_regle="membres_organisation")
    return code


async def _utilisateur(organization_id: str | None = None, statut_membre: str = "active") -> uuid.UUID:
    """Crée un utilisateur ; le rattache à l'organisation avec `statut_membre` si fourni."""
    async with AsyncSessionLocal() as db:
        utilisateur = User(email=f"be212-{uuid.uuid4().hex}@test.local", hashedPassword="x", fullName="BE212")
        db.add(utilisateur)
        await db.commit()
        if organization_id is not None:
            db.add(
                OrganizationUser(
                    userId=utilisateur.id, organizationId=uuid.UUID(organization_id), status=statut_membre
                )
            )
            await db.commit()
        return utilisateur.id


async def _second_utilisateur_connecte(client, organization_id: str) -> dict:
    """Crée un second compte connecté, rattaché à l'organisation (pour l'isolation)."""
    email = f"be212-second-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Second"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    tokens = login.json()
    async with AsyncSessionLocal() as db:
        utilisateur_id = await db.scalar(select(User.id).where(User.email == email))
        db.add(OrganizationUser(userId=utilisateur_id, organizationId=uuid.UUID(organization_id)))
        await db.commit()
    return {"email": email, "accessToken": tokens["accessToken"]}


def _valeurs_colonnes(objet) -> list[str]:
    """Toutes les valeurs de colonnes d'une ligne ORM, sous forme de texte."""
    return [str(getattr(objet, attribut.key)) for attribut in sa_inspect(objet).mapper.column_attrs]


async def test_be212_ca1_aucun_secret_dans_notifications_ni_preferences(client, registered_user, organization):
    """Un message d'erreur de canal contenant un secret n'est jamais persisté ni exposé."""
    code = await _categorie()
    destinataire = await _utilisateur(organization["id"])
    secret = "SECRET-BE212-NE-DOIT-PAS-SORTIR"

    def envoi_qui_fuit(notification):
        raise RuntimeError(f"echec du canal avec {secret}")

    async with AsyncSessionLocal() as db:
        notification = Notification(
            eventId=uuid.uuid4(), categorieCode=code, destinataireId=destinataire, statut="en_attente"
        )
        db.add(notification)
        await db.commit()
        await livraison.livrer_avec_reprise(
            db, notification=notification, canal="web_push", envoi=envoi_qui_fuit, limite=2
        )
        lignes_livraison = (
            await db.execute(
                select(NotificationDelivery).where(NotificationDelivery.notificationId == notification.id)
            )
        ).scalars().all()
        for objet in [notification, *lignes_livraison]:
            for valeur in _valeurs_colonnes(objet):
                assert secret not in valeur

    colonnes_sensibles = re.compile(r"secret|token|password|mot_de_passe|hash", re.IGNORECASE)
    for modele in (Notification, NotificationDelivery, PreferenceNotification):
        for attribut in sa_inspect(modele).mapper.column_attrs:
            assert not colonnes_sensibles.search(attribut.key), f"{modele.__name__}.{attribut.key}"

    await client.put(PREFERENCES_URL, json={"category": code, "enabled": False}, headers=_headers(registered_user, organization))
    lecture = await client.get(PREFERENCES_URL, headers=_headers(registered_user, organization))
    assert lecture.status_code == 200, lecture.text
    assert secret not in lecture.text


async def test_be212_ca2_preference_d_un_autre_utilisateur_inaccessible(client, registered_user, organization):
    """Le `PUT` de l'acteur ne modifie que sa préférence ; l'autre utilisateur ne la voit pas."""
    code = await _categorie()
    autre = await _second_utilisateur_connecte(client, organization["id"])
    headers_autre = {"Authorization": f"Bearer {autre['accessToken']}", "X-Organization-Id": organization["id"]}

    await client.put(PREFERENCES_URL, json={"category": code, "enabled": False}, headers=_headers(registered_user, organization))
    lecture_autre = await client.get(PREFERENCES_URL, headers=headers_autre)
    assert lecture_autre.status_code == 200, lecture_autre.text
    assert all(ligne["category"] != code for ligne in lecture_autre.json())

    await client.put(PREFERENCES_URL, json={"category": code, "enabled": True}, headers=headers_autre)
    lecture_acteur = await client.get(PREFERENCES_URL, headers=_headers(registered_user, organization))
    assert [ligne["enabled"] for ligne in lecture_acteur.json() if ligne["category"] == code] == [False]


async def test_be212_ca3_categorie_inconnue_renvoie_422_sans_ecriture(client, registered_user, organization):
    """Une catégorie absente de la liste configurée est refusée en 422, sans ligne créée."""
    reponse = await client.put(
        PREFERENCES_URL,
        json={"category": "CATEGORIE-INCONNUE-BE212", "enabled": True},
        headers=_headers(registered_user, organization),
    )
    assert reponse.status_code == 422, reponse.text

    lecture = await client.get(PREFERENCES_URL, headers=_headers(registered_user, organization))
    assert lecture.status_code == 200, lecture.text
    assert lecture.json() == []


async def test_be212_ca4_audience_limitee_aux_membres_actifs_du_tenant(registered_user, organization):
    """L'audience d'un tenant exclut les membres suspendus et ceux d'un autre tenant.

    Le propriétaire créé par la fixture `organization` est membre actif : il figure donc
    parmi les éligibles, à côté du membre actif ajouté par le test.
    """
    tenant = uuid.UUID(organization["id"])
    proprietaire = await _id_par_email(registered_user["email"])
    actif = await _utilisateur(organization["id"], statut_membre="active")
    suspendu = await _utilisateur(organization["id"], statut_membre="suspended")
    hors_tenant = await _utilisateur(None)

    async with AsyncSessionLocal() as db:
        destinataires = await moteur._resoudre_audience(db, tenant, moteur.AUDIENCE_MEMBRES_ORGANISATION)

    eligibles = {destinataire.utilisateur_id for destinataire in destinataires if destinataire.eligible}
    presents = {destinataire.utilisateur_id for destinataire in destinataires}
    assert eligibles == {proprietaire, actif}
    assert suspendu in presents and suspendu not in eligibles
    assert hors_tenant not in presents


async def _id_par_email(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(User.id).where(User.email == email))


async def test_be212_ca5_echec_repris_jusqu_a_la_limite_puis_passe_en_echec(organization):
    """Un canal toujours en panne fait 5 tentatives tracées, puis la notification passe en `echec`."""
    code = await _categorie()
    destinataire = await _utilisateur(organization["id"])
    tentatives: list[uuid.UUID] = []

    def envoi_en_panne(notification):
        tentatives.append(notification.id)
        raise RuntimeError("canal indisponible")

    async with AsyncSessionLocal() as db:
        notification = Notification(
            eventId=uuid.uuid4(), categorieCode=code, destinataireId=destinataire, statut="en_attente"
        )
        db.add(notification)
        await db.commit()
        derniere = await livraison.livrer_avec_reprise(
            db, notification=notification, canal="web_push", envoi=envoi_en_panne
        )
        assert derniere.resultat == "echec"
        assert len(tentatives) == LIMITE_TENTATIVES_ATTENDUE
        assert notification.statut == "echec"
        lignes = (
            await db.execute(
                select(NotificationDelivery).where(NotificationDelivery.notificationId == notification.id)
            )
        ).scalars().all()
        assert sorted(ligne.tentative for ligne in lignes) == list(range(1, LIMITE_TENTATIVES_ATTENDUE + 1))


async def test_be212_ca5_echec_puis_succes_arrete_la_reprise(organization):
    """Un envoi qui réussit à la troisième tentative arrête la reprise et passe en `envoyee`."""
    code = await _categorie()
    destinataire = await _utilisateur(organization["id"])
    appels = {"n": 0}

    def envoi_capricieux(notification):
        appels["n"] += 1
        if appels["n"] < 3:
            raise RuntimeError("canal indisponible")

    async with AsyncSessionLocal() as db:
        notification = Notification(
            eventId=uuid.uuid4(), categorieCode=code, destinataireId=destinataire, statut="en_attente"
        )
        db.add(notification)
        await db.commit()
        derniere = await livraison.livrer_avec_reprise(
            db, notification=notification, canal="web_push", envoi=envoi_capricieux
        )
        assert derniere.resultat == "envoyee"
        assert appels["n"] == 3
        assert notification.statut == "envoyee"


async def test_be212_routes_lecture_et_ecriture_par_categorie(client, registered_user, organization):
    """`PUT` enregistre la préférence de l'utilisateur courant ; `GET` la relit."""
    code = await _categorie()
    headers = _headers(registered_user, organization)

    vide = await client.get(PREFERENCES_URL, headers=headers)
    assert vide.status_code == 200, vide.text
    assert vide.json() == []

    ecriture = await client.put(PREFERENCES_URL, json={"category": code, "enabled": False}, headers=headers)
    assert ecriture.status_code == 200, ecriture.text
    corps = ecriture.json()
    assert corps["category"] == code
    assert corps["enabled"] is False
    assert "updatedAt" in corps

    lecture = await client.get(PREFERENCES_URL, headers=headers)
    assert [(ligne["category"], ligne["enabled"]) for ligne in lecture.json()] == [(code, False)]
