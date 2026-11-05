"""BE-144 : notifications d'une action opérateur.

Tests écrits d'après la définition `### BE-144` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Route : `GET /api/v1/admin/commands/{command_id}/notifications`.
Service : `app.notifications.admin_notifications.notifier_action` (table
`admin_notification`).

Couverture (critères d'acceptation de la définition) :
- CA-1 : un échec d'envoi est enregistré (`echec`, motif court) et n'annule pas
  l'action : la commande reste lisible, sans changement d'état ;
- CA-2 (refus de droit) : un agent L1 non initiateur reçoit 403 ;
- CA-3 (isolation tenant) : une notification d'une commande du tenant B, lue par un
  agent du tenant A, reçoit 403 ;
- CA-4 : la représentation d'une notification n'expose aucune charge utile brute
  (test de projection : clés connues seulement, message d'erreur d'envoi absent).

Tests complémentaires : l'initiateur et l'auditeur lisent la liste (200) ; un envoi
réussi est marqué `envoyee` avec `sentAtUtc` ; une commande inconnue donne 404.

Hypothèses consignées : canal et destinataires sont NON DÉFINIS (PH-13) ; le test
injecte l'envoyeur, aucun canal réel n'est appelé. Les affectations de rôle sont posées
directement en base (helper `_accorder`), comme dans les tests BE-124.
"""

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal

CHEMIN_COMMANDES = "/api/v1/admin/commands"
MOT_DE_PASSE = "TestPassword123!"
CLASSE = "tenant.suspension"
ROLE_GESTION = "securite_incident_commander"
ROLE_L1 = "agent_support_l1"
ROLE_AUDITEUR = "auditeur"
CHAMPS_NOTIFICATION = {
    "notificationId",
    "commandId",
    "channel",
    "recipientRef",
    "status",
    "sentAtUtc",
    "failureReason",
}


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    """Compte sans affectation d'administration."""
    email = f"be144-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-144"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    return {"id": me.json()["id"], "accessToken": jetons["accessToken"]}


async def _accorder(actor_id: str, role_code: str, scope: str) -> None:
    """Pose une affectation d'administration active directement en base."""
    from app.rbac.role_assignments import AdminRoleAssignment

    async with AsyncSessionLocal() as db:
        db.add(AdminRoleAssignment(
            actorId=uuid.UUID(actor_id),
            roleCode=role_code,
            scope=scope,
            grantedBy=uuid.UUID(actor_id),
            grantedAt=datetime.now(timezone.utc),
            expiresAt=None,
            revokedAt=None,
        ))
        await db.commit()


async def _organisation(client: AsyncClient, proprietaire: dict) -> str:
    """Crée un tenant avec ce compte pour propriétaire et renvoie son identifiant."""
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant BE-144", "slug": f"tenant-be144-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()["id"]


def _corps(tenant_id: str) -> dict:
    return {
        "commandType": CLASSE,
        "commandVersion": 1,
        "tenantId": tenant_id,
        "targetObjectType": "Tenant",
        "targetObjectId": tenant_id,
        "targetVersionExpected": 3,
        "reasonTicket": "INC-1234",
        "idempotencyKey": uuid.uuid4().hex,
    }


async def _commande(client: AsyncClient, acteur: dict, tenant_id: str) -> str:
    """Crée une intention de commande et renvoie son identifiant."""
    reponse = await client.post(CHEMIN_COMMANDES, json=_corps(tenant_id), headers=_entetes(acteur))
    assert reponse.status_code == 201, reponse.text
    return reponse.json()["commandId"]


async def _notifier(commande_id: str, envoyer) -> None:
    """Appelle le service de notification comme le ferait une action, puis valide."""
    from app.notifications.admin_notifications import notifier_action

    async with AsyncSessionLocal() as db:
        await notifier_action(db, uuid.UUID(commande_id), "destinataire-test", envoyer, channel=None)
        await db.commit()


async def _envoi_en_echec() -> None:
    raise RuntimeError("SECRET-PAYLOAD-BE144 jeton=abc123")


async def _envoi_reussi() -> None:
    return None


async def test_ca1_echec_envoi_enregistre_sans_annuler_action(client: AsyncClient):
    """CA-1 : l'échec d'envoi ne lève rien ; la ligne est `echec` et la commande reste intacte."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    commande_id = await _commande(client, gestionnaire, tenant)

    await _notifier(commande_id, _envoi_en_echec)

    reponse = await client.get(
        f"{CHEMIN_COMMANDES}/{commande_id}/notifications", headers=_entetes(gestionnaire),
    )
    assert reponse.status_code == 200, reponse.text
    notifications = reponse.json()
    assert len(notifications) == 1
    assert notifications[0]["status"] == "echec"
    assert notifications[0]["failureReason"]
    assert notifications[0]["sentAtUtc"] is None

    commande = await client.get(f"{CHEMIN_COMMANDES}/{commande_id}", headers=_entetes(gestionnaire))
    assert commande.status_code == 200
    assert commande.json()["status"] == "intention"


async def test_ca2_agent_l1_non_initiateur_recoit_403(client: AsyncClient):
    """CA-2 : un agent L1 qui n'a pas initié la commande ne peut pas lire ses notifications."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    commande_id = await _commande(client, gestionnaire, tenant)
    await _notifier(commande_id, _envoi_reussi)

    agent_l1 = await _nouvel_utilisateur(client)
    await _accorder(agent_l1["id"], ROLE_L1, f"tenant:{tenant}")

    reponse = await client.get(
        f"{CHEMIN_COMMANDES}/{commande_id}/notifications", headers=_entetes(agent_l1),
    )
    assert reponse.status_code == 403, reponse.text


async def test_ca3_isolation_tenant_notification_lue_depuis_autre_tenant_refusee(client: AsyncClient):
    """CA-3 : la commande du tenant B n'est pas lisible par un agent du seul tenant A."""
    proprietaire_b = await _nouvel_utilisateur(client)
    tenant_b = await _organisation(client, proprietaire_b)
    await _accorder(proprietaire_b["id"], ROLE_GESTION, f"tenant:{tenant_b}")
    commande_id = await _commande(client, proprietaire_b, tenant_b)
    await _notifier(commande_id, _envoi_reussi)

    agent_a = await _nouvel_utilisateur(client)
    tenant_a = await _organisation(client, agent_a)
    await _accorder(agent_a["id"], ROLE_GESTION, f"tenant:{tenant_a}")

    reponse = await client.get(
        f"{CHEMIN_COMMANDES}/{commande_id}/notifications", headers=_entetes(agent_a),
    )
    assert reponse.status_code == 403, reponse.text


async def test_ca4_projection_sans_charge_utile_brute(client: AsyncClient):
    """CA-4 : seules les clés projetées sortent ; le message brut de l'envoyeur n'apparaît pas."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    commande_id = await _commande(client, gestionnaire, tenant)
    await _notifier(commande_id, _envoi_en_echec)

    reponse = await client.get(
        f"{CHEMIN_COMMANDES}/{commande_id}/notifications", headers=_entetes(gestionnaire),
    )
    assert reponse.status_code == 200, reponse.text
    for notification in reponse.json():
        assert set(notification) == CHAMPS_NOTIFICATION
    assert "SECRET-PAYLOAD-BE144" not in reponse.text
    assert "abc123" not in reponse.text


async def test_initiateur_et_auditeur_lisent_envoi_reussi_marque_envoyee(client: AsyncClient):
    """Droits : l'initiateur et l'auditeur de la portée lisent ; un envoi réussi est `envoyee`."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    commande_id = await _commande(client, gestionnaire, tenant)
    await _notifier(commande_id, _envoi_reussi)

    auditeur = await _nouvel_utilisateur(client)
    await _accorder(auditeur["id"], ROLE_AUDITEUR, f"tenant:{tenant}")

    for lecteur in (gestionnaire, auditeur):
        reponse = await client.get(
            f"{CHEMIN_COMMANDES}/{commande_id}/notifications", headers=_entetes(lecteur),
        )
        assert reponse.status_code == 200, reponse.text
        notifications = reponse.json()
        assert len(notifications) == 1
        assert notifications[0]["status"] == "envoyee"
        assert notifications[0]["sentAtUtc"] is not None
        assert notifications[0]["failureReason"] is None


async def test_commande_inconnue_recoit_404(client: AsyncClient):
    """Une commande inexistante donne 404, sans fuite d'existence pour les autres cas."""
    utilisateur = await _nouvel_utilisateur(client)
    reponse = await client.get(
        f"{CHEMIN_COMMANDES}/{uuid.uuid4()}/notifications", headers=_entetes(utilisateur),
    )
    assert reponse.status_code == 404, reponse.text


async def test_table_admin_notification_ecrite_par_le_service(client: AsyncClient):
    """La ligne persistée porte la commande et le destinataire passés au service."""
    from app.notifications.admin_notifications import AdminNotification

    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    commande_id = await _commande(client, gestionnaire, tenant)
    await _notifier(commande_id, _envoi_reussi)

    async with AsyncSessionLocal() as db:
        lignes = (await db.execute(
            select(AdminNotification).where(AdminNotification.commandId == uuid.UUID(commande_id))
        )).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].recipientRef == "destinataire-test"
    assert lignes[0].status == "envoyee"
