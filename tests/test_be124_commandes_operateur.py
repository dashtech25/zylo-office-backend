"""BE-124 : modèle de commande opérateur et idempotence sous `/api/v1/admin/commands`.

Tests écrits d'après la définition `### BE-124` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Couverture (critères d'acceptation de la définition) :
- CA-1 : deux envois de la même `idempotencyKey` avec le même corps renvoient la même
  commande, et une seule ligne `admin_command` existe (le seul effet persistant ici) ;
- CA-2 : même clé avec un corps différent : 409 ;
- CA-3 (refus de droit) : un rôle non habilité à la classe reçoit 403, aucune commande
  n'est créée ;
- CA-4 : absence de `reasonTicket` : 422 ;
- CA-5 (isolation tenant) : une commande visant le tenant B, créée par un acteur qui
  n'a de droit que sur le tenant A, est refusée (403).

Tests complémentaires : la clé d'idempotence est scopée par acteur ; une classe hors
registre BE-127 est refusée (422) ; la lecture par `GET` est réservée au créateur ou à
un responsable de gestion de la portée (403 sinon) ; une commande inconnue : 404.

Hypothèses consignées (voir `app/operator/commands.py`) : la matrice rôle par classe
est provisoire (responsable d'escalade seul) ; l'effet n'est pas exécuté ici (QE-ADM-22).
Les affectations de rôle sont posées directement en base (helper `_accorder`), comme
dans les tests BE-123.
"""

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal

CHEMIN_COMMANDES = "/api/v1/admin/commands"
MOT_DE_PASSE = "TestPassword123!"
CLASSE = "tenant.suspension"
ROLE_GESTION = "securite_incident_commander"
ROLE_L1 = "agent_support_l1"


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    """Compte sans affectation d'administration."""
    email = f"be124-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-124"})
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
        json={"name": "Tenant BE-124", "slug": f"tenant-be124-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()["id"]


def _corps(tenant_id: str | None, **surcharges) -> dict:
    """Corps d'intention valide ; les surcharges remplacent les champs donnés."""
    corps = {
        "commandType": CLASSE,
        "commandVersion": 1,
        "tenantId": tenant_id,
        "targetObjectType": "Tenant",
        "targetObjectId": tenant_id or str(uuid.uuid4()),
        "targetVersionExpected": 3,
        "reasonTicket": "INC-1234",
        "idempotencyKey": uuid.uuid4().hex,
    }
    corps.update(surcharges)
    return corps


async def _soumettre(client: AsyncClient, acteur: dict, corps: dict):
    return await client.post(CHEMIN_COMMANDES, json=corps, headers=_entetes(acteur))


async def _nombre_commandes(acteur_id: str, cle: str) -> int:
    """Nombre de lignes `admin_command` pour ce couple (acteur, clé)."""
    from app.operator.commands import AdminCommand

    async with AsyncSessionLocal() as db:
        stmt = select(func.count()).select_from(AdminCommand).where(
            AdminCommand.actorId == uuid.UUID(acteur_id),
            AdminCommand.idempotencyKey == cle,
        )
        return (await db.execute(stmt)).scalar_one()


async def test_ca1_double_envoi_meme_cle_meme_corps_renvoie_la_meme_commande(client: AsyncClient):
    """CA-1 : le second envoi renvoie la commande du premier et ne crée aucune ligne."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    corps = _corps(tenant)

    premier = await _soumettre(client, gestionnaire, corps)
    second = await _soumettre(client, gestionnaire, dict(corps))

    assert premier.status_code == 201, premier.text
    assert second.status_code == 200, second.text
    assert second.json()["commandId"] == premier.json()["commandId"]
    assert await _nombre_commandes(gestionnaire["id"], corps["idempotencyKey"]) == 1


async def test_ca2_meme_cle_corps_different_renvoie_409(client: AsyncClient):
    """CA-2 : une clé déjà utilisée avec un autre corps est refusée en 409."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    corps = _corps(tenant)
    assert (await _soumettre(client, gestionnaire, corps)).status_code == 201

    autre = dict(corps, reasonTicket="INC-9999")
    reponse = await _soumettre(client, gestionnaire, autre)

    assert reponse.status_code == 409, reponse.text
    assert await _nombre_commandes(gestionnaire["id"], corps["idempotencyKey"]) == 1


async def test_ca3_role_non_habilite_a_la_classe_recoit_403_sans_commande(client: AsyncClient):
    """CA-3 : un agent L1 ne crée pas une commande de la classe `tenant.suspension`."""
    agent = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, agent)
    await _accorder(agent["id"], ROLE_L1, f"tenant:{tenant}")
    corps = _corps(tenant)

    reponse = await _soumettre(client, agent, corps)

    assert reponse.status_code == 403, reponse.text
    assert await _nombre_commandes(agent["id"], corps["idempotencyKey"]) == 0


async def test_ca4_reason_ticket_absent_renvoie_422(client: AsyncClient):
    """CA-4 : sans `reasonTicket`, la commande est refusée en 422."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    corps = _corps(tenant)
    del corps["reasonTicket"]

    reponse = await _soumettre(client, gestionnaire, corps)

    assert reponse.status_code == 422, reponse.text
    assert await _nombre_commandes(gestionnaire["id"], corps["idempotencyKey"]) == 0


async def test_ca5_commande_sur_autre_tenant_recoit_403(client: AsyncClient):
    """CA-5 : un acteur habilité sur le tenant A ne crée rien pour le tenant B."""
    acteur = await _nouvel_utilisateur(client)
    tenant_a = await _organisation(client, acteur)
    autre = await _nouvel_utilisateur(client)
    tenant_b = await _organisation(client, autre)
    await _accorder(acteur["id"], ROLE_GESTION, f"tenant:{tenant_a}")
    corps = _corps(tenant_b)

    reponse = await _soumettre(client, acteur, corps)

    assert reponse.status_code == 403, reponse.text
    assert await _nombre_commandes(acteur["id"], corps["idempotencyKey"]) == 0


async def test_la_cle_d_idempotence_est_scopee_par_acteur(client: AsyncClient):
    """Deux acteurs peuvent utiliser la même clé sans se renvoyer la commande d'autrui."""
    premier = await _nouvel_utilisateur(client)
    second = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, premier)
    await _accorder(premier["id"], ROLE_GESTION, f"tenant:{tenant}")
    await _accorder(second["id"], ROLE_GESTION, f"tenant:{tenant}")
    cle = uuid.uuid4().hex
    corps = _corps(tenant, idempotencyKey=cle)

    reponse_1 = await _soumettre(client, premier, corps)
    reponse_2 = await _soumettre(client, second, dict(corps))

    assert reponse_1.status_code == 201, reponse_1.text
    assert reponse_2.status_code == 201, reponse_2.text
    assert reponse_1.json()["commandId"] != reponse_2.json()["commandId"]


async def test_commande_enregistre_le_role_et_la_portee_effectifs(client: AsyncClient):
    """La commande garde le rôle qui l'a autorisée et la portée du tenant visé."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")

    reponse = await _soumettre(client, gestionnaire, _corps(tenant))

    assert reponse.status_code == 201, reponse.text
    corps_reponse = reponse.json()
    assert corps_reponse["effectiveRole"] == ROLE_GESTION
    assert corps_reponse["effectiveScope"] == f"tenant:{tenant}"
    assert corps_reponse["status"] == "intention"
    assert corps_reponse["approverId"] is None
    assert corps_reponse["actorId"] == gestionnaire["id"]


async def test_classe_hors_registre_renvoie_422(client: AsyncClient):
    """Un `commandType` absent du registre BE-127 est refusé en 422."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")

    reponse = await _soumettre(client, gestionnaire, _corps(tenant, commandType="classe.inexistante"))

    assert reponse.status_code == 422, reponse.text


async def test_lecture_reservee_au_createur_ou_au_responsable(client: AsyncClient):
    """GET : le créateur lit sa commande ; un compte sans droit sur la portée reçoit 403."""
    gestionnaire = await _nouvel_utilisateur(client)
    tiers = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    cree = await _soumettre(client, gestionnaire, _corps(tenant))
    commande_id = cree.json()["commandId"]

    lecture_createur = await client.get(f"{CHEMIN_COMMANDES}/{commande_id}", headers=_entetes(gestionnaire))
    lecture_tiers = await client.get(f"{CHEMIN_COMMANDES}/{commande_id}", headers=_entetes(tiers))

    assert lecture_createur.status_code == 200, lecture_createur.text
    assert lecture_createur.json()["commandId"] == commande_id
    assert lecture_tiers.status_code == 403, lecture_tiers.text


async def test_lecture_commande_inconnue_renvoie_404(client: AsyncClient):
    gestionnaire = await _nouvel_utilisateur(client)

    reponse = await client.get(f"{CHEMIN_COMMANDES}/{uuid.uuid4()}", headers=_entetes(gestionnaire))

    assert reponse.status_code == 404, reponse.text
