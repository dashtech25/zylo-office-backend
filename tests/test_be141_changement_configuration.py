"""BE-141 : changement de configuration et gel de credential.

Tests écrits d'après la définition `### BE-141` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Routes testées :
- `POST /api/v1/admin/organizations/{organization_id}/config-changes` (201, 200 au rejeu) ;
- `POST /api/v1/admin/credentials/{credential_id}/freeze` (201, 200 au rejeu) ;
- `POST /api/v1/admin/commands/{command_id}/preview` et `.../confirm` (BE-125), pour CA-4.

Couverture (critères d'acceptation de la définition) :
- CA-1 (refus de droit) : gel de credential par un agent L2 : 403 ;
- CA-2 : aucune réponse ni ligne `admin_command` ne contient la valeur fournie ;
- CA-3 (isolation tenant) : changement de configuration du tenant B depuis une
  affectation au tenant A : 403 ;
- CA-4 : exécution sans approbation distincte : 409 `approval_required`, sans appel au
  domaine (passe par la garde de BE-126, `app.operator.guard.executer_commande`).

Le gel de credential n'est pas prévisualisable (BE-125 exige un tenant cible) : il ne
peut donc pas atteindre la garde d'exécution. Ce point est consigné en QE dans le
rapport de la tâche ; le CA-4 est vérifié sur le changement de configuration, qui porte
la même classe `configuration.modification`.

Aucune fixture massive : chaque test crée son utilisateur, son organisation, son réglage
et son credential. Les affectations de rôle sont posées directement en base, comme dans
BE-124, BE-125 et BE-135.
"""

import json
import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal

MOT_DE_PASSE = "TestPassword123!"
ROLE_GESTION = "securite_incident_commander"
ROLE_L2 = "agent_support_l2"
TYPE_CLASSE_CONFIG = "configuration.modification"
DUREE_PREVIEW_TEST = 600


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = f"be141-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-141"})
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
        json={"name": nom, "slug": f"tenant-be141-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()["id"]


async def _reglage(cle: str | None = None) -> str:
    """Déclare un réglage dans `settings_registry` (BE-237) et renvoie sa clé."""
    from app.settings.models import SettingsRegistry

    cle = cle or f"be141.reglage.{uuid.uuid4().hex[:12]}"
    async with AsyncSessionLocal() as db:
        db.add(SettingsRegistry(
            key=cle,
            scopeKind="tenant",
            owner="exploitation",
            secret=False,
            effect="runtime",
            effectiveAt=None,
            defaultValue=None,
        ))
        await db.commit()
    return cle


async def _credential() -> str:
    """Déclare un credential dans `secret_registry` (BE-230) et renvoie son identifiant."""
    from app.operator.secrets_models import SecretRegistry

    async with AsyncSessionLocal() as db:
        ligne = SecretRegistry(
            name=f"BE141_{uuid.uuid4().hex[:12].upper()}",
            owner="exploitation",
            scope="environment",
            expiresAt=None,
            lastRotatedAt=None,
            consumer="tests.be141",
            required=True,
        )
        db.add(ligne)
        await db.commit()
        return str(ligne.id)


def _corps_changement(cle_reglage: str, valeur: str = "valeur-ordinaire", motif: str = "INC-141") -> dict:
    return {
        "settingKey": cle_reglage,
        "valeur": valeur,
        "reasonTicket": motif,
        "idempotencyKey": uuid.uuid4().hex,
    }


def _corps_gel(motif: str = "INC-141-GEL") -> dict:
    return {"reasonTicket": motif, "idempotencyKey": uuid.uuid4().hex}


def _chemin_changement(organisation_id: str) -> str:
    return f"/api/v1/admin/organizations/{organisation_id}/config-changes"


def _chemin_gel(credential_id: str) -> str:
    return f"/api/v1/admin/credentials/{credential_id}/freeze"


async def test_ca1_gel_de_credential_par_agent_l2_403(client: AsyncClient):
    """CA-1 (refus de droit) : un agent L2 ne peut pas geler un credential."""
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], ROLE_L2, "platform")
    credential_id = await _credential()

    reponse = await client.post(_chemin_gel(credential_id), json=_corps_gel(), headers=_entetes(agent))

    assert reponse.status_code == 403, reponse.text


async def test_ca2_valeur_absente_de_la_reponse_et_du_journal(client: AsyncClient):
    """CA-2 : la valeur fournie n'apparaît ni dans la réponse ni dans la ligne `admin_command`."""
    from app.operator.commands import AdminCommand

    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant CA-2 BE-141")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    cle_reglage = await _reglage()
    sentinelle = f"SENTINELLE-BE141-{uuid.uuid4().hex}"

    reponse = await client.post(
        _chemin_changement(organisation_id),
        json=_corps_changement(cle_reglage, valeur=sentinelle),
        headers=_entetes(gestionnaire),
    )

    assert reponse.status_code == 201, reponse.text
    assert sentinelle not in reponse.text
    async with AsyncSessionLocal() as db:
        ligne = (await db.execute(
            select(AdminCommand).where(AdminCommand.commandId == uuid.UUID(reponse.json()["commandId"]))
        )).scalar_one()
    assert sentinelle not in json.dumps(ligne.payload or {}, default=str)
    assert sentinelle not in json.dumps(ligne.result or {}, default=str)
    assert sentinelle not in ligne.reasonTicket


async def test_ca3_changement_tenant_b_depuis_affectation_tenant_a_403(client: AsyncClient):
    """CA-3 (isolation tenant) : un gestionnaire du tenant A ne peut pas changer la configuration du tenant B."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant_a = await _organisation(client, gestionnaire, "Tenant A CA-3 BE-141")
    tenant_b = await _organisation(client, gestionnaire, "Tenant B CA-3 BE-141")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant_a}")
    cle_reglage = await _reglage()

    reponse = await client.post(
        _chemin_changement(tenant_b),
        json=_corps_changement(cle_reglage),
        headers=_entetes(gestionnaire),
    )

    assert reponse.status_code == 403, reponse.text


async def test_ca4_execution_sans_approbation_distincte_409(client: AsyncClient, monkeypatch):
    """CA-4 : une intention de configuration exécutée sans approbateur distinct répond 409, sans appel au domaine.

    Parcours réel : intention (201), preview (201), confirmation (200), puis garde
    d'exécution de BE-126 avec un domaine fictif enregistré pour la classe.
    """
    from app.operator.guard import EXECUTEURS, executer_commande

    monkeypatch.setattr(settings, "ADMIN_PREVIEW_TTL_SECONDS", DUREE_PREVIEW_TEST)
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant CA-4 BE-141")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    cle_reglage = await _reglage()
    intention = await client.post(
        _chemin_changement(organisation_id), json=_corps_changement(cle_reglage), headers=_entetes(gestionnaire),
    )
    assert intention.status_code == 201, intention.text
    command_id = intention.json()["commandId"]
    preview = await client.post(f"/api/v1/admin/commands/{command_id}/preview", headers=_entetes(gestionnaire))
    assert preview.status_code == 201, preview.text
    confirmation = await client.post(
        f"/api/v1/admin/commands/{command_id}/confirm",
        json={"previewId": preview.json()["previewId"]},
        headers=_entetes(gestionnaire),
    )
    assert confirmation.status_code == 200, confirmation.text

    appels = []

    async def domaine_fictif(db, commande):
        appels.append(commande.commandId)
        return {"appliquee": True}

    monkeypatch.setitem(EXECUTEURS, TYPE_CLASSE_CONFIG, domaine_fictif)
    async with AsyncSessionLocal() as db:
        try:
            await executer_commande(
                db,
                command_id=uuid.UUID(command_id),
                actor_id=uuid.UUID(gestionnaire["id"]),
                preview_id=uuid.UUID(preview.json()["previewId"]),
            )
            raise AssertionError("La garde aurait dû refuser l'exécution sans approbateur.")
        except Exception as erreur:  # noqa: BLE001 : on vérifie le code de l'AppError
            assert getattr(erreur, "code", None) == "approval_required", repr(erreur)
            assert getattr(erreur, "status_code", None) == 409
    assert appels == []


async def test_nominal_changement_puis_rejeu_identique_200(client: AsyncClient):
    """Création de l'intention de changement (201), puis rejeu de la même clé (200)."""
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant nominal BE-141")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    cle_reglage = await _reglage()
    corps = _corps_changement(cle_reglage)

    premier = await client.post(_chemin_changement(organisation_id), json=corps, headers=_entetes(gestionnaire))
    rejeu = await client.post(_chemin_changement(organisation_id), json=corps, headers=_entetes(gestionnaire))

    assert premier.status_code == 201, premier.text
    assert premier.json()["commandType"] == TYPE_CLASSE_CONFIG
    assert premier.json()["status"] == "intention"
    assert premier.json()["tenantId"] == organisation_id
    assert premier.json()["settingKey"] == cle_reglage
    assert rejeu.status_code == 200, rejeu.text
    assert rejeu.json()["commandId"] == premier.json()["commandId"]


async def test_nominal_gel_de_credential_puis_rejeu_200(client: AsyncClient):
    """Gel par le rôle sécurité sur la portée plateforme (201), puis rejeu de la même clé (200)."""
    responsable = await _nouvel_utilisateur(client)
    await _accorder(responsable["id"], ROLE_GESTION, "platform")
    credential_id = await _credential()
    corps = _corps_gel()

    premier = await client.post(_chemin_gel(credential_id), json=corps, headers=_entetes(responsable))
    rejeu = await client.post(_chemin_gel(credential_id), json=corps, headers=_entetes(responsable))

    assert premier.status_code == 201, premier.text
    assert premier.json()["commandType"] == TYPE_CLASSE_CONFIG
    assert premier.json()["status"] == "intention"
    assert premier.json()["targetObjectId"] == credential_id
    assert rejeu.status_code == 200, rejeu.text
    assert rejeu.json()["commandId"] == premier.json()["commandId"]


async def test_reglage_inconnu_422(client: AsyncClient):
    """Un réglage absent du registre BE-237 est refusé avant toute écriture."""
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant reglage BE-141")
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")

    reponse = await client.post(
        _chemin_changement(organisation_id),
        json=_corps_changement(f"inconnu.{uuid.uuid4().hex[:12]}"),
        headers=_entetes(gestionnaire),
    )

    assert reponse.status_code == 422, reponse.text


async def test_credential_inconnu_404(client: AsyncClient):
    """Gel d'un identifiant absent du registre des secrets : 404, sans intention créée."""
    responsable = await _nouvel_utilisateur(client)
    await _accorder(responsable["id"], ROLE_GESTION, "platform")

    reponse = await client.post(_chemin_gel(str(uuid.uuid4())), json=_corps_gel(), headers=_entetes(responsable))

    assert reponse.status_code == 404, reponse.text
