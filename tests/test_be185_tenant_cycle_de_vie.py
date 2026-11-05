"""Tests BE-185 : cycle de vie du tenant (CA-1 à CA-5).

Source : implementation-backend/tasks-donnees-api-contrats.md, section BE-185.

Vocabulaire : la définition écrit `tenant` (`tenantId`, `state`, `version`) et
les routes `/api/v1/tenants`. Le droit de gestion est la permission plateforme
`platform.tenant.manage`, attribuée par allowlist d'environnement
(`PLATFORM_TENANT_MANAGE_USER_IDS`), comme les droits plateforme de BE-042.

Un membre d'un tenant est un membre de l'organisation dont l'identifiant vaut
le `tenantId` (tenant racine = organisation, BE-002 et BE-182). Les tests qui
ont besoin de ce rattachement l'insèrent directement.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.evenements.models import OutboxEvenement
from app.identity.models import Organization, OrganizationUser
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
ROUTE = "/api/v1/tenants"


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['token']}"}


async def _creer_utilisateur(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-185"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "token": token}


@pytest.fixture
async def plateforme(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Compte porteur du droit `platform.tenant.manage` (allowlist d'environnement)."""
    utilisateur = await _creer_utilisateur(client)
    monkeypatch.setenv("PLATFORM_TENANT_MANAGE_USER_IDS", utilisateur["id"])
    return utilisateur


async def _creer_tenant(client: AsyncClient, plateforme: dict) -> dict:
    res = await client.post(ROUTE, json={"slug": f"tenant-{uuid.uuid4().hex[:10]}"}, headers=_entetes(plateforme))
    assert res.status_code == 201, res.text
    return res.json()


async def _transition(client: AsyncClient, acteur: dict, tenant_id: str, cible: str, version: int):
    return await client.post(
        f"{ROUTE}/{tenant_id}/transitions",
        json={"targetState": cible, "expectedVersion": version},
        headers=_entetes(acteur),
    )


async def _rattacher_membre(tenant_id: str, user_id: str) -> None:
    """Rend `user_id` membre du tenant `tenant_id` (organisation de même identifiant)."""
    async with AsyncSessionLocal() as db:
        db.add(Organization(id=uuid.UUID(tenant_id), name="Tenant BE-185", slug=f"t185-{uuid.uuid4().hex[:12]}", status="active"))
        await db.flush()
        db.add(OrganizationUser(organizationId=uuid.UUID(tenant_id), userId=uuid.UUID(user_id)))
        await db.commit()


# ---------------------------------------------------------------------------
# CA-1 : une transition du graphe passe ; une transition absente renvoie 422
# ---------------------------------------------------------------------------


async def test_ca1_transitions_du_graphe_passent_et_transition_absente_renvoie_422(client: AsyncClient, plateforme: dict):
    tenant = await _creer_tenant(client, plateforme)
    tenant_id = tenant["tenantId"]
    assert tenant["state"] == "requested"
    version = tenant["version"]

    for cible in ["provisioning", "active", "suspended", "active", "closing", "closed"]:
        res = await _transition(client, plateforme, tenant_id, cible, version)
        assert res.status_code == 200, res.text
        assert res.json()["state"] == cible
        version = res.json()["version"]

    interdite = await _transition(client, plateforme, tenant_id, "active", version)
    assert interdite.status_code == 422, interdite.text


# ---------------------------------------------------------------------------
# CA-2 : sans permission plateforme, création et transition renvoient 403
# ---------------------------------------------------------------------------


async def test_ca2_utilisateur_sans_droit_plateforme_recoit_403(client: AsyncClient, plateforme: dict):
    tenant = await _creer_tenant(client, plateforme)
    sans_droit = await _creer_utilisateur(client)

    res = await _transition(client, sans_droit, tenant["tenantId"], "provisioning", tenant["version"])
    assert res.status_code == 403, res.text

    creation = await client.post(ROUTE, json={"slug": f"tenant-{uuid.uuid4().hex[:10]}"}, headers=_entetes(sans_droit))
    assert creation.status_code == 403, creation.text

    lu = await client.get(f"{ROUTE}/{tenant['tenantId']}", headers=_entetes(plateforme))
    assert lu.json()["state"] == "requested", "une demande refusée ne doit rien modifier"


# ---------------------------------------------------------------------------
# CA-3 : un utilisateur d'un autre tenant obtient 404 ; un tenant fermé aussi
# ---------------------------------------------------------------------------


async def test_ca3_utilisateur_d_un_autre_tenant_obtient_404(client: AsyncClient, plateforme: dict):
    tenant_b = await _creer_tenant(client, plateforme)
    utilisateur_a = await _creer_utilisateur(client)
    await client.post(
        "/api/v1/organizations",
        json={"name": f"Org A {uuid.uuid4().hex[:6]}", "slug": f"org-a-{uuid.uuid4().hex[:10]}"},
        headers=_entetes(utilisateur_a),
    )

    res = await client.get(f"{ROUTE}/{tenant_b['tenantId']}", headers=_entetes(utilisateur_a))
    assert res.status_code == 404, res.text


async def test_ca3_membre_lit_son_tenant_actif_et_obtient_404_une_fois_ferme(client: AsyncClient, plateforme: dict):
    tenant = await _creer_tenant(client, plateforme)
    tenant_id = tenant["tenantId"]
    membre = await _creer_utilisateur(client)
    await _rattacher_membre(tenant_id, membre["id"])

    actif = await client.get(f"{ROUTE}/{tenant_id}", headers=_entetes(membre))
    assert actif.status_code == 200, actif.text

    version = tenant["version"]
    for cible in ["provisioning", "active", "closing", "closed"]:
        res = await _transition(client, plateforme, tenant_id, cible, version)
        assert res.status_code == 200, res.text
        version = res.json()["version"]

    ferme = await client.get(f"{ROUTE}/{tenant_id}", headers=_entetes(membre))
    assert ferme.status_code == 404, ferme.text

    par_plateforme = await client.get(f"{ROUTE}/{tenant_id}", headers=_entetes(plateforme))
    assert par_plateforme.status_code == 200, "la plateforme lit un tenant fermé"


# ---------------------------------------------------------------------------
# CA-4 : chaque transition réussie écrit une entrée d'audit et une entrée outbox
# ---------------------------------------------------------------------------


async def test_ca4_chaque_transition_ecrit_audit_et_outbox(client: AsyncClient, plateforme: dict):
    tenant = await _creer_tenant(client, plateforme)
    tenant_id = tenant["tenantId"]

    res = await _transition(client, plateforme, tenant_id, "provisioning", tenant["version"])
    assert res.status_code == 200, res.text

    async with AsyncSessionLocal() as db:
        audits = (
            await db.execute(
                select(AuditEvent).where(AuditEvent.entityId == uuid.UUID(tenant_id), AuditEvent.action == "tenant.transition")
            )
        ).scalars().all()
        evenements = (
            await db.execute(select(OutboxEvenement).where(OutboxEvenement.eventType == "Plateforme.tenant.transition"))
        ).scalars().all()

    assert len(audits) == 1, "une transition réussie écrit exactement une entrée d'audit"
    assert audits[0].changes["toState"] == "provisioning"
    assert any(e.payload["subject"]["id"] == tenant_id for e in evenements), "une entrée outbox porte le tenant"


# ---------------------------------------------------------------------------
# CA-5 : une demande identique rejouée sur le même état renvoie 409
# ---------------------------------------------------------------------------


async def test_ca5_seconde_demande_identique_renvoie_409(client: AsyncClient, plateforme: dict):
    tenant = await _creer_tenant(client, plateforme)
    tenant_id = tenant["tenantId"]

    premiere = await _transition(client, plateforme, tenant_id, "provisioning", tenant["version"])
    assert premiere.status_code == 200, premiere.text

    seconde = await _transition(client, plateforme, tenant_id, "provisioning", tenant["version"])
    assert seconde.status_code == 409, seconde.text


# ---------------------------------------------------------------------------
# Compléments : slug unique, tenant inconnu
# ---------------------------------------------------------------------------


async def test_slug_deja_utilise_renvoie_409(client: AsyncClient, plateforme: dict):
    slug = f"tenant-{uuid.uuid4().hex[:10]}"
    premier = await client.post(ROUTE, json={"slug": slug}, headers=_entetes(plateforme))
    assert premier.status_code == 201, premier.text
    doublon = await client.post(ROUTE, json={"slug": slug}, headers=_entetes(plateforme))
    assert doublon.status_code == 409, doublon.text


async def test_tenant_inconnu_renvoie_404(client: AsyncClient, plateforme: dict):
    res = await client.get(f"{ROUTE}/{uuid.uuid4()}", headers=_entetes(plateforme))
    assert res.status_code == 404, res.text
