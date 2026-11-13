"""BE-123 : cas d'intervention (ticket de support) sous `/api/v1/admin/cases`.

Tests écrits d'après la définition `### BE-123` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Couverture :
- CA-1 : ouverture d'un cas avec une priorité hors enum (`basse | normale | haute`) : 422 ;
- CA-2 (refus de droit) : un agent L1 qui affecte un cas reçoit 403 ;
- CA-3 (isolation tenant) : un agent limité au tenant A qui lit un cas du tenant B
  reçoit 403 ;
- CA-4 : clôture sans vérification enregistrée : 409 ; avec vérification : 200 et
  `closedAtUtc` renseigné ;
- CA-5 : chaque transition de statut (ouverture, affectation, clôture) produit une
  entrée d'audit, vérifiée en base.

Tests complémentaires (lecture limitée, droits d'ouverture) : un agent L1 qui n'est
ni l'ouvreur ni l'affecté ne lit pas le cas (403) ; un sujet sans rôle ne peut pas
ouvrir de cas (403) ; un cas inconnu renvoie 404.

Hypothèses consignées (voir le module `app/operator/cases.py`) : le responsable
d'escalade est porté par le rôle `securite_incident_commander` ; la vérification
enregistrée est une entrée d'audit d'action `admin.case.verification` sur le cas.
Les affectations de rôle sont posées directement en base (helper `_accorder`), car
le bootstrap n'existe pas encore.
"""

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.admin_audit import ecrire_evenement_admin
from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal

CHEMIN_CAS = "/api/v1/admin/cases"
MOT_DE_PASSE = "TestPassword123!"
ACTION_VERIFICATION = "admin.case.verification"


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    """Compte sans affectation d'administration."""
    email = f"be123-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-123"})
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
    """Second tenant (B), créé par un autre compte, qui y est seul affecté."""
    proprietaire = await _nouvel_utilisateur(client)
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"tenant-b-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json(), proprietaire["id"]


async def _ouvrir(client: AsyncClient, agent: dict, tenant_id: str | None, priorite: str = "normale") -> dict:
    """Ouvre un cas et renvoie la réponse HTTP."""
    corps = {"tenantId": tenant_id, "priority": priorite, "qualification": "Coupure de carte bancaire"}
    return await client.post(CHEMIN_CAS, json=corps, headers=_entetes(agent))


async def _verifier(cas_id: str, tenant_id: str | None, acteur_id: str) -> None:
    """Enregistre la vérification du cas directement dans le journal d'audit."""
    async with AsyncSessionLocal() as db:
        await ecrire_evenement_admin(
            db,
            organization_id=uuid.UUID(tenant_id) if tenant_id else None,
            actor_user_id=uuid.UUID(acteur_id),
            action=ACTION_VERIFICATION,
            entity_type="InterventionCase",
            entity_id=uuid.UUID(cas_id),
            summary="Vérification du cas enregistrée",
            correlation_id="be123-verif",
        )
        await db.commit()


async def _evenements_du_cas(cas_id: str) -> list[str]:
    """Actions d'audit écrites sur ce cas, dans l'ordre de création."""
    async with AsyncSessionLocal() as db:
        lignes = await db.execute(
            select(AuditEvent.action)
            .where(AuditEvent.entityType == "InterventionCase", AuditEvent.entityId == uuid.UUID(cas_id))
            .order_by(AuditEvent.createdAt)
        )
        return [ligne for ligne in lignes.scalars().all()]


# ---------------------------------------------------------------------------
# CA-1 : priorité hors enum refusée
# ---------------------------------------------------------------------------


async def test_be123_ca1_priorite_hors_enum_refusee_422(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")

    reponse = await _ouvrir(client, agent, None, priorite="urgente")

    assert reponse.status_code == 422


async def test_be123_ca1_priorite_de_l_enum_acceptee_201(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")

    reponse = await _ouvrir(client, agent, None, priorite="haute")

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["priority"] == "haute"
    assert reponse.json()["status"] == "ouvert"
    assert reponse.json()["openedBy"] == agent["id"]


# ---------------------------------------------------------------------------
# CA-2 : agent L1 qui affecte un cas reçoit 403
# ---------------------------------------------------------------------------


async def test_be123_ca2_agent_l1_qui_affecte_un_cas_recoit_403(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    cas = (await _ouvrir(client, agent, None)).json()
    cible = await _nouvel_utilisateur(client)

    reponse = await client.post(
        f"{CHEMIN_CAS}/{cas['id']}/assign",
        json={"assigneeId": cible["id"]},
        headers=_entetes(agent),
    )

    assert reponse.status_code == 403


# ---------------------------------------------------------------------------
# CA-3 : isolation tenant
# ---------------------------------------------------------------------------


async def test_be123_ca3_agent_tenant_a_lit_un_cas_du_tenant_b_recoit_403(client: AsyncClient, registered_user: dict, organization: dict):
    agent_b = await _nouvel_utilisateur(client)
    tenant_b, proprietaire_b = await _autre_organisation(client)
    await _accorder(agent_b["id"], "agent_support_l2", f"tenant:{tenant_b['id']}")
    cas_b = (await _ouvrir(client, agent_b, tenant_b["id"])).json()
    assert cas_b["tenantId"] == tenant_b["id"]

    agent_a = await _nouvel_utilisateur(client)
    await _accorder(agent_a["id"], "agent_support_l2", f"tenant:{organization['id']}")

    reponse = await client.get(f"{CHEMIN_CAS}/{cas_b['id']}", headers=_entetes(agent_a))

    assert reponse.status_code == 403


# ---------------------------------------------------------------------------
# CA-4 : clôture et vérification enregistrée
# ---------------------------------------------------------------------------


async def test_be123_ca4_cloture_sans_verification_recoit_409(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    responsable = await _nouvel_utilisateur(client)
    await _accorder(responsable["id"], "securite_incident_commander", "platform")
    cas = (await _ouvrir(client, agent, None)).json()

    reponse = await client.post(
        f"{CHEMIN_CAS}/{cas['id']}/close",
        json={"closureReason": "Carte réactivée"},
        headers=_entetes(responsable),
    )

    assert reponse.status_code == 409


async def test_be123_ca4_cloture_avec_verification_renseigne_closed_at(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    responsable = await _nouvel_utilisateur(client)
    await _accorder(responsable["id"], "securite_incident_commander", "platform")
    cas = (await _ouvrir(client, agent, None)).json()
    await _verifier(cas["id"], None, responsable["id"])

    reponse = await client.post(
        f"{CHEMIN_CAS}/{cas['id']}/close",
        json={"closureReason": "Carte réactivée"},
        headers=_entetes(responsable),
    )

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["status"] == "cloture"
    assert corps["closedAtUtc"] is not None
    assert corps["closureReason"] == "Carte réactivée"


# ---------------------------------------------------------------------------
# CA-5 : chaque transition produit une entrée d'audit
# ---------------------------------------------------------------------------


async def test_be123_ca5_chaque_transition_ecrit_une_entree_d_audit(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    responsable = await _nouvel_utilisateur(client)
    await _accorder(responsable["id"], "securite_incident_commander", "platform")
    cas = (await _ouvrir(client, agent, None)).json()
    assignee = await _nouvel_utilisateur(client)

    await client.post(f"{CHEMIN_CAS}/{cas['id']}/assign", json={"assigneeId": assignee["id"]}, headers=_entetes(responsable))
    await _verifier(cas["id"], None, responsable["id"])
    await client.post(f"{CHEMIN_CAS}/{cas['id']}/close", json={"closureReason": "Résolu"}, headers=_entetes(responsable))

    actions = await _evenements_du_cas(cas["id"])
    assert "admin.case.open" in actions
    assert "admin.case.assign" in actions
    assert "admin.case.close" in actions


# ---------------------------------------------------------------------------
# Compléments : lecture limitée et droit d'ouverture
# ---------------------------------------------------------------------------


async def test_be123_lecture_limitee_agent_l1_non_affecte_recoit_403(client: AsyncClient, registered_user: dict):
    ouvreur = await _nouvel_utilisateur(client)
    await _accorder(ouvreur["id"], "agent_support_l1", "platform")
    cas = (await _ouvrir(client, ouvreur, None)).json()
    autre_l1 = await _nouvel_utilisateur(client)
    await _accorder(autre_l1["id"], "agent_support_l1", "platform")

    reponse = await client.get(f"{CHEMIN_CAS}/{cas['id']}", headers=_entetes(autre_l1))

    assert reponse.status_code == 403


async def test_be123_ouverture_sans_role_recoit_403(client: AsyncClient, registered_user: dict):
    sans_role = await _nouvel_utilisateur(client)

    reponse = await _ouvrir(client, sans_role, None)

    assert reponse.status_code == 403


async def test_be123_cas_inconnu_recoit_404(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")

    reponse = await client.get(f"{CHEMIN_CAS}/{uuid.uuid4()}", headers=_entetes(agent))

    assert reponse.status_code == 404
