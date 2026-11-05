"""BE-142 : escalade d'un cas d'intervention et clôture d'escalade, sous `/api/v1/admin`.

Tests écrits d'après la définition `### BE-142` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Routes testées :
- `POST /api/v1/admin/cases/{case_id}/escalations` : ouverture d'une escalade ;
- `POST /api/v1/admin/escalations/{escalation_id}/close` : clôture d'une escalade.

Couverture :
- CA-1 (refus de droit) : un agent L1 qui clôt une escalade reçoit 403 ;
- CA-2 : ouverture d'une escalade met le cas en état `escalade` (test de transition) ;
- CA-3 (isolation tenant) : escalade d'un cas du tenant B par un agent du tenant A : 403 ;
- CA-4 : chaque ouverture et chaque clôture produit une entrée d'audit, vérifiée en base.

Compléments : le responsable d'escalade clôt l'escalade (200, `closedAtUtc` renseigné) ;
une seconde clôture renvoie 409 ; l'ouverture sur un cas clos renvoie 409.

Hypothèses consignées (voir `app/operator/escalation.py`) : le responsable d'escalade
porte le rôle `securite_incident_commander` (QE-ADM-86) ; les niveaux d'escalade sont
provisoirement les entiers 1 à 3 (QE-ADM-12, NON DÉFINI) ; le rôle cible doit appartenir
au vocabulaire `ROLES_CANDIDATS` de BE-121.
"""

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal

CHEMIN_CAS = "/api/v1/admin/cases"
CHEMIN_ESCALADES = "/api/v1/admin/escalations"
MOT_DE_PASSE = "TestPassword123!"


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    """Compte sans affectation d'administration."""
    email = f"be142-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-142"})
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


async def _autre_organisation(client: AsyncClient) -> tuple[dict, str]:
    """Second tenant (B), créé par un autre compte."""
    proprietaire = await _nouvel_utilisateur(client)
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"tenant-b-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json(), proprietaire["id"]


async def _ouvrir_cas(client: AsyncClient, agent: dict, tenant_id: str | None) -> dict:
    """Ouvre un cas d'intervention (BE-123) et renvoie sa représentation."""
    corps = {"tenantId": tenant_id, "priority": "normale", "qualification": "Coupure de carte bancaire"}
    reponse = await client.post(CHEMIN_CAS, json=corps, headers=_entetes(agent))
    assert reponse.status_code == 201, reponse.text
    return reponse.json()


async def _escalader(client: AsyncClient, agent: dict, cas_id: str, niveau: int = 2) -> object:
    """Ouvre une escalade sur le cas et renvoie la réponse HTTP."""
    corps = {"level": niveau, "targetRole": "securite_incident_commander"}
    return await client.post(f"{CHEMIN_CAS}/{cas_id}/escalations", json=corps, headers=_entetes(agent))


async def _verifier_cas(cas_id: str, acteur_id: str) -> None:
    """Enregistre la vérification exigée par la clôture d'un cas (BE-123, CA-4)."""
    from app.audit.admin_audit import ecrire_evenement_admin

    async with AsyncSessionLocal() as db:
        await ecrire_evenement_admin(
            db,
            organization_id=None,
            actor_user_id=uuid.UUID(acteur_id),
            action="admin.case.verification",
            entity_type="InterventionCase",
            entity_id=uuid.UUID(cas_id),
            summary="Vérification du cas enregistrée",
            correlation_id="be142-verif",
        )
        await db.commit()


async def _etat_du_cas(client: AsyncClient, agent: dict, cas_id: str) -> str:
    reponse = await client.get(f"{CHEMIN_CAS}/{cas_id}", headers=_entetes(agent))
    assert reponse.status_code == 200, reponse.text
    return reponse.json()["status"]


async def _actions_d_audit(entity_type: str, entity_id: str) -> list[str]:
    """Actions d'audit écrites sur cette entité, dans l'ordre de création."""
    async with AsyncSessionLocal() as db:
        lignes = await db.execute(
            select(AuditEvent.action)
            .where(AuditEvent.entityType == entity_type, AuditEvent.entityId == uuid.UUID(entity_id))
            .order_by(AuditEvent.createdAt)
        )
        return [ligne for ligne in lignes.scalars().all()]


# ---------------------------------------------------------------------------
# CA-1 : clôture d'escalade par L1 refusée
# ---------------------------------------------------------------------------


async def test_be142_ca1_cloture_d_escalade_par_l1_recoit_403(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    cas = await _ouvrir_cas(client, agent, None)
    escalade = (await _escalader(client, agent, cas["id"])).json()

    reponse = await client.post(
        f"{CHEMIN_ESCALADES}/{escalade['id']}/close",
        json={"closureReason": "Traitée"},
        headers=_entetes(agent),
    )

    assert reponse.status_code == 403


# ---------------------------------------------------------------------------
# CA-2 : ouverture d'escalade met le cas en état escaladé
# ---------------------------------------------------------------------------


async def test_be142_ca2_ouverture_d_escalade_met_le_cas_en_etat_escalade(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    cas = await _ouvrir_cas(client, agent, None)
    assert await _etat_du_cas(client, agent, cas["id"]) == "ouvert"

    reponse = await _escalader(client, agent, cas["id"])

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert corps["caseId"] == cas["id"]
    assert corps["level"] == 2
    assert corps["targetRole"] == "securite_incident_commander"
    assert corps["closedAtUtc"] is None
    assert await _etat_du_cas(client, agent, cas["id"]) == "escalade"


async def test_be142_ca2_l2_peut_ouvrir_une_escalade(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l2", "platform")
    cas = await _ouvrir_cas(client, agent, None)

    reponse = await _escalader(client, agent, cas["id"])

    assert reponse.status_code == 201, reponse.text


# ---------------------------------------------------------------------------
# CA-3 : isolation tenant
# ---------------------------------------------------------------------------


async def test_be142_ca3_escalade_d_un_cas_du_tenant_b_par_agent_tenant_a_recoit_403(
    client: AsyncClient, registered_user: dict, organization: dict,
):
    agent_b = await _nouvel_utilisateur(client)
    tenant_b, _proprietaire_b = await _autre_organisation(client)
    await _accorder(agent_b["id"], "agent_support_l2", f"tenant:{tenant_b['id']}")
    cas_b = await _ouvrir_cas(client, agent_b, tenant_b["id"])

    agent_a = await _nouvel_utilisateur(client)
    await _accorder(agent_a["id"], "agent_support_l2", f"tenant:{organization['id']}")

    reponse = await _escalader(client, agent_a, cas_b["id"])

    assert reponse.status_code == 403


# ---------------------------------------------------------------------------
# CA-4 : chaque ouverture et clôture produit une entrée d'audit
# ---------------------------------------------------------------------------


async def test_be142_ca4_ouverture_et_cloture_ecrivent_une_entree_d_audit(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    responsable = await _nouvel_utilisateur(client)
    await _accorder(responsable["id"], "securite_incident_commander", "platform")
    cas = await _ouvrir_cas(client, agent, None)
    escalade = (await _escalader(client, agent, cas["id"])).json()

    reponse = await client.post(
        f"{CHEMIN_ESCALADES}/{escalade['id']}/close",
        json={"closureReason": "Traitée"},
        headers=_entetes(responsable),
    )
    assert reponse.status_code == 200, reponse.text

    actions = await _actions_d_audit("Escalation", escalade["id"])
    assert "admin.escalation.open" in actions
    assert "admin.escalation.close" in actions


# ---------------------------------------------------------------------------
# Compléments : clôture par le responsable, double clôture, cas clos
# ---------------------------------------------------------------------------


async def test_be142_cloture_par_le_responsable_renseigne_closed_at(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    responsable = await _nouvel_utilisateur(client)
    await _accorder(responsable["id"], "securite_incident_commander", "platform")
    cas = await _ouvrir_cas(client, agent, None)
    escalade = (await _escalader(client, agent, cas["id"])).json()

    reponse = await client.post(
        f"{CHEMIN_ESCALADES}/{escalade['id']}/close",
        json={"closureReason": "Traitée"},
        headers=_entetes(responsable),
    )

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["closedAtUtc"] is not None
    assert corps["closureReason"] == "Traitée"

    seconde = await client.post(
        f"{CHEMIN_ESCALADES}/{escalade['id']}/close",
        json={"closureReason": "Déjà traitée"},
        headers=_entetes(responsable),
    )
    assert seconde.status_code == 409


async def test_be142_ouverture_sur_un_cas_clos_recoit_409(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    responsable = await _nouvel_utilisateur(client)
    await _accorder(responsable["id"], "securite_incident_commander", "platform")
    cas = await _ouvrir_cas(client, agent, None)
    await _verifier_cas(cas["id"], responsable["id"])
    cloture = await client.post(
        f"{CHEMIN_CAS}/{cas['id']}/close",
        json={"closureReason": "Résolu"},
        headers=_entetes(responsable),
    )
    assert cloture.status_code == 200, cloture.text

    reponse = await _escalader(client, agent, cas["id"])

    assert reponse.status_code == 409
