"""BE-133 : parcours guidé de diagnostic abonnement, sous `/api/v1/admin/cases/{case_id}`.

Tests écrits d'après la définition `### BE-133` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Routes testées :
- `POST /api/v1/admin/cases/{case_id}/subscription-diagnostics` ;
- `GET /api/v1/admin/cases/{case_id}/subscription-diagnostics/{diagnostic_id}`.

Couverture :
- CA-1 : le parcours couvre les mêmes huit étapes que le parcours paiement (test de schéma) ;
- CA-2 (refus de droit) : modification directe d'un entitlement dérivé depuis ce parcours
  reçoit 403 ou 405 ;
- CA-3 (isolation tenant) : diagnostic d'un abonnement du tenant B par un agent du tenant A
  reçoit 403 ;
- CA-4 : rétablissement d'un abonnement sans préconditions remplies reçoit 409. Le test
  s'appuie sur la machine d'état BE-079 (`transition_etat`), seule porte d'écriture des
  axes d'abonnement ; le parcours diagnostic n'écrit jamais ces axes.

Les affectations de rôle sont posées directement en base (helper `_accorder`), comme
dans les tests de BE-132 et BE-123, car le bootstrap n'existe pas encore.
"""

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select, text

from app.billing import service
from app.billing.models import Subscription
from app.billing.subscriptions.etats import transition_etat
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import Organization

CHEMIN_CAS = "/api/v1/admin/cases"
MOT_DE_PASSE = "TestPassword123!"
CHAMPS_ATTENDUS = {
    "id",
    "caseId",
    "qualification",
    "proofConsultedRef",
    "permittedAction",
    "result",
    "verificationStatus",
    "failurePath",
    "escalationId",
    "closedAtUtc",
}


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    """Compte sans affectation d'administration."""
    email = f"be133-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-133"})
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


async def _organisation(client: AsyncClient, nom: str) -> str:
    """Crée une organisation par un compte propriétaire et renvoie son identifiant."""
    proprietaire = await _nouvel_utilisateur(client)
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"{nom.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()["id"]


async def _ouvrir_cas(client: AsyncClient, agent: dict, tenant_id: str | None) -> str:
    """Ouvre un cas d'intervention (BE-123) et renvoie son identifiant."""
    corps = {"tenantId": tenant_id, "priority": "normale", "qualification": "Abonnement en anomalie"}
    reponse = await client.post(CHEMIN_CAS, json=corps, headers=_entetes(agent))
    assert reponse.status_code == 201, reponse.text
    return reponse.json()["id"]


def _corps(**surcharges) -> dict:
    """Corps de diagnostic valide, modifié par les surcharges du test."""
    corps = {
        "qualification": "Abonnement non reconduit",
        "proofConsultedRef": "preuve-abonnement-456",
        "result": "conforme",
        "verificationStatus": "verifiee",
    }
    corps.update(surcharges)
    return corps


async def _diagnostiquer(client: AsyncClient, agent: dict, case_id: str, **surcharges):
    return await client.post(
        f"{CHEMIN_CAS}/{case_id}/subscription-diagnostics",
        json=_corps(**surcharges),
        headers=_entetes(agent),
    )


async def _nombre_diagnostics(case_id: str) -> int:
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(
            text("SELECT count(*) FROM subscription_diagnostic WHERE \"caseId\" = :cas"),
            {"cas": uuid.UUID(case_id)},
        )
        return resultat.scalar_one()


async def _colonnes(table: str) -> set[str]:
    async with AsyncSessionLocal() as db:
        lignes = await db.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :table"),
            {"table": table},
        )
        return set(lignes.scalars().all())


async def _creer_abonnement_resilie(tenant_id: uuid.UUID) -> uuid.UUID:
    """Abonnement résilié (cycle de vie `cancelled`) du tenant ; renvoie son identifiant.

    Montage minimal : un plan et une ligne d'abonnement, comme dans les tests de BE-079.
    """
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be133-{uuid.uuid4().hex[:8]}", "Plan BE-133", 1000, "XAF", 30
        )
        abonnement = Subscription(
            organizationId=tenant_id,
            planId=plan.id,
            status="trial",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
            beneficiaryTenantId=tenant_id,
            lifecycleStatus="cancelled",
            financialStatus="none",
            incidentStatus="none",
        )
        db.add(abonnement)
        await db.commit()
        return abonnement.id


# ---------------------------------------------------------------------------
# CA-1 : le parcours couvre les mêmes huit étapes que le parcours paiement (schéma)
# ---------------------------------------------------------------------------


async def test_be133_ca1_schema_table_porte_les_huit_etapes(client: AsyncClient, registered_user: dict):
    colonnes = await _colonnes("subscription_diagnostic")

    assert CHAMPS_ATTENDUS <= colonnes


async def test_be133_ca1_table_identique_au_parcours_paiement(client: AsyncClient, registered_user: dict):
    colonnes_abonnement = await _colonnes("subscription_diagnostic")
    colonnes_paiement = await _colonnes("payment_diagnostic")

    assert colonnes_abonnement == colonnes_paiement


async def test_be133_ca1_reponse_couvre_qualification_a_cloture(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id)

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert set(corps) >= CHAMPS_ATTENDUS
    assert corps["qualification"] == "Abonnement non reconduit"
    assert corps["proofConsultedRef"] == "preuve-abonnement-456"
    assert corps["permittedAction"] == "consultation_seule"
    assert corps["result"] == "conforme"
    assert corps["verificationStatus"] == "verifiee"
    assert corps["failurePath"] is None
    assert corps["escalationId"] is None
    assert corps["closedAtUtc"] is not None


async def test_be133_ca1_lecture_renvoie_le_diagnostic_enregistre(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)
    cree = (await _diagnostiquer(client, agent, case_id)).json()

    reponse = await client.get(
        f"{CHEMIN_CAS}/{case_id}/subscription-diagnostics/{cree['id']}", headers=_entetes(agent),
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json() == cree


async def test_be133_ca1_verification_absente_ne_clot_pas(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id, verificationStatus="non_verifiee")

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["closedAtUtc"] is None


# ---------------------------------------------------------------------------
# CA-2 : aucune modification directe d'entitlement depuis ce parcours (403 ou 405)
# ---------------------------------------------------------------------------


async def test_be133_ca2_modification_entitlement_depuis_le_parcours_refusee_403(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id, actionDemandee="modification_entitlement")

    assert reponse.status_code == 403, reponse.text
    assert await _nombre_diagnostics(case_id) == 0


async def test_be133_ca2_correction_d_abonnement_depuis_le_parcours_refusee_403(client: AsyncClient, registered_user: dict):
    """Toute correction d'abonnement passe par BE-135 : le parcours diagnostic la refuse."""
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id, actionDemandee="changement_plan")

    assert reponse.status_code == 403, reponse.text
    assert await _nombre_diagnostics(case_id) == 0


async def test_be133_ca2_ecriture_directe_du_diagnostic_405(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)
    cree = (await _diagnostiquer(client, agent, case_id)).json()

    reponse = await client.patch(
        f"{CHEMIN_CAS}/{case_id}/subscription-diagnostics/{cree['id']}",
        json={"result": "echec"},
        headers=_entetes(agent),
    )

    assert reponse.status_code == 405, reponse.text


# ---------------------------------------------------------------------------
# CA-3 : isolation tenant
# ---------------------------------------------------------------------------


async def test_be133_ca3_diagnostic_abonnement_tenant_b_par_agent_tenant_a_403(client: AsyncClient, registered_user: dict):
    tenant_a = await _organisation(client, "Tenant A")
    tenant_b = await _organisation(client, "Tenant B")
    ouvreur_b = await _nouvel_utilisateur(client)
    await _accorder(ouvreur_b["id"], "agent_support_l1", f"tenant:{tenant_b}")
    case_id = await _ouvrir_cas(client, ouvreur_b, tenant_b)

    agent_a = await _nouvel_utilisateur(client)
    await _accorder(agent_a["id"], "agent_support_l1", f"tenant:{tenant_a}")

    reponse = await _diagnostiquer(client, agent_a, case_id)

    assert reponse.status_code == 403, reponse.text
    assert await _nombre_diagnostics(case_id) == 0


# ---------------------------------------------------------------------------
# CA-4 : rétablissement sans préconditions remplies : 409
# ---------------------------------------------------------------------------


async def test_be133_ca4_retablissement_sans_preconditions_409(client: AsyncClient, registered_user: dict):
    """Un abonnement résilié ne revient pas à `active` : la machine BE-079 renvoie 409.

    Le parcours diagnostic n'écrit aucun axe d'abonnement ; la seule porte d'écriture est
    `transition_etat`. L'état reste inchangé après le refus.
    """
    tenant_id = uuid.UUID(await _organisation(client, "Tenant Retablissement"))
    abonnement_id = await _creer_abonnement_resilie(tenant_id)

    async with AsyncSessionLocal() as db:
        try:
            await transition_etat(db, abonnement_id, tenant_id, "lifecycle", "active")
            leve = None
        except AppError as erreur:
            leve = erreur

    assert leve is not None
    assert leve.status_code == 409
    assert leve.code == "INVALID_TRANSITION"
    async with AsyncSessionLocal() as db:
        abonnement = await db.scalar(select(Subscription).where(Subscription.id == abonnement_id))
        assert abonnement.lifecycleStatus == "cancelled"


# ---------------------------------------------------------------------------
# Compléments : droits, validation et introuvables
# ---------------------------------------------------------------------------


async def test_be133_l2_ouvreur_peut_lancer_un_diagnostic(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l2", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id)

    assert reponse.status_code == 201, reponse.text


async def test_be133_sujet_sans_role_refuse_403(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)
    sans_role = await _nouvel_utilisateur(client)

    reponse = await _diagnostiquer(client, sans_role, case_id)

    assert reponse.status_code == 403, reponse.text


async def test_be133_resultat_hors_enum_422(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id, result="peut-etre")

    assert reponse.status_code == 422


async def test_be133_preuve_absente_422(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)
    corps = _corps()
    del corps["proofConsultedRef"]

    reponse = await client.post(
        f"{CHEMIN_CAS}/{case_id}/subscription-diagnostics", json=corps, headers=_entetes(agent),
    )

    assert reponse.status_code == 422


async def test_be133_cas_inconnu_404(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")

    reponse = await _diagnostiquer(client, agent, str(uuid.uuid4()))

    assert reponse.status_code == 404


async def test_be133_diagnostic_inconnu_ou_d_un_autre_cas_404(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_1 = await _ouvrir_cas(client, agent, None)
    case_2 = await _ouvrir_cas(client, agent, None)
    cree = (await _diagnostiquer(client, agent, case_1)).json()

    autre_cas = await client.get(
        f"{CHEMIN_CAS}/{case_2}/subscription-diagnostics/{cree['id']}", headers=_entetes(agent),
    )
    inconnu = await client.get(
        f"{CHEMIN_CAS}/{case_1}/subscription-diagnostics/{uuid.uuid4()}", headers=_entetes(agent),
    )

    assert autre_cas.status_code == 404
    assert inconnu.status_code == 404
