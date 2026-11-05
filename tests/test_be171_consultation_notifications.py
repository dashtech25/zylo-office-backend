"""BE-171 : routes API de consultation des notifications.

Tests écrits d'après la définition `### BE-171` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Routes cibles :
- `GET /api/v1/notifications` : notifications du destinataire courant, filtrables par `statut` ;
- `GET /api/v1/notifications/{id}/livraisons` : résultats de livraison d'une notification.

Lecture seule des tables `notification` et `livraison` (BE-169, BE-170) ; aucune migration.
Organisation désignée par l'en-tête `X-Organization-Id`.

Écarts avec la définition, signalés ici et dans `app/notifications/consultation.py` :
- QE-PAR-03 : la permission `notifications.read` n'existait pas ; elle est déclarée par le
  module (`app/notifications/permissions.py`) et n'est accordée à aucun rôle par défaut ;
- la table `notification` n'a pas de colonne de tenant (BE-169) : l'isolation tenant de la
  liste repose sur le destinataire et sur l'événement source (`outbox_evenement.tenantId`).

Couverture :
- CA-1 : la liste ne contient que les notifications du destinataire courant ;
- CA-1 (filtre) : `statut` filtre la liste ; une valeur hors énumération renvoie 422 ;
- CA-2 : `GET .../livraisons` renvoie les résultats sans adresse de destinataire ;
- CA-3 (refus) : lire les livraisons sans `notifications.read` renvoie 403 ;
- CA-4 : une notification d'un autre destinataire renvoie 404 ;
- CA-5 (isolation tenant) : la liste ne contient aucune notification du tenant B pour un
  utilisateur du tenant A.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.evenements.models import OutboxEvenement
from app.identity.models import OrganizationUser, User
from app.notifications.categories import creer_categorie
from app.notifications.models import Livraison, Notification
from app.rbac.models import RolePermission, UserRole
from app.rbac.service import get_or_create_permission
from tests.conftest import unique_email

ROUTE = "/api/v1/notifications"
PERMISSION_LECTURE = "notifications.read"
MOT_DE_PASSE = "TestPassword123!"


def _entetes(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def _inscrire_et_connecter(client: AsyncClient) -> dict:
    """Crée un compte connecté ; renvoie son identifiant et son jeton d'accès."""
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE171"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        return {"id": str(user.id), "accessToken": login.json()["accessToken"]}


async def _id_de(utilisateur: dict) -> str:
    """Identifiant de l'utilisateur du fixture `registered_user` (lu en base par courriel)."""
    async with AsyncSessionLocal() as db:
        return str((await db.execute(select(User).where(User.email == utilisateur["email"]))).scalar_one().id)


async def _membre_sans_compte(organization_id: str) -> uuid.UUID:
    """Utilisateur actif rattaché à l'organisation, sans session ouverte."""
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"be171-{uuid.uuid4().hex}@test.local",
            hashedPassword=hash_password("x"),
            fullName="Destinataire BE-171",
            status="active",
        )
        db.add(user)
        await db.flush()
        db.add(OrganizationUser(userId=user.id, organizationId=uuid.UUID(organization_id)))
        await db.commit()
        return user.id


async def _categorie() -> str:
    code = f"BE171-{uuid.uuid4().hex[:12]}"
    async with AsyncSessionLocal() as db:
        await creer_categorie(db, code=code, libelle="Catégorie BE-171", audience_regle="membres_organisation")
    return code


async def _notification(destinataire_id: uuid.UUID, categorie: str, statut: str = "en_attente", motif: str | None = None) -> str:
    """Une notification du moteur pour ce destinataire ; renvoie son identifiant."""
    async with AsyncSessionLocal() as db:
        ligne = Notification(
            eventId=uuid.uuid4(),
            categorieCode=categorie,
            destinataireId=destinataire_id,
            statut=statut,
            motifSuppression=motif,
        )
        db.add(ligne)
        await db.commit()
        return str(ligne.id)


async def _livraison(notification_id: str, tentative: int, resultat: str, canal: str = "canal-test", code_erreur: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            Livraison(
                notificationId=uuid.UUID(notification_id),
                canal=canal,
                tentativeNo=tentative,
                resultat=resultat,
                codeErreur=code_erreur,
            )
        )
        await db.commit()


async def _evenement_tenant(event_id: uuid.UUID, tenant_id: str) -> None:
    """Enregistre l'événement source dans l'outbox, rattaché à un tenant."""
    async with AsyncSessionLocal() as db:
        db.add(
            OutboxEvenement(
                eventId=event_id,
                eventType="Notifications.Test.BE171",
                schemaVersion=1,
                tenantId=uuid.UUID(tenant_id),
                payload={},
            )
        )
        await db.commit()


async def _accorder_lecture(user_id: str, organization_id: str) -> None:
    """Accorde `notifications.read` via le rôle que l'utilisateur détient dans l'organisation."""
    async with AsyncSessionLocal() as db:
        permission = await get_or_create_permission(db, PERMISSION_LECTURE, "notifications", "Lire les livraisons.")
        role_id = (
            await db.execute(
                select(UserRole.roleId).where(
                    UserRole.userId == uuid.UUID(user_id), UserRole.organizationId == uuid.UUID(organization_id)
                )
            )
        ).scalars().first()
        db.add(RolePermission(roleId=role_id, permissionId=permission.id))
        await db.commit()


async def _ajouter_membre_sans_permission(client: AsyncClient, organization_id: str) -> dict:
    """Membre actif de l'organisation, sans rôle ni permission de lecture."""
    membre = await _inscrire_et_connecter(client)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=uuid.UUID(membre["id"])))
        await db.commit()
    return membre


async def test_be171_ca1_liste_ne_contient_que_les_notifications_du_destinataire(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : seules les notifications de l'utilisateur courant sont listées."""
    categorie = await _categorie()
    moi = await _id_de(registered_user)
    mienne = await _notification(uuid.UUID(moi), categorie)
    autre = await _notification(await _membre_sans_compte(organization["id"]), categorie)

    res = await client.get(ROUTE, headers=_entetes(registered_user["accessToken"], organization["id"]))

    assert res.status_code == 200, res.text
    ids = [ligne["id"] for ligne in res.json()["data"]]
    assert mienne in ids
    assert autre not in ids


async def test_be171_ca1_filtre_par_statut(client: AsyncClient, registered_user: dict, organization: dict):
    """Filtre `statut` : seules les notifications du statut demandé sont renvoyées ;
    une valeur hors énumération renvoie 422."""
    categorie = await _categorie()
    moi = uuid.UUID(await _id_de(registered_user))
    envoyee = await _notification(moi, categorie, statut="envoyee")
    await _notification(moi, categorie, statut="en_attente")
    entetes = _entetes(registered_user["accessToken"], organization["id"])

    res = await client.get(ROUTE, params={"statut": "envoyee"}, headers=entetes)
    assert res.status_code == 200, res.text
    assert [ligne["id"] for ligne in res.json()["data"]] == [envoyee]
    assert all(ligne["statut"] == "envoyee" for ligne in res.json()["data"])

    invalide = await client.get(ROUTE, params={"statut": "inconnu"}, headers=entetes)
    assert invalide.status_code == 422, invalide.text


async def test_be171_ca2_livraisons_sans_adresse_de_destinataire(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-2 : les résultats de livraison ne contiennent aucune adresse ; seuls les champs
    de tentative sont renvoyés."""
    categorie = await _categorie()
    moi = uuid.UUID(await _id_de(registered_user))
    notification = await _notification(moi, categorie, statut="envoyee")
    await _livraison(notification, 1, "rebond", code_erreur="CHANNEL_UNAVAILABLE")
    await _accorder_lecture(str(moi), organization["id"])

    res = await client.get(f"{ROUTE}/{notification}/livraisons", headers=_entetes(registered_user["accessToken"], organization["id"]))

    assert res.status_code == 200, res.text
    livraisons = res.json()
    assert len(livraisons) == 1
    assert set(livraisons[0]) == {"id", "canal", "tentativeNo", "resultat", "codeErreur", "prochaineTentativeAt", "creeAt"}
    assert livraisons[0]["resultat"] == "rebond"
    assert "@" not in res.text


async def test_be171_ca3_livraisons_sans_notifications_read_renvoie_403(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 (refus) : sans `notifications.read`, la lecture des livraisons renvoie 403."""
    categorie = await _categorie()
    membre = await _ajouter_membre_sans_permission(client, organization["id"])
    notification = await _notification(uuid.UUID(membre["id"]), categorie, statut="envoyee")
    await _livraison(notification, 1, "livre")

    res = await client.get(f"{ROUTE}/{notification}/livraisons", headers=_entetes(membre["accessToken"], organization["id"]))

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_be171_ca4_notification_d_un_autre_destinataire_renvoie_404(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : sans permission de lecture, la notification d'un autre destinataire est `404`
    (sans révéler son existence) ; la liste de l'utilisateur ne la montre pas."""
    categorie = await _categorie()
    autre = await _membre_sans_compte(organization["id"])
    notification = await _notification(autre, categorie, statut="envoyee")
    entetes = _entetes(registered_user["accessToken"], organization["id"])

    res = await client.get(f"{ROUTE}/{notification}/livraisons", headers=entetes)
    assert res.status_code == 404, res.text

    # Témoin : la même route, sur une notification propre, ne renvoie pas 404 (sans permission : 403).
    propre = await _notification(uuid.UUID(await _id_de(registered_user)), categorie, statut="envoyee")
    temoin = await client.get(f"{ROUTE}/{propre}/livraisons", headers=entetes)
    assert temoin.status_code == 403, temoin.text


async def test_be171_ca5_isolation_tenant_liste_sans_notification_du_tenant_b(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-5 : une notification dont l'événement source appartient au tenant B n'apparaît pas
    dans la liste d'un utilisateur du tenant A, même si elle lui est adressée."""
    categorie = await _categorie()
    moi = uuid.UUID(await _id_de(registered_user))

    tenant_b = await _inscrire_et_connecter(client)
    res_b = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"tenant-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {tenant_b['accessToken']}"},
    )
    assert res_b.status_code in (200, 201), res_b.text
    tenant_b_id = res_b.json()["id"]

    visible = await _notification(moi, categorie, statut="envoyee")
    evenement_b = uuid.uuid4()
    await _evenement_tenant(evenement_b, tenant_b_id)
    tenant_b_notification = await _notification(moi, categorie, statut="envoyee")
    async with AsyncSessionLocal() as db:
        ligne = await db.get(Notification, uuid.UUID(tenant_b_notification))
        ligne.eventId = evenement_b
        await db.commit()

    res = await client.get(ROUTE, headers=_entetes(registered_user["accessToken"], organization["id"]))

    assert res.status_code == 200, res.text
    ids = [ligne["id"] for ligne in res.json()["data"]]
    assert visible in ids
    assert tenant_b_notification not in ids
