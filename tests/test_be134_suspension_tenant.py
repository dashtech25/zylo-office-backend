"""BE-134 : suspension et rétablissement d'un tenant.

Tests écrits d'après la définition `### BE-134` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Routes testées :
- `POST /api/v1/admin/organizations/{organization_id}/suspension` (201, 200 au rejeu) ;
- `POST /api/v1/admin/organizations/{organization_id}/reinstatement` (201, 409 sans préconditions) ;
- `POST /api/v1/admin/commands/{command_id}/preview` (201), pour le contenu de la preview ;
- `POST /api/v1/admin/commands/{command_id}/confirm` (200), avant l'exécution testée en CA-2.

Couverture (critères d'acceptation de la définition) :
- CA-1 (refus de droit) : agent L1 demandant la suspension : 403 ;
- CA-2 : suspension sans approbation distincte : 409 `approval_required` à l'exécution ;
- CA-3 (isolation tenant) : suspension d'un tenant hors portée de l'opérateur : 403 ;
- CA-4 : la preview expose connexion, opérations en cours, API, exports et facturation ;
- CA-5 : le rejeu de la même commande (même clé) ne crée pas une seconde intention ;
- rétablissement : sans tenant suspendu (préconditions non remplies) : 409.

Les affectations de rôle sont posées directement en base, comme dans BE-124 à BE-135.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import Tenant
from app.operator.commands import AdminCommand
from app.operator.guard import EXECUTEURS, executer_commande

MOT_DE_PASSE = "TestPassword123!"
ROLE_GESTION = "securite_incident_commander"
ROLE_L1 = "agent_support_l1"
CLASSE = "tenant.suspension"
DUREE_PREVIEW_TEST = 600
CHEMIN_ADMIN = "/api/v1/admin"


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = f"be134-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-134"})
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


async def _tenant_suspendu(organisation_id: str, statut: str) -> None:
    """Pose la ligne `tenant` de l'organisation avec le statut donné (cycle de vie BE-185)."""
    async with AsyncSessionLocal() as db:
        db.add(Tenant(
            organizationId=uuid.UUID(organisation_id),
            status=statut,
            slug=f"be134-{uuid.uuid4().hex[:10]}",
            version=1,
        ))
        await db.commit()


async def _organisation(client: AsyncClient, proprietaire: dict, nom: str) -> str:
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"tenant-be134-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()["id"]


def _corps(motif: str = "INC-134", cle: str | None = None) -> dict:
    return {
        "reasonTicket": motif,
        "idempotencyKey": cle or uuid.uuid4().hex,
    }


def _chemin(organisation_id: str, operation: str) -> str:
    return f"{CHEMIN_ADMIN}/organizations/{organisation_id}/{operation}"


def _fixer_duree(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_PREVIEW_TTL_SECONDS", DUREE_PREVIEW_TEST)


async def test_ca1_agent_l1_demandant_la_suspension_403(client: AsyncClient):
    """CA-1 (refus de droit) : un agent L1 ne peut pas demander la suspension d'un tenant."""
    proprietaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, proprietaire, "Tenant CA-1 BE-134")
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], ROLE_L1, f"tenant:{organisation_id}")

    reponse = await client.post(_chemin(organisation_id, "suspension"), json=_corps(), headers=_entetes(agent))

    assert reponse.status_code == 403, reponse.text


async def test_ca2_suspension_sans_approbation_distincte_409(client: AsyncClient, monkeypatch):
    """CA-2 : une suspension confirmée mais sans approbateur distinct n'est pas exécutée (409).

    Le domaine propriétaire est fictif (QE-ADM-22) : aucun appel ne doit lui parvenir.
    """
    _fixer_duree(monkeypatch)
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant CA-2 BE-134")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    intention = await client.post(_chemin(organisation_id, "suspension"), json=_corps(), headers=_entetes(gestionnaire))
    assert intention.status_code == 201, intention.text
    command_id = intention.json()["commandId"]
    preview = await client.post(f"{CHEMIN_ADMIN}/commands/{command_id}/preview", headers=_entetes(gestionnaire))
    assert preview.status_code == 201, preview.text
    preview_id = preview.json()["previewId"]
    confirmation = await client.post(
        f"{CHEMIN_ADMIN}/commands/{command_id}/confirm",
        json={"previewId": preview_id},
        headers=_entetes(gestionnaire),
    )
    assert confirmation.status_code == 200, confirmation.text
    appels: list[str] = []

    async def domaine(db, commande: AdminCommand) -> dict:
        appels.append(str(commande.commandId))
        return {"suspendu": True}

    monkeypatch.setitem(EXECUTEURS, CLASSE, domaine)
    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await executer_commande(
                db,
                command_id=uuid.UUID(command_id),
                actor_id=uuid.UUID(gestionnaire["id"]),
                preview_id=uuid.UUID(preview_id),
            )

    assert erreur.value.status_code == 409
    assert erreur.value.code == "approval_required"
    assert appels == []


async def test_ca3_suspension_tenant_hors_portee_403(client: AsyncClient):
    """CA-3 (isolation tenant) : un gestionnaire du tenant A ne peut pas suspendre le tenant B."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant_a = await _organisation(client, gestionnaire, "Tenant A CA-3 BE-134")
    tenant_b = await _organisation(client, gestionnaire, "Tenant B CA-3 BE-134")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant_a}")

    reponse = await client.post(_chemin(tenant_b, "suspension"), json=_corps(), headers=_entetes(gestionnaire))

    assert reponse.status_code == 403, reponse.text


async def test_ca4_preview_expose_connexion_operations_api_exports_facturation(client: AsyncClient, monkeypatch):
    """CA-4 (test de schéma) : la preview de suspension porte les cinq rubriques d'impact."""
    _fixer_duree(monkeypatch)
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant CA-4 BE-134")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    intention = await client.post(_chemin(organisation_id, "suspension"), json=_corps(), headers=_entetes(gestionnaire))
    assert intention.status_code == 201, intention.text

    preview = await client.post(
        f"{CHEMIN_ADMIN}/commands/{intention.json()['commandId']}/preview",
        headers=_entetes(gestionnaire),
    )

    assert preview.status_code == 201, preview.text
    effets = preview.json()["effects"]
    assert effets["operation"] == "suspension"
    assert isinstance(effets["connexion"]["utilisateursAffectes"], int)
    assert isinstance(effets["operationsEnCours"]["commandesOuvertes"], int)
    for rubrique in ("api", "exports", "facturation"):
        assert isinstance(effets[rubrique]["effet"], str)


async def test_ca5_rejeu_de_la_meme_cle_ne_suspend_pas_deux_fois(client: AsyncClient):
    """CA-5 (test d'idempotence) : le même envoi renvoie la même intention, sans seconde ligne."""
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant CA-5 BE-134")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    corps = _corps()

    premier = await client.post(_chemin(organisation_id, "suspension"), json=corps, headers=_entetes(gestionnaire))
    rejeu = await client.post(_chemin(organisation_id, "suspension"), json=corps, headers=_entetes(gestionnaire))

    assert premier.status_code == 201, premier.text
    assert rejeu.status_code == 200, rejeu.text
    assert rejeu.json()["commandId"] == premier.json()["commandId"]
    assert premier.json()["commandType"] == CLASSE
    async with AsyncSessionLocal() as db:
        nombre = (await db.execute(
            select(func.count()).select_from(AdminCommand).where(AdminCommand.idempotencyKey == corps["idempotencyKey"])
        )).scalar_one()
    assert nombre == 1


async def test_rétablissement_sans_tenant_suspendu_409(client: AsyncClient):
    """Rétablissement : préconditions non remplies (le tenant n'est pas suspendu) : 409."""
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant rétablissement KO BE-134")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")

    reponse = await client.post(_chemin(organisation_id, "reinstatement"), json=_corps(), headers=_entetes(gestionnaire))

    assert reponse.status_code == 409, reponse.text


async def test_rétablissement_avec_tenant_suspendu_201(client: AsyncClient):
    """Rétablissement nominal : tenant suspendu, intention créée avec l'opération `reinstatement`."""
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant rétablissement OK BE-134")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    await _tenant_suspendu(organisation_id, "suspended")

    reponse = await client.post(_chemin(organisation_id, "reinstatement"), json=_corps(), headers=_entetes(gestionnaire))

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["commandType"] == CLASSE
    assert reponse.json()["status"] == "intention"
    assert reponse.json()["operation"] == "reinstatement"
