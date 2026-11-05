"""BE-126 : garde de commande (pipeline d'exécution).

Tests écrits d'après la définition `### BE-126` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Le pipeline n'a pas de route propre : il est appelé par
`app.operator.guard.executer_commande` (la branche sur `confirm` est reportée, voir le
docstring de `app.operator.guard`). Les tests l'appellent donc directement, avec une
session de test, et injectent un domaine propriétaire fictif dans `EXECUTEURS`
(QE-ADM-22 non résolu).

Couverture (critères d'acceptation de la définition) :
- CA-1 : ordre des étapes, vérifié sur un enregistreur d'étapes (et parcours nominal) ;
- CA-2 (refus de droit) : droit révoqué entre preview et exécution : 403, aucun effet ;
- CA-3 : l'intention d'audit est persistée avant l'appel au domaine propriétaire ;
- CA-4 (isolation tenant) : tenant de la commande changé après la preview : 409, aucun effet ;
- CA-5 : résultat inconnu du domaine : arrêt 409, pas de second appel ;
- garde d'approbation : classe à double validation sans approbateur : 409, aucun effet.

Les fixtures et helpers HTTP reprennent ceux de BE-124, BE-125 et BE-128.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.operator import guard
from app.operator.commands import AdminCommand
from app.operator.guard import ETAPES, EXECUTEURS, ResultatInconnu, executer_commande
from app.rbac.role_assignments import AdminRoleAssignment

CHEMIN_COMMANDES = "/api/v1/admin/commands"
MOT_DE_PASSE = "TestPassword123!"
CLASSE = "tenant.suspension"
ROLE_GESTION = "securite_incident_commander"
ROLE_APPROBATION = "approbateur_independant"
DUREE_PREVIEW_TEST = 600


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = f"be126-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-126"})
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


async def _revoquer(actor_id: str) -> None:
    """Retire tous les rôles d'administration du compte, comme BE-121 le fait."""
    async with AsyncSessionLocal() as db:
        affectations = (await db.execute(
            select(AdminRoleAssignment).where(AdminRoleAssignment.actorId == uuid.UUID(actor_id))
        )).scalars().all()
        for affectation in affectations:
            affectation.revokedAt = datetime.now(timezone.utc)
        await db.commit()


async def _organisation(client: AsyncClient, proprietaire: dict) -> str:
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant BE-126", "slug": f"tenant-be126-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()["id"]


async def _version_organisation(tenant_id: str) -> int:
    from app.identity.models import Organization

    async with AsyncSessionLocal() as db:
        return (await db.get(Organization, uuid.UUID(tenant_id))).version


async def _creer_commande(client: AsyncClient, acteur: dict, tenant_id: str) -> str:
    version = await _version_organisation(tenant_id)
    corps = {
        "commandType": CLASSE,
        "commandVersion": 1,
        "tenantId": tenant_id,
        "targetObjectType": "Tenant",
        "targetObjectId": tenant_id,
        "targetVersionExpected": version,
        "reasonTicket": "INC-126",
        "idempotencyKey": uuid.uuid4().hex,
    }
    reponse = await client.post(CHEMIN_COMMANDES, json=corps, headers=_entetes(acteur))
    assert reponse.status_code == 201, reponse.text
    return reponse.json()["commandId"]


async def _commande_confirmee(client: AsyncClient, monkeypatch, *, approuver: bool) -> dict:
    """Une commande initiée, prévisualisée et confirmée, approuvée si demandé.

    La durée de preview est fixée par le réglage, comme en BE-125 (QE-ADM-07).
    """
    monkeypatch.setattr(settings, "ADMIN_PREVIEW_TTL_SECONDS", DUREE_PREVIEW_TEST)
    gestionnaire = await _nouvel_utilisateur(client)
    tenant = await _organisation(client, gestionnaire)
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant}")
    command_id = await _creer_commande(client, gestionnaire, tenant)
    preview = await client.post(f"{CHEMIN_COMMANDES}/{command_id}/preview", headers=_entetes(gestionnaire))
    assert preview.status_code == 201, preview.text
    preview_id = preview.json()["previewId"]
    if approuver:
        approbateur = await _nouvel_utilisateur(client)
        await _accorder(approbateur["id"], ROLE_APPROBATION, f"tenant:{tenant}")
        decision = await client.post(
            f"{CHEMIN_COMMANDES}/{command_id}/approve",
            json={"reasonTicket": "INC-126-APPROBATION"},
            headers=_entetes(approbateur),
        )
        assert decision.status_code == 200, decision.text
    confirmation = await client.post(
        f"{CHEMIN_COMMANDES}/{command_id}/confirm",
        json={"previewId": preview_id},
        headers=_entetes(gestionnaire),
    )
    assert confirmation.status_code == 200, confirmation.text
    return {
        "gestionnaire": gestionnaire,
        "tenant": tenant,
        "command_id": command_id,
        "preview_id": preview_id,
    }


async def _pipeline(ctx: dict, etapes: list[str] | None = None) -> AdminCommand:
    async with AsyncSessionLocal() as db:
        return await executer_commande(
            db,
            command_id=uuid.UUID(ctx["command_id"]),
            actor_id=uuid.UUID(ctx["gestionnaire"]["id"]),
            preview_id=uuid.UUID(ctx["preview_id"]),
            etapes=etapes,
        )


async def _statut(command_id: str) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.get(AdminCommand, uuid.UUID(command_id))).status


async def _nombre_audits_intention(command_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return len((await db.execute(
            select(AuditEvent.eventId).where(
                AuditEvent.action == guard.ACTION_INTENTION,
                AuditEvent.entityId == uuid.UUID(command_id),
            )
        )).all())


@pytest.fixture
def appels_domaine(monkeypatch):
    """Domaine propriétaire fictif, enregistré pour la classe de test ; liste des appels."""
    appels: list[str] = []

    async def domaine(db, commande: AdminCommand) -> dict:
        appels.append(str(commande.commandId))
        return {"appliquee": True}

    monkeypatch.setitem(EXECUTEURS, CLASSE, domaine)
    return appels


async def test_ca1_ordre_des_etapes_et_parcours_nominal(client: AsyncClient, monkeypatch, appels_domaine):
    """CA-1 : les étapes passent dans l'ordre de la définition ; la commande finit `executee`."""
    ctx = await _commande_confirmee(client, monkeypatch, approuver=True)
    etapes: list[str] = []

    commande = await _pipeline(ctx, etapes)

    assert etapes == list(ETAPES)
    assert commande.status == "executee"
    assert appels_domaine == [ctx["command_id"]]


async def test_ca2_droit_retire_entre_preview_et_execution_renvoie_403_sans_effet(
    client: AsyncClient, monkeypatch, appels_domaine,
):
    """CA-2 : rôle révoqué après la preview : 403, aucun appel au domaine, aucune audit."""
    ctx = await _commande_confirmee(client, monkeypatch, approuver=True)
    await _revoquer(ctx["gestionnaire"]["id"])

    with pytest.raises(AppError) as erreur:
        await _pipeline(ctx)

    assert erreur.value.status_code == 403
    assert appels_domaine == []
    assert await _nombre_audits_intention(ctx["command_id"]) == 0
    assert await _statut(ctx["command_id"]) == "approuvee"


async def test_ca3_intention_d_audit_persistee_avant_l_appel_au_domaine(
    client: AsyncClient, monkeypatch,
):
    """CA-3 : au moment de l'appel au domaine, l'intention d'audit est déjà en base (vue d'une autre session)."""
    ctx = await _commande_confirmee(client, monkeypatch, approuver=True)
    vues_au_moment_de_l_appel: list[int] = []

    async def domaine(db, commande: AdminCommand) -> dict:
        vues_au_moment_de_l_appel.append(await _nombre_audits_intention(str(commande.commandId)))
        return {"appliquee": True}

    monkeypatch.setitem(EXECUTEURS, CLASSE, domaine)
    await _pipeline(ctx)

    assert vues_au_moment_de_l_appel == [1]


async def test_ca4_tenant_change_entre_preview_et_commit_renvoie_409_sans_effet(
    client: AsyncClient, monkeypatch, appels_domaine,
):
    """CA-4 : le tenant de la commande ne correspond plus à celui de la preview : 409, aucun effet."""
    ctx = await _commande_confirmee(client, monkeypatch, approuver=True)
    autre_tenant = await _organisation(client, ctx["gestionnaire"])
    async with AsyncSessionLocal() as db:
        commande = await db.get(AdminCommand, uuid.UUID(ctx["command_id"]))
        commande.tenantId = uuid.UUID(autre_tenant)
        await db.commit()

    with pytest.raises(AppError) as erreur:
        await _pipeline(ctx)

    assert erreur.value.status_code == 409
    assert appels_domaine == []
    assert await _nombre_audits_intention(ctx["command_id"]) == 0


async def test_ca5_resultat_inconnu_arrete_le_pipeline_sans_second_appel(
    client: AsyncClient, monkeypatch,
):
    """CA-5 : le domaine répond « résultat inconnu » : 409, statut `resultat_inconnu`, un seul appel."""
    ctx = await _commande_confirmee(client, monkeypatch, approuver=True)
    appels: list[str] = []

    async def domaine(db, commande: AdminCommand) -> dict:
        appels.append(str(commande.commandId))
        raise ResultatInconnu("délai dépassé côté domaine")

    monkeypatch.setitem(EXECUTEURS, CLASSE, domaine)

    with pytest.raises(AppError) as erreur:
        await _pipeline(ctx)
    assert erreur.value.status_code == 409
    assert await _statut(ctx["command_id"]) == "resultat_inconnu"

    with pytest.raises(AppError) as second_essai:
        await _pipeline(ctx)
    assert second_essai.value.status_code == 409
    assert appels == [ctx["command_id"]]


async def test_garde_approbation_classe_a_double_validation_sans_approbateur_renvoie_409(
    client: AsyncClient, monkeypatch, appels_domaine,
):
    """Classe à double validation sans approbation : 409 `approval_required`, aucun effet."""
    ctx = await _commande_confirmee(client, monkeypatch, approuver=False)

    with pytest.raises(AppError) as erreur:
        await _pipeline(ctx)

    assert erreur.value.status_code == 409
    assert erreur.value.code == "approval_required"
    assert appels_domaine == []
    assert await _nombre_audits_intention(ctx["command_id"]) == 0
