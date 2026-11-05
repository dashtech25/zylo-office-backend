"""BE-132 : parcours guidé de diagnostic paiement, sous `/api/v1/admin/cases/{case_id}`.

Tests écrits d'après la définition `### BE-132` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Routes testées :
- `POST /api/v1/admin/cases/{case_id}/payment-diagnostics` ;
- `GET /api/v1/admin/cases/{case_id}/payment-diagnostics/{diagnostic_id}`.

Couverture :
- CA-1 : le parcours enregistre qualification, preuve consultée, action permise,
  résultat, vérification, échec ou reprise, escalade et clôture (test de schéma) ;
- CA-2 (refus de droit) : une tentative d'action financière depuis ce parcours
  reçoit 403, et aucun diagnostic n'est écrit ;
- CA-3 (isolation tenant) : un diagnostic sur un cas du tenant B, par un agent du
  tenant A, reçoit 403 ;
- CA-4 : un échec de diagnostic crée une reprise ou une escalade tracée (test de
  transition) : `failurePath` renseigné et entrée d'audit d'échec écrite.

Tests complémentaires : L2 peut lancer un diagnostic sur un cas qu'il a ouvert ;
un sujet sans rôle reçoit 403 ; un cas ou un diagnostic inconnu reçoit 404 ; un
résultat hors enum ou une preuve absente reçoit 422 ; une vérification non faite
ne clôt pas le diagnostic.

Les affectations de rôle sont posées directement en base (helper `_accorder`), comme
dans les tests de BE-123, car le bootstrap n'existe pas encore.
"""

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select, text

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal

CHEMIN_CAS = "/api/v1/admin/cases"
MOT_DE_PASSE = "TestPassword123!"
ACTION_ECHEC = "admin.payment_diagnostic.failure"
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
    email = f"be132-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-132"})
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
    corps = {"tenantId": tenant_id, "priority": "normale", "qualification": "Paiement refusé"}
    reponse = await client.post(CHEMIN_CAS, json=corps, headers=_entetes(agent))
    assert reponse.status_code == 201, reponse.text
    return reponse.json()["id"]


def _corps(**surcharges) -> dict:
    """Corps de diagnostic valide, modifié par les surcharges du test."""
    corps = {
        "qualification": "Paiement refusé par la banque",
        "proofConsultedRef": "preuve-journal-123",
        "result": "conforme",
        "verificationStatus": "verifiee",
    }
    corps.update(surcharges)
    return corps


async def _diagnostiquer(client: AsyncClient, agent: dict, case_id: str, **surcharges):
    return await client.post(
        f"{CHEMIN_CAS}/{case_id}/payment-diagnostics",
        json=_corps(**surcharges),
        headers=_entetes(agent),
    )


async def _actions_d_echec(diagnostic_id: str) -> list[str]:
    """Entrées d'audit d'échec écrites pour ce diagnostic."""
    async with AsyncSessionLocal() as db:
        lignes = await db.execute(
            select(AuditEvent.action)
            .where(AuditEvent.action == ACTION_ECHEC, AuditEvent.entityId == uuid.UUID(diagnostic_id))
        )
        return list(lignes.scalars().all())


async def _nombre_diagnostics(case_id: str) -> int:
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(
            text("SELECT count(*) FROM payment_diagnostic WHERE \"caseId\" = :cas"),
            {"cas": uuid.UUID(case_id)},
        )
        return resultat.scalar_one()


# ---------------------------------------------------------------------------
# CA-1 : le parcours enregistre toutes les étapes (test de schéma)
# ---------------------------------------------------------------------------


async def test_be132_ca1_schema_table_porte_les_huit_etapes(client: AsyncClient, registered_user: dict):
    async with AsyncSessionLocal() as db:
        lignes = await db.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'payment_diagnostic'")
        )
        colonnes = set(lignes.scalars().all())

    attendues = {
        "id", "caseId", "qualification", "proofConsultedRef", "permittedAction", "result",
        "verificationStatus", "failurePath", "escalationId", "closedAtUtc",
    }
    assert attendues <= colonnes


async def test_be132_ca1_reponse_couvre_qualification_a_cloture(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id)

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert set(corps) >= CHAMPS_ATTENDUS
    assert corps["qualification"] == "Paiement refusé par la banque"
    assert corps["proofConsultedRef"] == "preuve-journal-123"
    assert corps["permittedAction"] == "consultation_seule"
    assert corps["result"] == "conforme"
    assert corps["verificationStatus"] == "verifiee"
    assert corps["failurePath"] is None
    assert corps["escalationId"] is None
    assert corps["closedAtUtc"] is not None


async def test_be132_ca1_lecture_renvoie_le_diagnostic_enregistre(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)
    cree = (await _diagnostiquer(client, agent, case_id)).json()

    reponse = await client.get(
        f"{CHEMIN_CAS}/{case_id}/payment-diagnostics/{cree['id']}", headers=_entetes(agent),
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json() == cree


async def test_be132_ca1_verification_absente_ne_clot_pas(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id, verificationStatus="non_verifiee")

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["closedAtUtc"] is None


# ---------------------------------------------------------------------------
# CA-2 : aucune action financière depuis ce parcours (refus de droit)
# ---------------------------------------------------------------------------


async def test_be132_ca2_action_financiere_depuis_le_parcours_refusee_403(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id, actionDemandee="remboursement")

    assert reponse.status_code == 403, reponse.text
    assert await _nombre_diagnostics(case_id) == 0


# ---------------------------------------------------------------------------
# CA-3 : isolation tenant
# ---------------------------------------------------------------------------


async def test_be132_ca3_diagnostic_sur_cas_tenant_b_par_agent_tenant_a_403(client: AsyncClient, registered_user: dict):
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
# CA-4 : un échec crée une reprise ou une escalade tracée
# ---------------------------------------------------------------------------


async def test_be132_ca4_echec_cree_escalade_tracee(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id, result="echec", verificationStatus="non_verifiee")

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert corps["failurePath"] == "escalade"
    assert corps["closedAtUtc"] is None
    assert await _actions_d_echec(corps["id"]) == [ACTION_ECHEC]


async def test_be132_ca4_non_concluant_cree_reprise_tracee(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id, result="non_concluant", verificationStatus="non_verifiee")

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert corps["failurePath"] == "reprise"
    assert corps["closedAtUtc"] is None
    assert await _actions_d_echec(corps["id"]) == [ACTION_ECHEC]


async def test_be132_ca4_conforme_ne_trace_aucun_echec(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    corps = (await _diagnostiquer(client, agent, case_id)).json()

    assert await _actions_d_echec(corps["id"]) == []


# ---------------------------------------------------------------------------
# Compléments : droits, validation et introuvables
# ---------------------------------------------------------------------------


async def test_be132_l2_ouvreur_peut_lancer_un_diagnostic(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l2", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id)

    assert reponse.status_code == 201, reponse.text


async def test_be132_sujet_sans_role_refuse_403(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)
    sans_role = await _nouvel_utilisateur(client)

    reponse = await _diagnostiquer(client, sans_role, case_id)

    assert reponse.status_code == 403, reponse.text


async def test_be132_resultat_hors_enum_422(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)

    reponse = await _diagnostiquer(client, agent, case_id, result="peut-etre")

    assert reponse.status_code == 422


async def test_be132_preuve_absente_422(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_id = await _ouvrir_cas(client, agent, None)
    corps = _corps()
    del corps["proofConsultedRef"]

    reponse = await client.post(
        f"{CHEMIN_CAS}/{case_id}/payment-diagnostics", json=corps, headers=_entetes(agent),
    )

    assert reponse.status_code == 422


async def test_be132_cas_inconnu_404(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")

    reponse = await _diagnostiquer(client, agent, str(uuid.uuid4()))

    assert reponse.status_code == 404


async def test_be132_diagnostic_inconnu_ou_d_un_autre_cas_404(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    case_1 = await _ouvrir_cas(client, agent, None)
    case_2 = await _ouvrir_cas(client, agent, None)
    cree = (await _diagnostiquer(client, agent, case_1)).json()

    autre_cas = await client.get(
        f"{CHEMIN_CAS}/{case_2}/payment-diagnostics/{cree['id']}", headers=_entetes(agent),
    )
    inconnu = await client.get(
        f"{CHEMIN_CAS}/{case_1}/payment-diagnostics/{uuid.uuid4()}", headers=_entetes(agent),
    )

    assert autre_cas.status_code == 404
    assert inconnu.status_code == 404
