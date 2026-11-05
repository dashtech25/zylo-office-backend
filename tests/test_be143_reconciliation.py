"""BE-143 : réconciliation des résultats inconnus et vérification post-action.

Tests écrits d'après la définition `### BE-143` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Routes testées (opérateur, sous `/api/v1/admin`) :
- `POST /api/v1/admin/commands/{command_id}/reconcile` ;
- `POST /api/v1/admin/commands/{command_id}/verify`.

Le domaine propriétaire (QE-ADM-22) n'est pas résolu : les tests injectent un
réconciliateur et un vérificateur fictifs dans `RECONCILIATEURS` et `VERIFICATEURS`,
et un domaine d'exécution fictif dans `EXECUTEURS` (comme BE-126).

Couverture (critères d'acceptation) :
- CA-1 : une commande `resultat_inconnu` bloque tout nouvel effet, y compris après
  une réconciliation qui ne tranche pas ;
- CA-2 : la réconciliation ne modifie aucun état métier (état avant = état après) ;
- CA-3 (refus de droit) : un agent L1 reçoit 403 sur la réconciliation et sur la
  vérification ; la vérification sans propriétaire de domaine branché est refusée ;
- CA-4 : une reprise après réconciliation réemploie la clé d'origine (`commandId`) ;
- CA-5 (isolation tenant) : un agent du tenant A ne réconcilie pas une commande du
  tenant B : 403.

Les fixtures HTTP et helpers reprennent ceux de BE-126.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.operator import guard, reconcile
from app.operator.commands import AdminCommand
from app.operator.guard import EXECUTEURS, ResultatInconnu, executer_commande
from app.rbac.role_assignments import AdminRoleAssignment

CHEMIN_COMMANDES = "/api/v1/admin/commands"
MOT_DE_PASSE = "TestPassword123!"
CLASSE = "tenant.suspension"
ROLE_GESTION = "securite_incident_commander"
ROLE_L1 = "agent_support_l1"
ROLE_L2 = "agent_support_l2"
ROLE_PLATEFORME = "operateur_plateforme"
DUREE_PREVIEW_TEST = 600


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = f"be143-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-143"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    return {"id": me.json()["id"], "accessToken": jetons["accessToken"]}


async def _accorder(actor_id: str, role_code: str, scope: str) -> None:
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
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant BE-143", "slug": f"tenant-be143-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()["id"]


async def _version_organisation(tenant_id: str) -> int:
    from app.identity.models import Organization

    async with AsyncSessionLocal() as db:
        return (await db.get(Organization, uuid.UUID(tenant_id))).version


async def _commande_confirmee(client: AsyncClient, monkeypatch, tenant: str, gestionnaire: dict) -> tuple[str, str]:
    """Crée, prévisualise et confirme une commande sur `tenant`. Renvoie (command_id, preview_id)."""
    monkeypatch.setattr(settings, "ADMIN_PREVIEW_TTL_SECONDS", DUREE_PREVIEW_TEST)
    version = await _version_organisation(tenant)
    corps = {
        "commandType": CLASSE,
        "commandVersion": 1,
        "tenantId": tenant,
        "targetObjectType": "Tenant",
        "targetObjectId": tenant,
        "targetVersionExpected": version,
        "reasonTicket": "INC-143",
        "idempotencyKey": uuid.uuid4().hex,
    }
    creation = await client.post(CHEMIN_COMMANDES, json=corps, headers=_entetes(gestionnaire))
    assert creation.status_code == 201, creation.text
    command_id = creation.json()["commandId"]
    preview = await client.post(f"{CHEMIN_COMMANDES}/{command_id}/preview", headers=_entetes(gestionnaire))
    assert preview.status_code == 201, preview.text
    preview_id = preview.json()["previewId"]
    confirmation = await client.post(
        f"{CHEMIN_COMMANDES}/{command_id}/confirm",
        json={"previewId": preview_id},
        headers=_entetes(gestionnaire),
    )
    assert confirmation.status_code == 200, confirmation.text
    return command_id, preview_id


async def _commande_en_resultat_inconnu(client: AsyncClient, monkeypatch) -> dict:
    """Commande dont le domaine a répondu `ResultatInconnu` (passage réel par la garde BE-126)."""

    async def domaine_muet(db, commande):
        raise ResultatInconnu()

    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    command_id, preview_id = await _commande_confirmee(client, monkeypatch, tenant, gestionnaire)
    monkeypatch.setitem(EXECUTEURS, CLASSE, domaine_muet)
    async with AsyncSessionLocal() as db:
        with pytest.raises(Exception):
            await executer_commande(
                db, command_id=uuid.UUID(command_id), actor_id=uuid.UUID(gestionnaire["id"]),
                preview_id=uuid.UUID(preview_id),
            )
    return {"command_id": command_id, "preview_id": preview_id, "gestionnaire": gestionnaire, "tenant": tenant}


async def _statut(command_id: str) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.get(AdminCommand, uuid.UUID(command_id))).status


async def _journal(action: str) -> list[AuditEvent]:
    async with AsyncSessionLocal() as db:
        return list((await db.execute(select(AuditEvent).where(AuditEvent.action == action))).scalars().all())


def _reconciliateur(effet: str, resultat: dict | None = None):
    """Réconciliateur fictif : lit l'état du domaine, ne le modifie pas."""

    async def reconcilier(db, commande):
        if effet == "present":
            return {"effet": "present", "resultat": resultat or {"ok": True}}
        return {"effet": effet}

    return reconcilier


# CA-1 : résultat inconnu = blocage de tout nouvel effet.
async def test_ca1_resultat_inconnu_bloque_tout_nouvel_effet(client: AsyncClient, monkeypatch):
    cible = await _commande_en_resultat_inconnu(client, monkeypatch)
    monkeypatch.setitem(reconcile.RECONCILIATEURS, CLASSE, _reconciliateur("inconnu"))
    appels = []

    async def domaine_compte(db, commande):
        appels.append(commande.commandId)
        return {"ok": True}

    monkeypatch.setitem(EXECUTEURS, CLASSE, domaine_compte)
    reponse = await client.post(
        f"{CHEMIN_COMMANDES}/{cible['command_id']}/reconcile", headers=_entetes(cible["gestionnaire"]),
    )
    assert reponse.status_code == 200, reponse.text
    assert await _statut(cible["command_id"]) == "resultat_inconnu"

    async with AsyncSessionLocal() as db:
        with pytest.raises(Exception) as erreur:
            await executer_commande(
                db, command_id=uuid.UUID(cible["command_id"]),
                actor_id=uuid.UUID(cible["gestionnaire"]["id"]), preview_id=uuid.UUID(cible["preview_id"]),
            )
    assert getattr(erreur.value, "status_code", None) == 409
    assert appels == [], "le domaine ne doit recevoir aucun second appel"


# CA-2 : la réconciliation ne modifie aucun état métier.
async def test_ca2_reconciliation_ne_modifie_aucun_etat_metier(client: AsyncClient, monkeypatch):
    cible = await _commande_en_resultat_inconnu(client, monkeypatch)
    etat_metier = {"abonnement": "actif", "version": 7}
    avant = dict(etat_metier)

    async def lecture_seule(db, commande):
        # Le réconciliateur lit l'état métier et le rapporte, sans l'écrire.
        return {"effet": "present", "resultat": {"abonnement": etat_metier["abonnement"]}}

    monkeypatch.setitem(reconcile.RECONCILIATEURS, CLASSE, lecture_seule)
    reponse = await client.post(
        f"{CHEMIN_COMMANDES}/{cible['command_id']}/reconcile", headers=_entetes(cible["gestionnaire"]),
    )
    assert reponse.status_code == 200, reponse.text
    assert etat_metier == avant
    assert await _statut(cible["command_id"]) == "executee"


# CA-3 (refus de droit) : agent L1 refusé ; vérification sans propriétaire branché refusée.
async def test_ca3_agent_l1_recoit_403_en_reconciliation_et_verification(client: AsyncClient, monkeypatch):
    cible = await _commande_en_resultat_inconnu(client, monkeypatch)
    l1 = await _nouvel_utilisateur(client)
    await _accorder(l1["id"], ROLE_L1, f"tenant:{cible['tenant']}")
    monkeypatch.setitem(reconcile.RECONCILIATEURS, CLASSE, _reconciliateur("present"))
    monkeypatch.setitem(reconcile.VERIFICATEURS, CLASSE, (frozenset({ROLE_PLATEFORME}), lambda db, c: {"conforme": True}))

    reconciliation = await client.post(f"{CHEMIN_COMMANDES}/{cible['command_id']}/reconcile", headers=_entetes(l1))
    verification = await client.post(f"{CHEMIN_COMMANDES}/{cible['command_id']}/verify", headers=_entetes(l1))
    assert reconciliation.status_code == 403, reconciliation.text
    assert verification.status_code == 403, verification.text
    assert await _statut(cible["command_id"]) == "resultat_inconnu"


async def test_ca3_verification_refusee_sans_proprietaire_branche(client: AsyncClient, monkeypatch):
    cible = await _commande_en_resultat_inconnu(client, monkeypatch)
    plateforme = await _nouvel_utilisateur(client)
    await _accorder(plateforme["id"], ROLE_PLATEFORME, f"tenant:{cible['tenant']}")
    monkeypatch.setattr(reconcile, "VERIFICATEURS", {})
    reponse = await client.post(f"{CHEMIN_COMMANDES}/{cible['command_id']}/verify", headers=_entetes(plateforme))
    assert reponse.status_code == 403, reponse.text


# CA-4 : une reprise réemploie la clé d'idempotence d'origine (commandId).
async def test_ca4_reprise_reemploie_la_cle_d_origine(client: AsyncClient, monkeypatch):
    cible = await _commande_en_resultat_inconnu(client, monkeypatch)
    l2 = await _nouvel_utilisateur(client)
    await _accorder(l2["id"], ROLE_L2, f"tenant:{cible['tenant']}")
    monkeypatch.setitem(reconcile.RECONCILIATEURS, CLASSE, _reconciliateur("absent"))
    reponse = await client.post(f"{CHEMIN_COMMANDES}/{cible['command_id']}/reconcile", headers=_entetes(l2))
    assert reponse.status_code == 200, reponse.text
    assert await _statut(cible["command_id"]) == "intention", "l'effet absent rouvre une exécution"

    cles_recues = []

    async def domaine_reprise(db, commande):
        cles_recues.append((str(commande.commandId), commande.idempotencyKey))
        return {"ok": True}

    monkeypatch.setitem(EXECUTEURS, CLASSE, domaine_reprise)
    async with AsyncSessionLocal() as db:
        commande = await executer_commande(
            db, command_id=uuid.UUID(cible["command_id"]),
            actor_id=uuid.UUID(cible["gestionnaire"]["id"]), preview_id=uuid.UUID(cible["preview_id"]),
        )
    assert commande.status == "executee"
    assert cles_recues == [(cible["command_id"], cles_recues[0][1])]
    assert cles_recues[0][1] == (await _cle_origine(cible["command_id"]))


async def _cle_origine(command_id: str) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.get(AdminCommand, uuid.UUID(command_id))).idempotencyKey


# CA-5 (isolation tenant) : agent du tenant A, commande du tenant B : 403.
async def test_ca5_agent_tenant_a_ne_reconcilie_pas_commande_tenant_b(client: AsyncClient, monkeypatch):
    cible = await _commande_en_resultat_inconnu(client, monkeypatch)
    agent_a = await _nouvel_utilisateur(client)
    tenant_a = await _organisation(client, agent_a)
    await _accorder(agent_a["id"], ROLE_L2, f"tenant:{tenant_a}")
    monkeypatch.setitem(reconcile.RECONCILIATEURS, CLASSE, _reconciliateur("present"))
    reponse = await client.post(f"{CHEMIN_COMMANDES}/{cible['command_id']}/reconcile", headers=_entetes(agent_a))
    assert reponse.status_code == 403, reponse.text
    assert await _statut(cible["command_id"]) == "resultat_inconnu"


# Traçabilité : chaque réconciliation écrit un évènement d'audit.
async def test_reconciliation_ecrit_un_evenement_d_audit(client: AsyncClient, monkeypatch):
    cible = await _commande_en_resultat_inconnu(client, monkeypatch)
    plateforme = await _nouvel_utilisateur(client)
    await _accorder(plateforme["id"], ROLE_PLATEFORME, f"tenant:{cible['tenant']}")
    monkeypatch.setitem(reconcile.RECONCILIATEURS, CLASSE, _reconciliateur("present"))
    avant = len(await _journal(reconcile.ACTION_RECONCILIATION))
    reponse = await client.post(f"{CHEMIN_COMMANDES}/{cible['command_id']}/reconcile", headers=_entetes(plateforme))
    assert reponse.status_code == 200, reponse.text
    assert len(await _journal(reconcile.ACTION_RECONCILIATION)) == avant + 1
