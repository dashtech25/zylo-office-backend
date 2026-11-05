"""BE-128 : approbation distincte (double validation) des commandes opérateur.

Tests écrits d'après la définition `### BE-128` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Routes : `POST /api/v1/admin/commands/{command_id}/approve` et
`POST /api/v1/admin/commands/{command_id}/reject`, corps `{"reasonTicket": ...}`.

Couverture (critères d'acceptation de la définition) :
- CA-1 (refus de droit) : auto-approbation par l'initiateur : 403. L'initiateur porte
  ici aussi le rôle d'approbateur, pour que seule la règle de distinction soit testée ;
- CA-2 (refus de droit) : approbation par un agent L2 : 403 ;
- CA-3 : rejet d'une commande la place en état terminal ; toute confirmation ultérieure
  (approbation ou rejet) : 409 ;
- CA-4 : approbation par une seconde identité habilitée : la commande passe à
  l'état approuvé (test nominal) ;
- CA-5 (isolation tenant) : approbateur sans affectation au tenant de la commande : 403.

Tests complémentaires : une seule décision par commande (une ligne de décision) ; motif
absent : 422 ; commande inconnue : 404.

Hypothèses consignées : l'approbateur porte le rôle `approbateur_independant` sur la
portée du tenant de la commande (seul rôle admis, BE-121) ; les affectations sont posées
directement en base (helper `_accorder`), comme dans les tests BE-123 et BE-124.
"""

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal

CHEMIN_COMMANDES = "/api/v1/admin/commands"
MOT_DE_PASSE = "TestPassword123!"
CLASSE = "tenant.suspension"
ROLE_GESTION = "securite_incident_commander"
ROLE_APPROBATEUR = "approbateur_independant"
ROLE_L2 = "agent_support_l2"


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    """Compte sans affectation d'administration."""
    email = f"be128-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-128"})
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
            expiresAt=datetime.now(timezone.utc) + timedelta(days=30),
            revokedAt=None,
        ))
        await db.commit()


async def _organisation(client: AsyncClient, proprietaire: dict) -> str:
    """Crée un tenant avec ce compte pour propriétaire et renvoie son identifiant."""
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant BE-128", "slug": f"tenant-be128-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()["id"]


def _corps(tenant_id: str | None, **surcharges) -> dict:
    """Corps d'intention valide (BE-124) ; les surcharges remplacent les champs donnés."""
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


async def _intention(client: AsyncClient, initiateur: dict, tenant: str) -> str:
    """Crée une intention de commande par `initiateur` et renvoie son identifiant."""
    reponse = await client.post(CHEMIN_COMMANDES, json=_corps(tenant), headers=_entetes(initiateur))
    assert reponse.status_code == 201, reponse.text
    return reponse.json()["commandId"]


async def _decider(client: AsyncClient, approbateur: dict, commande_id: str, decision: str, motif: str = "INC-5678"):
    return await client.post(
        f"{CHEMIN_COMMANDES}/{commande_id}/{decision}",
        json={"reasonTicket": motif},
        headers=_entetes(approbateur),
    )


async def _lire(client: AsyncClient, lecteur: dict, commande_id: str) -> dict:
    reponse = await client.get(f"{CHEMIN_COMMANDES}/{commande_id}", headers=_entetes(lecteur))
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


async def _nombre_decisions(commande_id: str) -> int:
    """Nombre de lignes `admin_command_approval` pour cette commande."""
    from app.operator.approval import AdminCommandApproval

    async with AsyncSessionLocal() as db:
        stmt = select(func.count()).select_from(AdminCommandApproval).where(
            AdminCommandApproval.commandId == uuid.UUID(commande_id),
        )
        return (await db.execute(stmt)).scalar_one()


async def test_ca1_auto_approbation_par_l_initiateur_renvoie_403(client: AsyncClient):
    """CA-1 : l'initiateur ne approuve pas sa propre commande, même avec le rôle d'approbateur."""
    initiateur = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, initiateur)
    await _accorder(initiateur["id"], ROLE_GESTION, f"tenant:{tenant}")
    await _accorder(initiateur["id"], ROLE_APPROBATEUR, f"tenant:{tenant}")
    commande_id = await _intention(client, initiateur, tenant)

    reponse = await _decider(client, initiateur, commande_id, "approve")

    assert reponse.status_code == 403, reponse.text
    assert (await _lire(client, initiateur, commande_id))["status"] == "intention"
    assert await _nombre_decisions(commande_id) == 0


async def test_ca2_agent_l2_ne_peut_pas_approuver_403(client: AsyncClient):
    """CA-2 : un agent de support L2 n'est pas approbateur : 403, la commande reste en intention."""
    initiateur = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, initiateur)
    await _accorder(initiateur["id"], ROLE_GESTION, f"tenant:{tenant}")
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], ROLE_L2, f"tenant:{tenant}")
    commande_id = await _intention(client, initiateur, tenant)

    reponse = await _decider(client, agent, commande_id, "approve")

    assert reponse.status_code == 403, reponse.text
    assert (await _lire(client, initiateur, commande_id))["status"] == "intention"
    assert await _nombre_decisions(commande_id) == 0


async def test_ca3_rejet_rend_la_commande_terminale(client: AsyncClient):
    """CA-3 : après rejet, la commande est en état terminal `rejetee` et une seule décision existe."""
    initiateur = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, initiateur)
    await _accorder(initiateur["id"], ROLE_GESTION, f"tenant:{tenant}")
    approbateur = await _nouvel_utilisateur(client)
    await _accorder(approbateur["id"], ROLE_APPROBATEUR, f"tenant:{tenant}")
    commande_id = await _intention(client, initiateur, tenant)

    reponse = await _decider(client, approbateur, commande_id, "reject")

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["status"] == "rejetee"
    assert await _nombre_decisions(commande_id) == 1


async def test_ca3_confirmation_apres_rejet_renvoie_409(client: AsyncClient):
    """CA-3 : toute confirmation après rejet (approbation ou second rejet) est refusée en 409."""
    initiateur = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, initiateur)
    await _accorder(initiateur["id"], ROLE_GESTION, f"tenant:{tenant}")
    premier = await _nouvel_utilisateur(client)
    await _accorder(premier["id"], ROLE_APPROBATEUR, f"tenant:{tenant}")
    second = await _nouvel_utilisateur(client)
    await _accorder(second["id"], ROLE_APPROBATEUR, f"tenant:{tenant}")
    commande_id = await _intention(client, initiateur, tenant)
    assert (await _decider(client, premier, commande_id, "reject")).status_code == 200

    approbation_tardive = await _decider(client, second, commande_id, "approve")
    rejet_tardif = await _decider(client, second, commande_id, "reject")

    assert approbation_tardive.status_code == 409, approbation_tardive.text
    assert rejet_tardif.status_code == 409, rejet_tardif.text
    assert (await _lire(client, initiateur, commande_id))["status"] == "rejetee"
    assert await _nombre_decisions(commande_id) == 1


async def test_ca4_approbation_par_second_identite_passe_en_approuvee(client: AsyncClient):
    """CA-4 (nominal) : une seconde identité habilitée approuve ; la commande passe à `approuvee`."""
    initiateur = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, initiateur)
    await _accorder(initiateur["id"], ROLE_GESTION, f"tenant:{tenant}")
    approbateur = await _nouvel_utilisateur(client)
    await _accorder(approbateur["id"], ROLE_APPROBATEUR, f"tenant:{tenant}")
    commande_id = await _intention(client, initiateur, tenant)

    reponse = await _decider(client, approbateur, commande_id, "approve")

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["status"] == "approuvee"
    assert corps["approverId"] == approbateur["id"]
    relue = await _lire(client, initiateur, commande_id)
    assert relue["status"] == "approuvee"
    assert relue["approverId"] == approbateur["id"]
    assert await _nombre_decisions(commande_id) == 1


async def test_une_seule_decision_par_commande(client: AsyncClient):
    """Une commande approuvée ne reçoit pas une seconde décision : 409, une seule ligne."""
    initiateur = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, initiateur)
    await _accorder(initiateur["id"], ROLE_GESTION, f"tenant:{tenant}")
    premier = await _nouvel_utilisateur(client)
    await _accorder(premier["id"], ROLE_APPROBATEUR, f"tenant:{tenant}")
    second = await _nouvel_utilisateur(client)
    await _accorder(second["id"], ROLE_APPROBATEUR, f"tenant:{tenant}")
    commande_id = await _intention(client, initiateur, tenant)
    assert (await _decider(client, premier, commande_id, "approve")).status_code == 200

    reponse = await _decider(client, second, commande_id, "approve")

    assert reponse.status_code == 409, reponse.text
    assert (await _lire(client, initiateur, commande_id))["approverId"] == premier["id"]
    assert await _nombre_decisions(commande_id) == 1


async def test_ca5_approbateur_sans_affectation_sur_le_tenant_renvoie_403(client: AsyncClient):
    """CA-5 : un approbateur habilité sur un autre tenant ne peut pas approuver cette commande."""
    initiateur = await _nouvel_utilisateur(client)
    tenant_a = await _organisation(client, initiateur)
    await _accorder(initiateur["id"], ROLE_GESTION, f"tenant:{tenant_a}")
    autre = await _nouvel_utilisateur(client)
    tenant_b = await _organisation(client, autre)
    approbateur = await _nouvel_utilisateur(client)
    await _accorder(approbateur["id"], ROLE_APPROBATEUR, f"tenant:{tenant_b}")
    commande_id = await _intention(client, initiateur, tenant_a)

    reponse = await _decider(client, approbateur, commande_id, "approve")

    assert reponse.status_code == 403, reponse.text
    assert (await _lire(client, initiateur, commande_id))["status"] == "intention"
    assert await _nombre_decisions(commande_id) == 0


async def test_motif_absent_renvoie_422(client: AsyncClient):
    """Une décision sans `reasonTicket` est refusée en 422."""
    initiateur = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, initiateur)
    await _accorder(initiateur["id"], ROLE_GESTION, f"tenant:{tenant}")
    approbateur = await _nouvel_utilisateur(client)
    await _accorder(approbateur["id"], ROLE_APPROBATEUR, f"tenant:{tenant}")
    commande_id = await _intention(client, initiateur, tenant)

    reponse = await client.post(
        f"{CHEMIN_COMMANDES}/{commande_id}/approve", json={}, headers=_entetes(approbateur),
    )

    assert reponse.status_code == 422, reponse.text
    assert await _nombre_decisions(commande_id) == 0


async def test_decision_sur_commande_inconnue_renvoie_404(client: AsyncClient):
    approbateur = await _nouvel_utilisateur(client)

    reponse = await _decider(client, approbateur, str(uuid.uuid4()), "approve")

    assert reponse.status_code == 404, reponse.text
