"""BE-121 : affectations de rôle globales et temporaires (administration).

Tests écrits d'après la définition `### BE-121` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Couverture :
- CA-1 (refus de droit) : un agent support L1 (sans autorité plateforme) qui
  tente d'attribuer un rôle reçoit 403 ;
- CA-2 (refus de droit) : une attribution sans échéance pour un rôle marqué
  temporaire est refusée (422) ;
- CA-3 (isolation tenant) : une affectation de scope `tenant:A` n'ouvre aucune
  ressource du tenant B (403) ;
- CA-4 : l'attribution crée une entrée d'audit (BE-122), vérifiée en base.

Tests complémentaires (définition BE-120 et BE-121) : l'autorité plateforme
vient désormais des affectations `platform` actives (et non plus de la seule
liste `OPERATOR_READ_USER_IDS`), une affectation expirée ou révoquée ne donne
plus d'autorité, une portée tenant ne permet pas de poser une affectation
globale, un rôle inconnu est refusé, la liste filtre par acteur.

Les affectations d'autorité sont posées directement en base par le helper
`_accorder` : il n'existe pas encore de bootstrap (QE consignée).
"""

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal

CHEMIN_AFFECTATIONS = "/api/v1/admin/role-assignments"
CHEMIN_AUDIT = "/api/v1/admin/audit-events"
MOT_DE_PASSE = "TestPassword123!"


def _entetes(utilisateur: dict, portee: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['accessToken']}"}
    if portee is not None:
        entetes["X-Admin-Scope"] = portee
    return entetes


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    """Compte sans adhésion à l'organisation de test."""
    email = f"be121-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-121"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    return {"id": me.json()["id"], "accessToken": jetons["accessToken"]}


async def _accorder(actor_id: str, role_code: str, scope: str, expires_at: datetime | None = None,
                    revoked_at: datetime | None = None) -> str:
    """Pose une affectation directement en base (autorité d'amorçage). Renvoie son id."""
    from app.rbac.role_assignments import AdminRoleAssignment

    async with AsyncSessionLocal() as db:
        ligne = AdminRoleAssignment(
            actorId=uuid.UUID(actor_id),
            roleCode=role_code,
            scope=scope,
            grantedBy=uuid.UUID(actor_id),
            grantedAt=datetime.now(timezone.utc),
            expiresAt=expires_at,
            revokedAt=revoked_at,
        )
        db.add(ligne)
        await db.commit()
        return str(ligne.id)


def _corps(actor_id: str, role_code: str, scope: str, expires_at: str | None = None) -> dict:
    return {"actorId": actor_id, "roleCode": role_code, "scope": scope, "expiresAt": expires_at}


def _dans(jours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=jours)).isoformat()


# ---------------------------------------------------------------------------
# CA-1 : refus de droit pour un agent support L1
# ---------------------------------------------------------------------------


async def test_be121_ca1_agent_support_l1_recoit_403_pour_attribuer_un_role(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    cible = await _nouvel_utilisateur(client)

    reponse = await client.post(
        CHEMIN_AFFECTATIONS,
        json=_corps(cible["id"], "auditeur", "platform"),
        headers=_entetes(agent, "platform"),
    )

    assert reponse.status_code == 403


async def test_be121_ca1_utilisateur_sans_affectation_recoit_403(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    cible = await _nouvel_utilisateur(client)

    reponse = await client.post(
        CHEMIN_AFFECTATIONS,
        json=_corps(cible["id"], "auditeur", "platform"),
        headers=_entetes(registered_user, "platform"),
    )

    assert reponse.status_code == 403


async def test_be121_ca1_operateur_plateforme_peut_attribuer_un_role(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    cible = await _nouvel_utilisateur(client)

    reponse = await client.post(
        CHEMIN_AFFECTATIONS,
        json=_corps(cible["id"], "auditeur", "platform"),
        headers=_entetes(operateur, "platform"),
    )

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert corps["actorId"] == cible["id"]
    assert corps["roleCode"] == "auditeur"
    assert corps["scope"] == "platform"
    assert corps["grantedBy"] == operateur["id"]
    assert corps["revokedAt"] is None


# ---------------------------------------------------------------------------
# CA-2 : rôle temporaire sans échéance refusé
# ---------------------------------------------------------------------------


async def test_be121_ca2_role_temporaire_sans_echeance_refuse_422(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    cible = await _nouvel_utilisateur(client)

    reponse = await client.post(
        CHEMIN_AFFECTATIONS,
        json=_corps(cible["id"], "securite_incident_commander", "platform", expires_at=None),
        headers=_entetes(operateur, "platform"),
    )

    assert reponse.status_code == 422


async def test_be121_ca2_role_temporaire_avec_echeance_future_accepte(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    cible = await _nouvel_utilisateur(client)

    reponse = await client.post(
        CHEMIN_AFFECTATIONS,
        json=_corps(cible["id"], "securite_incident_commander", "platform", expires_at=_dans(2)),
        headers=_entetes(operateur, "platform"),
    )

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["expiresAt"] is not None


async def test_be121_ca2_echeance_deja_passee_refusee_422(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    cible = await _nouvel_utilisateur(client)

    reponse = await client.post(
        CHEMIN_AFFECTATIONS,
        json=_corps(cible["id"], "approbateur_independant", "platform", expires_at=_dans(-1)),
        headers=_entetes(operateur, "platform"),
    )

    assert reponse.status_code == 422


async def test_be121_role_inconnu_refuse_422(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    cible = await _nouvel_utilisateur(client)

    reponse = await client.post(
        CHEMIN_AFFECTATIONS,
        json=_corps(cible["id"], "super_admin_inconnu", "platform"),
        headers=_entetes(operateur, "platform"),
    )

    assert reponse.status_code == 422


# ---------------------------------------------------------------------------
# CA-3 : isolation tenant, une affectation tenant:A n'ouvre pas le tenant B
# ---------------------------------------------------------------------------


async def test_be121_ca3_affectation_tenant_a_n_ouvre_pas_le_tenant_b(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    tenant_b = str(uuid.uuid4())
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    # Affectation de portée tenant:A pour un autre compte : ne donne aucune autorité plateforme.
    gestionnaire = await _nouvel_utilisateur(client)
    await _accorder(gestionnaire["id"], "agent_support_l2", f"tenant:{organization['id']}")

    # 1) Poser une affectation sur le tenant B depuis la portée tenant A : refus.
    reponse = await client.post(
        CHEMIN_AFFECTATIONS,
        json=_corps(gestionnaire["id"], "agent_support_l1", f"tenant:{tenant_b}"),
        headers=_entetes(operateur, f"tenant:{organization['id']}"),
    )
    assert reponse.status_code == 403

    # 2) Le compte porteur de l'affectation tenant A n'ouvre rien du tenant B.
    reponse = await client.get(CHEMIN_AUDIT, headers=_entetes(gestionnaire, f"tenant:{tenant_b}"))
    assert reponse.status_code == 403


async def test_be121_ca3_portee_tenant_ne_pose_pas_une_affectation_globale(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    cible = await _nouvel_utilisateur(client)

    reponse = await client.post(
        CHEMIN_AFFECTATIONS,
        json=_corps(cible["id"], "auditeur", "platform"),
        headers=_entetes(operateur, f"tenant:{organization['id']}"),
    )

    assert reponse.status_code == 403


# ---------------------------------------------------------------------------
# CA-4 : chaque attribution crée une entrée d'audit (BE-122)
# ---------------------------------------------------------------------------


async def test_be121_ca4_attribution_cree_un_evenement_d_audit(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    cible = await _nouvel_utilisateur(client)

    reponse = await client.post(
        CHEMIN_AFFECTATIONS,
        json=_corps(cible["id"], "auditeur", "platform"),
        headers=_entetes(operateur, "platform"),
    )
    assert reponse.status_code == 201, reponse.text
    affectation_id = uuid.UUID(reponse.json()["id"])

    async with AsyncSessionLocal() as db:
        evenements = (await db.execute(
            select(AuditEvent).where(AuditEvent.entityId == affectation_id)
        )).scalars().all()

    assert len(evenements) == 1
    evenement = evenements[0]
    assert str(evenement.actorUserId) == operateur["id"]
    assert evenement.entityType == "AdminRoleAssignment"
    assert evenement.result == "success"
    assert evenement.request_id  # corrélation stockée dans request_id (BE-007, voir BE-122)


# ---------------------------------------------------------------------------
# Autorité plateforme : source = affectations actives, plus la seule liste
# ---------------------------------------------------------------------------


async def test_be121_autorite_plateforme_remplace_la_liste_d_exploitation(client: AsyncClient, registered_user: dict, monkeypatch):
    operateur = await _nouvel_utilisateur(client)
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", operateur["id"])
    cible = await _nouvel_utilisateur(client)

    reponse = await client.post(
        CHEMIN_AFFECTATIONS,
        json=_corps(cible["id"], "auditeur", "platform"),
        headers=_entetes(operateur, "platform"),
    )

    assert reponse.status_code == 403


async def test_be121_affectation_expiree_ou_revoquee_ne_donne_plus_d_autorite(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    expire = await _nouvel_utilisateur(client)
    await _accorder(expire["id"], "operateur_plateforme", "platform", expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    revoque = await _nouvel_utilisateur(client)
    await _accorder(revoque["id"], "operateur_plateforme", "platform", revoked_at=datetime.now(timezone.utc))
    cible = await _nouvel_utilisateur(client)

    for porteur in (expire, revoque):
        reponse = await client.post(
            CHEMIN_AFFECTATIONS,
            json=_corps(cible["id"], "auditeur", "platform"),
            headers=_entetes(porteur, "platform"),
        )
        assert reponse.status_code == 403, porteur["id"]


async def test_be121_liste_filtree_par_acteur(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    cible = await _nouvel_utilisateur(client)
    autre = await _nouvel_utilisateur(client)
    await _accorder(cible["id"], "auditeur", "platform")
    await _accorder(cible["id"], "agent_support_l2", f"tenant:{organization['id']}")
    await _accorder(autre["id"], "auditeur", "platform")

    reponse = await client.get(
        CHEMIN_AFFECTATIONS,
        params={"actor_id": cible["id"]},
        headers=_entetes(operateur, "platform"),
    )

    assert reponse.status_code == 200, reponse.text
    lignes = reponse.json()
    assert len(lignes) == 2
    assert {ligne["actorId"] for ligne in lignes} == {cible["id"]}
    assert {ligne["roleCode"] for ligne in lignes} == {"auditeur", "agent_support_l2"}


async def test_be121_liste_sans_actor_id_refusee_422(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")

    reponse = await client.get(CHEMIN_AFFECTATIONS, headers=_entetes(operateur, "platform"))

    assert reponse.status_code == 422
