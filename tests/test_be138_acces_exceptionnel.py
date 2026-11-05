"""BE-138 : accès exceptionnel au contenu client (refusé par défaut, BLOCKED Q-06).

Tests écrits d'après la définition `### BE-138` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Route testée : `POST /api/v1/admin/organizations/{organization_id}/exceptional-access`
(route proposée par la définition, refusée par défaut).

Couverture :
- CA-1 (refus de droit) : tout appelant, y compris le rôle sécurité / incident
  commander et chacun des rôles de BE-121, reçoit 403 ;
- CA-2 : chaque refus produit une entrée d'audit `audit_event` avec motif et
  corrélation (X-Request-Id), vérifiée en base ;
- CA-3 (isolation tenant) : un appelant administrateur du tenant A ne reçoit
  aucune donnée du tenant B en réponse à une demande visant B ;
- CA-4 : la réponse de refus ne contient aucune donnée de contenu client
  (test de projection : clés et valeurs de l'enveloppe d'erreur seulement).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal

MOT_DE_PASSE = "TestPassword123!"
MOTIF_DEMANDE = "Demande de support : vérification du contenu du tenant"

# Rôles de la définition BE-121 (candidats), repris tels quels : le test ne dépend
# pas de la liste codée dans l'implémentation.
ROLES_BE121 = [
    "agent_support_l1",
    "agent_support_l2",
    "finance_support",
    "operateur_plateforme",
    "securite_incident_commander",
    "approbateur_independant",
    "auditeur",
    "administrateur_client",
]

ACTION_REFUS = "admin.exceptional_access.refuse"


def _chemin(organisation_id: str) -> str:
    return f"/api/v1/admin/organizations/{organisation_id}/exceptional-access"


def _entetes(utilisateur: dict, portee: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['accessToken']}"}
    if portee is not None:
        entetes["X-Admin-Scope"] = portee
    return entetes


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    """Compte sans adhésion à l'organisation de test."""
    email = f"be138-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-138"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    return {"id": me.json()["id"], "accessToken": jetons["accessToken"]}


async def _accorder(actor_id: str, role_code: str, scope: str) -> None:
    """Pose une affectation d'administration directement en base (amorçage des tests).

    L'échéance est fixée dans le futur pour que les rôles temporaires (BE-121 CA-2)
    restent valides ; l'autorité est donc bien présente, et seul le refus de la
    route BE-138 peut produire le 403."""
    from app.rbac.role_assignments import AdminRoleAssignment

    async with AsyncSessionLocal() as db:
        db.add(AdminRoleAssignment(
            actorId=uuid.UUID(actor_id),
            roleCode=role_code,
            scope=scope,
            grantedBy=uuid.UUID(actor_id),
            grantedAt=datetime.now(timezone.utc),
            expiresAt=datetime.now(timezone.utc) + timedelta(days=1),
            revokedAt=None,
        ))
        await db.commit()


async def _organisation_d_un_autre_compte(client: AsyncClient) -> dict:
    """Second tenant (tenant B), créé par un compte qui n'a aucun rapport avec le tenant A."""
    proprietaire = await _nouvel_utilisateur(client)
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B BE-138", "slug": f"tenant-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {proprietaire['accessToken']}"},
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()


async def _evenements_refus(organisation_id: str) -> list[AuditEvent]:
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(
            select(AuditEvent).where(
                AuditEvent.action == ACTION_REFUS,
                AuditEvent.organizationId == uuid.UUID(organisation_id),
            )
        )
        return list(resultat.scalars().all())


# ---------------------------------------------------------------------------
# CA-1 : tout appelant reçoit 403, y compris sécurité / incident commander
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role_code", ROLES_BE121)
async def test_be138_ca1_chaque_role_be121_recoit_403(client: AsyncClient, organization: dict, role_code: str):
    appelant = await _nouvel_utilisateur(client)
    await _accorder(appelant["id"], role_code, "platform")

    reponse = await client.post(
        _chemin(organization["id"]),
        json={"motif": MOTIF_DEMANDE},
        headers=_entetes(appelant, "platform"),
    )

    assert reponse.status_code == 403


async def test_be138_ca1_securite_incident_commander_recoit_403_sur_tenant(client: AsyncClient, organization: dict):
    commandant = await _nouvel_utilisateur(client)
    await _accorder(commandant["id"], "securite_incident_commander", "platform")

    reponse = await client.post(
        _chemin(organization["id"]),
        json={"motif": MOTIF_DEMANDE},
        headers=_entetes(commandant, f"tenant:{organization['id']}"),
    )

    assert reponse.status_code == 403


async def test_be138_ca1_utilisateur_sans_affectation_recoit_403(client: AsyncClient, organization: dict):
    anonyme_admin = await _nouvel_utilisateur(client)

    reponse = await client.post(
        _chemin(organization["id"]),
        json={"motif": MOTIF_DEMANDE},
        headers=_entetes(anonyme_admin, "platform"),
    )

    assert reponse.status_code == 403


# ---------------------------------------------------------------------------
# CA-2 : chaque refus est journalisé avec motif et corrélation
# ---------------------------------------------------------------------------


async def test_be138_ca2_chaque_refus_produit_une_entree_d_audit_avec_motif_et_correlation(client: AsyncClient, organization: dict):
    commandant = await _nouvel_utilisateur(client)
    await _accorder(commandant["id"], "securite_incident_commander", "platform")

    reponse = await client.post(
        _chemin(organization["id"]),
        json={"motif": MOTIF_DEMANDE},
        headers=_entetes(commandant, "platform"),
    )

    assert reponse.status_code == 403
    entrees = await _evenements_refus(organization["id"])
    assert len(entrees) == 1
    entree = entrees[0]
    assert entree.result == "refused"
    assert entree.actorUserId == uuid.UUID(commandant["id"])
    assert entree.entityType == "Organization"
    assert entree.entityId == uuid.UUID(organization["id"])
    assert entree.request_id == reponse.headers["X-Request-Id"]
    assert entree.changes is not None
    assert entree.changes.get("motifRefus"), "le motif du refus doit être consigné"
    assert entree.changes.get("motifDemande") == MOTIF_DEMANDE


async def test_be138_ca2_chaque_nouvelle_demande_refusee_ajoute_une_entree(client: AsyncClient, organization: dict):
    appelant = await _nouvel_utilisateur(client)
    await _accorder(appelant["id"], "administrateur_client", "platform")

    for _ in range(2):
        reponse = await client.post(
            _chemin(organization["id"]),
            json={"motif": MOTIF_DEMANDE},
            headers=_entetes(appelant, "platform"),
        )
        assert reponse.status_code == 403

    assert len(await _evenements_refus(organization["id"])) == 2


# ---------------------------------------------------------------------------
# CA-3 : isolation tenant, aucune donnée du tenant B vers le tenant A
# ---------------------------------------------------------------------------


async def test_be138_ca3_admin_du_tenant_a_ne_recoit_aucune_donnee_du_tenant_b(client: AsyncClient, organization: dict):
    tenant_b = await _organisation_d_un_autre_compte(client)
    assert tenant_b["id"] != organization["id"]
    admin_a = await _nouvel_utilisateur(client)
    await _accorder(admin_a["id"], "administrateur_client", f"tenant:{organization['id']}")

    reponse = await client.post(
        _chemin(tenant_b["id"]),
        json={"motif": MOTIF_DEMANDE},
        headers=_entetes(admin_a, f"tenant:{organization['id']}"),
    )

    assert reponse.status_code == 403
    texte = reponse.text
    assert tenant_b["id"] not in texte
    assert tenant_b["name"] not in texte
    assert tenant_b["slug"] not in texte


# ---------------------------------------------------------------------------
# CA-4 : projection de la réponse de refus (aucune donnée de contenu client)
# ---------------------------------------------------------------------------


async def test_be138_ca4_la_reponse_de_refus_ne_contient_aucun_contenu_client(client: AsyncClient, organization: dict):
    commandant = await _nouvel_utilisateur(client)
    await _accorder(commandant["id"], "securite_incident_commander", "platform")

    reponse = await client.post(
        _chemin(organization["id"]),
        json={"motif": MOTIF_DEMANDE},
        headers=_entetes(commandant, "platform"),
    )

    assert reponse.status_code == 403
    # Enveloppe réelle (app/core/errors.py) : l'erreur est sous "error", request_id à la racine.
    erreur = reponse.json()["error"]
    assert set(erreur.keys()) <= {"code", "message", "details", "field_errors"}
    assert erreur.get("code") == "exceptional_access_denied"
    assert organization["name"] not in reponse.text
    assert organization["slug"] not in reponse.text
