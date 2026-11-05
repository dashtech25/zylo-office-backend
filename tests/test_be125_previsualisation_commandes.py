"""BE-125 : prévisualisation et confirmation des commandes opérateur.

Tests écrits d'après la définition `### BE-125` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Routes testées :
- `POST /api/v1/admin/commands/{command_id}/preview` (201) ;
- `POST /api/v1/admin/commands/{command_id}/confirm`, corps `{"previewId": ...}` (200).

Couverture (critères d'acceptation de la définition) :
- CA-1 : la preview ne modifie aucun état métier (état avant = état après) ;
- CA-2 : confirmation après `expiresAtUtc` : 409 ;
- CA-3 : confirmation après changement de version de l'objet : 409 ;
- CA-4 (refus de droit) : preview et confirmation par un autre acteur que l'initiateur : 403 ;
- CA-5 (isolation tenant) : la preview affiche l'identifiant canonique du tenant cible ;
  une preview sans tenant cible est refusée (422).

Hypothèses consignées (voir `app/operator/preview.py`) : la durée de preview n'a pas de
valeur par défaut (QE-ADM-07) ; le test la fixe par `monkeypatch` sur le réglage, comme
un paramètre d'exploitation. Sans réglage, la preview est refusée (503), testé aussi.
L'expiration (CA-2) est simulée en ramenant `expiresAtUtc` dans le passé en base, sans
attendre. Les affectations de rôle sont posées directement en base (`_accorder`), comme
dans les tests BE-124.
"""

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal

CHEMIN_COMMANDES = "/api/v1/admin/commands"
MOT_DE_PASSE = "TestPassword123!"
CLASSE = "tenant.suspension"
ROLE_GESTION = "securite_incident_commander"
DUREE_PREVIEW_TEST = 600


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = f"be125-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-125"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    return {"id": me.json()["id"], "accessToken": jetons["accessToken"]}


async def _accorder(actor_id: str, role_code: str, scope: str) -> None:
    from datetime import datetime as _dt

    from app.rbac.role_assignments import AdminRoleAssignment

    async with AsyncSessionLocal() as db:
        db.add(AdminRoleAssignment(
            actorId=uuid.UUID(actor_id),
            roleCode=role_code,
            scope=scope,
            grantedBy=uuid.UUID(actor_id),
            grantedAt=_dt.now(timezone.utc),
            expiresAt=None,
            revokedAt=None,
        ))
        await db.commit()


async def _organisation(client: AsyncClient, proprietaire: dict) -> str:
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant BE-125", "slug": f"tenant-be125-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()["id"]


async def _version_organisation(tenant_id: str) -> int:
    """Version courante de l'organisation, lue en base (BE-233)."""
    from app.identity.models import Organization

    async with AsyncSessionLocal() as db:
        return (await db.get(Organization, uuid.UUID(tenant_id))).version


async def _creer_commande(client: AsyncClient, acteur: dict, tenant_id: str) -> str:
    """Crée une intention valide visant le tenant, à la version courante, et renvoie son id."""
    version = await _version_organisation(tenant_id)
    corps = {
        "commandType": CLASSE,
        "commandVersion": 1,
        "tenantId": tenant_id,
        "targetObjectType": "Tenant",
        "targetObjectId": tenant_id,
        "targetVersionExpected": version,
        "reasonTicket": "INC-125",
        "idempotencyKey": uuid.uuid4().hex,
    }
    reponse = await client.post(CHEMIN_COMMANDES, json=corps, headers=_entetes(acteur))
    assert reponse.status_code == 201, reponse.text
    return reponse.json()["commandId"]


async def _etat_metier(tenant_id: str) -> dict:
    """Instantané de l'état métier observable : organisation et commandes de ce tenant."""
    from app.identity.models import Organization
    from app.operator.commands import AdminCommand

    async with AsyncSessionLocal() as db:
        org = await db.get(Organization, uuid.UUID(tenant_id))
        commandes = (await db.execute(
            select(AdminCommand.commandId, AdminCommand.status, AdminCommand.commandVersion, AdminCommand.result)
            .where(AdminCommand.targetObjectId == tenant_id)
        )).all()
        return {
            "organisation": (org.name, org.status, org.version),
            "commandes": sorted((str(c), s, v, r) for c, s, v, r in commandes),
        }


async def _expirer_preview(preview_id: str) -> None:
    """Ramène `expiresAtUtc` dans le passé : simule l'écoulement de la durée de preview."""
    from app.operator.preview import AdminCommandPreview

    async with AsyncSessionLocal() as db:
        preview = await db.get(AdminCommandPreview, uuid.UUID(preview_id))
        preview.expiresAtUtc = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()


def _fixer_duree(monkeypatch, duree: int | None = DUREE_PREVIEW_TEST) -> None:
    monkeypatch.setattr(settings, "ADMIN_PREVIEW_TTL_SECONDS", duree)


async def _previsualiser(client: AsyncClient, acteur: dict, command_id: str):
    return await client.post(f"{CHEMIN_COMMANDES}/{command_id}/preview", headers=_entetes(acteur))


async def _confirmer(client: AsyncClient, acteur: dict, command_id: str, preview_id: str):
    return await client.post(
        f"{CHEMIN_COMMANDES}/{command_id}/confirm",
        json={"previewId": preview_id},
        headers=_entetes(acteur),
    )


async def test_ca1_la_preview_ne_modifie_aucun_etat_metier(client: AsyncClient, monkeypatch):
    """CA-1 : l'état métier est identique avant et après la preview."""
    _fixer_duree(monkeypatch)
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    command_id = await _creer_commande(client, gestionnaire, tenant)
    avant = await _etat_metier(tenant)

    reponse = await _previsualiser(client, gestionnaire, command_id)

    assert reponse.status_code == 201, reponse.text
    assert await _etat_metier(tenant) == avant


async def test_ca2_confirmation_apres_expiration_renvoie_409(client: AsyncClient, monkeypatch):
    """CA-2 : une preview dont `expiresAtUtc` est dépassé ne se confirme plus (409)."""
    _fixer_duree(monkeypatch)
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    command_id = await _creer_commande(client, gestionnaire, tenant)
    preview = (await _previsualiser(client, gestionnaire, command_id)).json()
    await _expirer_preview(preview["previewId"])

    reponse = await _confirmer(client, gestionnaire, command_id, preview["previewId"])

    assert reponse.status_code == 409, reponse.text


async def test_ca3_confirmation_apres_changement_de_version_renvoie_409(client: AsyncClient, monkeypatch):
    """CA-3 : une mutation de l'organisation après la preview invalide la confirmation (409)."""
    _fixer_duree(monkeypatch)
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    command_id = await _creer_commande(client, gestionnaire, tenant)
    preview = (await _previsualiser(client, gestionnaire, command_id)).json()

    modification = await client.patch(
        f"/api/v1/organizations/{tenant}",
        json={"name": "Tenant BE-125 renommé"},
        headers=_entetes(gestionnaire),
    )
    assert modification.status_code == 200, modification.text
    reponse = await _confirmer(client, gestionnaire, command_id, preview["previewId"])

    assert reponse.status_code == 409, reponse.text


async def test_ca4_preview_et_confirmation_reservees_a_l_initiateur(client: AsyncClient, monkeypatch):
    """CA-4 : un autre acteur, même habilité, ne prévisualise ni ne confirme (403)."""
    _fixer_duree(monkeypatch)
    initiateur = await _nouvel_utilisateur(client)
    autre = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, initiateur)
    await _accorder(initiateur["id"], ROLE_GESTION, f"tenant:{tenant}")
    await _accorder(autre["id"], ROLE_GESTION, f"tenant:{tenant}")
    command_id = await _creer_commande(client, initiateur, tenant)
    preview = (await _previsualiser(client, initiateur, command_id)).json()

    preview_par_autre = await _previsualiser(client, autre, command_id)
    confirmation_par_autre = await _confirmer(client, autre, command_id, preview["previewId"])

    assert preview_par_autre.status_code == 403, preview_par_autre.text
    assert confirmation_par_autre.status_code == 403, confirmation_par_autre.text


async def test_ca5_preview_affiche_le_tenant_canonique(client: AsyncClient, monkeypatch):
    """CA-5 : la preview porte l'identifiant canonique du tenant cible."""
    _fixer_duree(monkeypatch)
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    command_id = await _creer_commande(client, gestionnaire, tenant)

    reponse = await _previsualiser(client, gestionnaire, command_id)

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["tenantId"] == str(uuid.UUID(tenant))


async def test_ca5_preview_sans_tenant_cible_renvoie_422(client: AsyncClient, monkeypatch):
    """CA-5 : une commande de portée plateforme, sans tenant cible, n'a pas de preview (422)."""
    _fixer_duree(monkeypatch)
    gestionnaire = await _nouvel_utilisateur(client)
    await _accorder(gestionnaire["id"], ROLE_GESTION, "platform")
    corps = {
        "commandType": CLASSE,
        "commandVersion": 1,
        "tenantId": None,
        "targetObjectType": "Tenant",
        "targetObjectId": str(uuid.uuid4()),
        "targetVersionExpected": None,
        "reasonTicket": "INC-125",
        "idempotencyKey": uuid.uuid4().hex,
    }
    cree = await client.post(CHEMIN_COMMANDES, json=corps, headers=_entetes(gestionnaire))
    assert cree.status_code == 201, cree.text

    reponse = await _previsualiser(client, gestionnaire, cree.json()["commandId"])

    assert reponse.status_code == 422, reponse.text


async def test_preview_sans_duree_configuree_est_refusee(client: AsyncClient, monkeypatch):
    """QE-ADM-07 : sans durée de preview configurée, aucune preview n'est créée (503)."""
    _fixer_duree(monkeypatch, None)
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    command_id = await _creer_commande(client, gestionnaire, tenant)

    reponse = await _previsualiser(client, gestionnaire, command_id)

    assert reponse.status_code == 503, reponse.text
