"""BE-129 : recherche d'organisation pour la console de support (lecture).

Tests écrits d'après la définition `### BE-129` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Route : `GET /api/v1/admin/search?q=&type=organization`.

Couverture :
- CA-1 : la recherche est écrite dans l'audit avec une empreinte du terme,
  jamais en clair ;
- CA-2 (refus de droit) : sujet sans autorité d'administration : 403 ;
- CA-3 (isolation tenant) : un agent limité au tenant A ne reçoit aucun résultat
  du tenant B (jeu de données à deux tenants) ;
- CA-4 : en portée tenant, les champs hors liste normalisée n'apparaissent pas
  dans la réponse (test de projection).

Décisions de test (écarts consignés dans app/operator/search.py) : la garde est
`require_admin_scope` (BE-120), obligatoire sur toute route `/api/v1/admin`
(BE-147 CA-3). Le « agent limité au tenant A » est donc un compte porteur de
l'autorité plateforme, dont la portée est `tenant:<A>`.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.rbac.role_assignments import AdminRoleAssignment

CHEMIN_RECHERCHE = "/api/v1/admin/search"
ACTION_RECHERCHE = "admin.search.query"
CHAMPS_NORMALISES = {"id", "name", "slug", "status"}


def _entetes(utilisateur: dict, portee: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['accessToken']}"}
    if portee is not None:
        entetes["X-Admin-Scope"] = portee
    return entetes


async def _moi(client: AsyncClient, utilisateur: dict) -> str:
    return (await client.get("/api/v1/auth/me", headers=_entetes(utilisateur))).json()["id"]


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


async def _organisation(client: AsyncClient, proprietaire: dict, nom: str) -> dict:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be129-{uuid.uuid4().hex[:12]}"},
        headers=_entetes(proprietaire),
    )
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = f"be129-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    mot_de_passe = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": mot_de_passe, "fullName": "Compte BE-129"})
    login = (await client.post("/api/v1/auth/login", json={"email": email, "password": mot_de_passe})).json()
    return {"accessToken": login["accessToken"]}


def _terme() -> str:
    return f"be129{uuid.uuid4().hex[:10]}"


async def test_be129_ca1_recherche_ecrite_en_audit_avec_empreinte_sans_terme_en_clair(client: AsyncClient, registered_user: dict):
    acteur = await _moi(client, registered_user)
    await _accorder(acteur, "operateur_plateforme", "platform")
    terme = _terme()
    organisation = await _organisation(client, registered_user, f"{terme} Alpha")

    res = await client.get(CHEMIN_RECHERCHE, params={"q": terme, "type": "organization"}, headers=_entetes(registered_user))

    assert res.status_code == 200
    assert organisation["id"] in [ligne["id"] for ligne in res.json()["data"]]
    async with AsyncSessionLocal() as db:
        entree = (await db.execute(
            select(AuditEvent)
            .where(AuditEvent.actorUserId == uuid.UUID(acteur), AuditEvent.action == ACTION_RECHERCHE)
            .order_by(AuditEvent.createdAt.desc())
            .limit(1)
        )).scalar_one()
    assert entree.changes["termeEmpreinte"] == hashlib.sha256(terme.encode()).hexdigest()
    texte_journalise = json.dumps(entree.changes) + entree.summary + entree.action
    assert terme not in texte_journalise


async def test_be129_ca2_sans_autorite_d_administration_403(client: AsyncClient, registered_user: dict):
    sans_droit = await _nouvel_utilisateur(client)
    autorite_l1 = await _nouvel_utilisateur(client)
    await _accorder(await _moi(client, autorite_l1), "agent_support_l1", "platform")

    res_sans_droit = await client.get(CHEMIN_RECHERCHE, params={"q": "alpha", "type": "organization"}, headers=_entetes(sans_droit))
    res_l1_seul = await client.get(CHEMIN_RECHERCHE, params={"q": "alpha", "type": "organization"}, headers=_entetes(autorite_l1))

    assert res_sans_droit.status_code == 403
    assert res_l1_seul.status_code == 403


async def test_be129_ca3_agent_limite_au_tenant_a_ne_recoit_aucun_resultat_du_tenant_b(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    agent_id = await _moi(client, agent)
    await _accorder(agent_id, "operateur_plateforme", "platform")
    terme = _terme()
    tenant_a = await _organisation(client, agent, f"{terme} Tenant A")
    proprietaire_b = await _nouvel_utilisateur(client)
    tenant_b = await _organisation(client, proprietaire_b, f"{terme} Tenant B")

    res_a = await client.get(
        CHEMIN_RECHERCHE,
        params={"q": terme, "type": "organization"},
        headers=_entetes(agent, f"tenant:{tenant_a['id']}"),
    )
    res_b = await client.get(
        CHEMIN_RECHERCHE,
        params={"q": terme, "type": "organization"},
        headers=_entetes(agent, f"tenant:{tenant_b['id']}"),
    )

    assert res_a.status_code == 200
    ids_a = [ligne["id"] for ligne in res_a.json()["data"]]
    assert ids_a == [tenant_a["id"]]
    assert tenant_b["id"] not in res_a.text
    assert res_b.status_code == 403
    assert tenant_b["id"] not in res_b.text


async def test_be129_ca4_projection_en_portee_tenant_limitee_aux_champs_normalises(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(await _moi(client, agent), "operateur_plateforme", "platform")
    terme = _terme()
    tenant_a = await _organisation(client, agent, f"{terme} Projection")

    res = await client.get(
        CHEMIN_RECHERCHE,
        params={"q": terme, "type": "organization"},
        headers=_entetes(agent, f"tenant:{tenant_a['id']}"),
    )

    assert res.status_code == 200
    lignes = res.json()["data"]
    assert len(lignes) == 1
    assert set(lignes[0].keys()) == CHAMPS_NORMALISES
    assert "createdAt" not in res.text
    assert "updatedAt" not in res.text


async def test_be129_type_inconnu_ou_terme_trop_court_422(client: AsyncClient, registered_user: dict):
    agent = await _nouvel_utilisateur(client)
    await _accorder(await _moi(client, agent), "operateur_plateforme", "platform")

    res_type = await client.get(CHEMIN_RECHERCHE, params={"q": "alpha", "type": "client"}, headers=_entetes(agent))
    res_court = await client.get(CHEMIN_RECHERCHE, params={"q": "a", "type": "organization"}, headers=_entetes(agent))

    assert res_type.status_code == 422
    assert res_court.status_code == 422
