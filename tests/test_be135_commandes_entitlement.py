"""BE-135 : commande d'entitlement et de module.

Tests écrits d'après la définition `### BE-135` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Routes testées :
- `POST /api/v1/admin/organizations/{organization_id}/entitlements/commands` (201, 200 au rejeu) ;
- `PATCH /api/v1/admin/organizations/{organization_id}/entitlements/{entitlement_id}` (405) ;
- `POST /api/v1/admin/commands/{command_id}/preview` (201), pour le contenu de la preview.

Couverture (critères d'acceptation de la définition) :
- CA-1 : écriture directe d'un entitlement dérivé : 405 ;
- CA-2 (refus de droit) : agent L2 demandant un changement de module : 403 ;
- CA-3 (isolation tenant) : commande visant le tenant B depuis une affectation au tenant A : 403 ;
- CA-4 : la preview liste modules et utilisateurs affectés (test de schéma) ;
- CA-5 : la commande produit un événement d'invalidation de cache (test sur la présence).

Le corps de la commande porte le module visé (`moduleCode`) et l'opération (`operation`) :
sans ces champs, l'intention ne dit pas quel droit elle modifie. Les affectations de rôle
sont posées directement en base, comme dans BE-124 et BE-125. Aucun abonnement ni module
n'est monté : seul le module de référence `zylo_liquid` (seed) est utilisé.
"""

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal

MOT_DE_PASSE = "TestPassword123!"
ROLE_GESTION = "securite_incident_commander"
ROLE_L2 = "agent_support_l2"
MODULE = "zylo_liquid"
TYPE_EVENEMENT_CACHE = "Tenant.entitlement.cache_invalidation_requested"
DUREE_PREVIEW_TEST = 600


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = f"be135-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-135"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    return {"id": me.json()["id"], "accessToken": jetons["accessToken"]}


async def _accorder(actor_id: str, role_code: str, scope: str) -> None:
    """Pose une affectation de rôle administrative sur une portée (table `admin_role_assignment`)."""
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


async def _organisation(client: AsyncClient, proprietaire: dict, nom: str) -> str:
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"tenant-be135-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()["id"]


def _corps(motif: str = "INC-135", module: str = MODULE) -> dict:
    return {
        "moduleCode": module,
        "operation": "activation",
        "reasonTicket": motif,
        "idempotencyKey": uuid.uuid4().hex,
    }


def _chemin_commandes(organisation_id: str) -> str:
    return f"/api/v1/admin/organizations/{organisation_id}/entitlements/commands"


def _fixer_duree(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_PREVIEW_TTL_SECONDS", DUREE_PREVIEW_TEST)


async def test_ca1_ecriture_directe_entitlement_derive_405(client: AsyncClient):
    """CA-1 : une écriture directe sur un entitlement dérivé répond 405, jamais une mise à jour."""
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant CA-1")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")

    reponse = await client.patch(
        f"/api/v1/admin/organizations/{organisation_id}/entitlements/{uuid.uuid4()}",
        json={"status": "active"},
        headers=_entetes(gestionnaire),
    )

    assert reponse.status_code == 405


async def test_ca2_agent_l2_changement_de_module_403(client: AsyncClient):
    """CA-2 (refus de droit) : un agent L2 ne peut pas demander un changement de module."""
    proprietaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, proprietaire, "Tenant CA-2")
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], ROLE_L2, f"tenant:{organisation_id}")

    reponse = await client.post(_chemin_commandes(organisation_id), json=_corps(), headers=_entetes(agent))

    assert reponse.status_code == 403, reponse.text


async def test_ca3_commande_tenant_b_depuis_affectation_tenant_a_403(client: AsyncClient):
    """CA-3 (isolation tenant) : un gestionnaire du tenant A ne peut pas viser le tenant B."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant_a = await _organisation(client, gestionnaire, "Tenant A CA-3")
    tenant_b = await _organisation(client, gestionnaire, "Tenant B CA-3")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant_a}")

    reponse = await client.post(_chemin_commandes(tenant_b), json=_corps(), headers=_entetes(gestionnaire))

    assert reponse.status_code == 403, reponse.text


async def test_nominal_intention_puis_rejeu_identique_200(client: AsyncClient):
    """Création de l'intention par un gestionnaire (201), puis rejeu de la même clé (200)."""
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant nominal")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    corps = _corps()

    premier = await client.post(_chemin_commandes(organisation_id), json=corps, headers=_entetes(gestionnaire))
    rejeu = await client.post(_chemin_commandes(organisation_id), json=corps, headers=_entetes(gestionnaire))

    assert premier.status_code == 201, premier.text
    assert premier.json()["commandType"] == "entitlement.module"
    assert premier.json()["status"] == "intention"
    assert premier.json()["tenantId"] == organisation_id
    assert premier.json()["moduleCode"] == MODULE
    assert rejeu.status_code == 200, rejeu.text
    assert rejeu.json()["commandId"] == premier.json()["commandId"]


async def test_ca4_preview_liste_modules_et_utilisateurs_affectes(client: AsyncClient, monkeypatch):
    """CA-4 (test de schéma) : la preview porte la liste des modules et des utilisateurs affectés."""
    _fixer_duree(monkeypatch)
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant CA-4")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    intention = await client.post(_chemin_commandes(organisation_id), json=_corps(), headers=_entetes(gestionnaire))
    assert intention.status_code == 201, intention.text
    command_id = intention.json()["commandId"]

    preview = await client.post(f"/api/v1/admin/commands/{command_id}/preview", headers=_entetes(gestionnaire))

    assert preview.status_code == 201, preview.text
    effets = preview.json()["effects"]
    assert isinstance(effets["modulesAffectes"], list)
    assert MODULE in [m["moduleCode"] for m in effets["modulesAffectes"]]
    assert isinstance(effets["utilisateursAffectes"], list)


async def test_ca5_la_commande_produit_un_evenement_d_invalidation_de_cache(client: AsyncClient):
    """CA-5 (test de présence) : l'intention écrit un événement d'invalidation dans l'outbox."""
    from app.evenements.models import OutboxEvenement

    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant CA-5")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    intention = await client.post(_chemin_commandes(organisation_id), json=_corps(), headers=_entetes(gestionnaire))
    assert intention.status_code == 201, intention.text

    async with AsyncSessionLocal() as db:
        evenements = (await db.execute(
            select(OutboxEvenement).where(
                OutboxEvenement.eventType == TYPE_EVENEMENT_CACHE,
                OutboxEvenement.tenantId == uuid.UUID(organisation_id),
            )
        )).scalars().all()

    commandes = [e.payload["payload"]["commandId"] for e in evenements]
    assert intention.json()["commandId"] in commandes
