"""BE-140 : changement de rôle ou d'adhésion d'un membre (commande sensible `role.adhesion`).

Tests écrits d'après la définition `### BE-140` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Route testée :
- `POST /api/v1/admin/organizations/{organization_id}/memberships/{user_id}/role-changes`
  (201 à la création de l'intention, 200 au rejeu identique) ;
- `POST /api/v1/admin/commands/{id}/preview`, `.../confirm` (BE-125) et `.../approve` (BE-128),
  puis `app.operator.guard.executer_commande` (BE-126), pour CA-3 et CA-4.

Couverture (critères d'acceptation de la définition) :
- CA-1 (refus de droit) : agent L1 demandant un changement de rôle : 403 ;
- CA-2 (isolation tenant) : gestionnaire du tenant A changeant un membre du tenant B : 403 ;
- CA-3 : exécution sans approbation distincte : 409 `approval_required`, aucun changement de rôle ;
- CA-4 : le changement approuvé écrit un événement d'audit avec état avant et après.

Aucune fixture massive : chaque test crée ses comptes, son organisation, ses rôles et son
membre. Les affectations de rôle opérateur sont posées directement en base, comme dans
BE-128, BE-135 et BE-141.
"""

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.rbac.models import Role, UserRole

MOT_DE_PASSE = "TestPassword123!"
ROLE_L1 = "agent_support_l1"
ROLE_GESTION = "securite_incident_commander"
ROLE_APPROBATEUR = "approbateur_independant"
TYPE_CLASSE_ROLE = "role.adhesion"
ACTION_AUDIT_CHANGEMENT = "admin.membership.role_changed"
DUREE_PREVIEW_TEST = 600
CHEMIN_COMMANDES = "/api/v1/admin/commands"
ROLE_OPERATEUR_PLATEFORME = "operateur_plateforme"
EN_TETE_PORTEE = "X-Admin-Scope"


def _entetes(utilisateur: dict, organisation_id: str) -> dict:
    """En-têtes d'un opérateur agissant sur le tenant `organisation_id` (portée tenant explicite)."""
    return {
        "Authorization": f"Bearer {utilisateur['accessToken']}",
        EN_TETE_PORTEE: f"tenant:{organisation_id}",
    }


async def _nouvel_utilisateur(client: AsyncClient, nom: str = "BE-140") -> dict:
    email = f"be140-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": nom})
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


async def _operateur(actor_id: str) -> None:
    """Autorité plateforme minimale : sans elle, `require_admin_scope` refuse avant le droit métier."""
    await _accorder(actor_id, ROLE_OPERATEUR_PLATEFORME, "platform")


async def _rattacher(organisation_id: str, utilisateur_id: str) -> None:
    """Rend l'utilisateur membre actif de l'organisation (sans rôle transverse)."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(utilisateur_id)))
        await db.commit()


async def _organisation(client: AsyncClient, proprietaire: dict, nom: str) -> str:
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"tenant-be140-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {proprietaire['accessToken']}"},
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()["id"]


async def _membre(organisation_id: str, role_ids: list[uuid.UUID] | None = None) -> str:
    """Rattache un nouvel utilisateur à l'organisation, avec les rôles transverses donnés."""
    from app.identity.models import User

    async with AsyncSessionLocal() as db:
        utilisateur = User(
            email=f"be140-membre-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com",
            fullName="Membre BE-140",
            status="active",
            hashedPassword="x",
        )
        db.add(utilisateur)
        await db.flush()
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=utilisateur.id))
        for role_id in role_ids or []:
            db.add(UserRole(userId=utilisateur.id, organizationId=uuid.UUID(organisation_id), roleId=role_id, resourceType=None, resourceId=None))
        await db.commit()
        return str(utilisateur.id)


async def _role(organisation_id: str, nom: str) -> uuid.UUID:
    """Rôle transverse sans permission, propre à l'organisation de test."""
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=uuid.UUID(organisation_id), code=f"be140-{nom}-{uuid.uuid4().hex[:6]}", name=f"Rôle BE-140 {nom}")
        db.add(role)
        await db.commit()
        return role.id


async def _roles_de(organisation_id: str, utilisateur_id: str) -> set[str]:
    async with AsyncSessionLocal() as db:
        lignes = await db.scalars(
            select(UserRole.roleId).where(
                UserRole.organizationId == uuid.UUID(organisation_id),
                UserRole.userId == uuid.UUID(utilisateur_id),
            )
        )
        return {str(r) for r in lignes.all()}


async def _membership_de(organisation_id: str, utilisateur_id: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(OrganizationUser.id).where(
                OrganizationUser.organizationId == uuid.UUID(organisation_id),
                OrganizationUser.userId == uuid.UUID(utilisateur_id),
            )
        )


def _corps(role_ids: list[str], motif: str = "INC-140") -> dict:
    return {"roleIds": role_ids, "reasonTicket": motif, "idempotencyKey": uuid.uuid4().hex}


def _chemin(organisation_id: str, utilisateur_id: str) -> str:
    return f"/api/v1/admin/organizations/{organisation_id}/memberships/{utilisateur_id}/role-changes"


async def _intention(client: AsyncClient, gestionnaire: dict, organisation_id: str, cible: str, role_ids: list[str]) -> dict:
    reponse = await client.post(_chemin(organisation_id, cible), json=_corps(role_ids), headers=_entetes(gestionnaire, organisation_id))
    assert reponse.status_code == 201, reponse.text
    return reponse.json()


async def _preview_et_confirmation(client: AsyncClient, gestionnaire: dict, organisation_id: str, command_id: str) -> str:
    preview = await client.post(f"{CHEMIN_COMMANDES}/{command_id}/preview", headers=_entetes(gestionnaire, organisation_id))
    assert preview.status_code == 201, preview.text
    confirmation = await client.post(
        f"{CHEMIN_COMMANDES}/{command_id}/confirm",
        json={"previewId": preview.json()["previewId"]},
        headers=_entetes(gestionnaire, organisation_id),
    )
    assert confirmation.status_code == 200, confirmation.text
    return preview.json()["previewId"]


async def test_ca1_changement_de_role_par_agent_l1_403(client: AsyncClient):
    """CA-1 (refus de droit) : un agent L1 ne peut pas demander un changement de rôle."""
    agent = await _nouvel_utilisateur(client, "agent L1 BE-140")
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant CA-1 BE-140")
    await _operateur(agent["id"])
    await _rattacher(organisation_id, agent["id"])
    await _accorder(agent["id"], ROLE_L1, f"tenant:{organisation_id}")
    cible = await _membre(organisation_id)
    role = await _role(organisation_id, "ca1")

    reponse = await client.post(_chemin(organisation_id, cible), json=_corps([str(role)]), headers=_entetes(agent, organisation_id))

    assert reponse.status_code == 403, reponse.text


async def test_ca2_membre_du_tenant_b_depuis_affectation_tenant_a_403(client: AsyncClient):
    """CA-2 (isolation tenant) : un gestionnaire du tenant A ne change pas un membre du tenant B."""
    gestionnaire = await _nouvel_utilisateur(client)
    tenant_a = await _organisation(client, gestionnaire, "Tenant A CA-2 BE-140")
    tenant_b = await _organisation(client, gestionnaire, "Tenant B CA-2 BE-140")
    await _operateur(gestionnaire["id"])
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{tenant_a}")
    cible = await _membre(tenant_b)
    role = await _role(tenant_b, "ca2")

    reponse = await client.post(_chemin(tenant_b, cible), json=_corps([str(role)]), headers=_entetes(gestionnaire, tenant_b))

    assert reponse.status_code == 403, reponse.text


async def test_ca3_execution_sans_approbation_distincte_409(client: AsyncClient, monkeypatch):
    """CA-3 : un changement de rôle exécuté sans approbateur distinct répond 409, sans rien modifier.

    Parcours réel : intention (201), preview (201), confirmation (200), puis garde d'exécution
    de BE-126 avec le domaine réel `role.adhesion`.
    """
    from app.operator.guard import executer_commande

    monkeypatch.setattr(settings, "ADMIN_PREVIEW_TTL_SECONDS", DUREE_PREVIEW_TEST)
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant CA-3 BE-140")
    await _operateur(gestionnaire["id"])
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    cible = await _membre(organisation_id)
    role = await _role(organisation_id, "ca3")
    intention = await _intention(client, gestionnaire, organisation_id, cible, [str(role)])
    preview_id = await _preview_et_confirmation(client, gestionnaire, organisation_id, intention["commandId"])

    async with AsyncSessionLocal() as db:
        try:
            await executer_commande(
                db,
                command_id=uuid.UUID(intention["commandId"]),
                actor_id=uuid.UUID(gestionnaire["id"]),
                preview_id=uuid.UUID(preview_id),
            )
            raise AssertionError("La garde aurait dû refuser l'exécution sans approbateur.")
        except Exception as erreur:  # noqa: BLE001 : on vérifie le code de l'AppError
            assert getattr(erreur, "code", None) == "approval_required", repr(erreur)
            assert getattr(erreur, "status_code", None) == 409
    assert await _roles_de(organisation_id, cible) == set()


async def test_ca4_changement_approuve_ecrit_audit_avant_et_apres(client: AsyncClient, monkeypatch):
    """CA-4 : le changement approuvé modifie les rôles et écrit un audit avec état avant et après."""
    from app.operator.guard import EXECUTEURS, executer_commande

    monkeypatch.setattr(settings, "ADMIN_PREVIEW_TTL_SECONDS", DUREE_PREVIEW_TEST)
    gestionnaire = await _nouvel_utilisateur(client)
    approbateur = await _nouvel_utilisateur(client, "approbateur BE-140")
    organisation_id = await _organisation(client, gestionnaire, "Tenant CA-4 BE-140")
    await _operateur(gestionnaire["id"])
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    await _operateur(approbateur["id"])
    await _rattacher(organisation_id, approbateur["id"])
    await _accorder(approbateur["id"], ROLE_APPROBATEUR, f"tenant:{organisation_id}")
    ancien = await _role(organisation_id, "ca4-ancien")
    nouveau = await _role(organisation_id, "ca4-nouveau")
    cible = await _membre(organisation_id, [ancien])
    intention = await _intention(client, gestionnaire, organisation_id, cible, [str(nouveau)])
    command_id = intention["commandId"]
    preview_id = await _preview_et_confirmation(client, gestionnaire, organisation_id, command_id)
    approbation = await client.post(
        f"{CHEMIN_COMMANDES}/{command_id}/approve",
        json={"reasonTicket": "INC-140-APPROBATION"},
        headers=_entetes(approbateur, organisation_id),
    )
    assert approbation.status_code == 200, approbation.text

    assert EXECUTEURS.get(TYPE_CLASSE_ROLE) is not None
    async with AsyncSessionLocal() as db:
        commande = await executer_commande(
            db,
            command_id=uuid.UUID(command_id),
            actor_id=uuid.UUID(gestionnaire["id"]),
            preview_id=uuid.UUID(preview_id),
        )
        assert commande.status == "executee"

    assert await _roles_de(organisation_id, cible) == {str(nouveau)}
    membership_id = await _membership_de(organisation_id, cible)
    async with AsyncSessionLocal() as db:
        audit = (await db.scalars(
            select(AuditEvent).where(
                AuditEvent.action == ACTION_AUDIT_CHANGEMENT,
                AuditEvent.entityId == membership_id,
            )
        )).all()
    assert len(audit) == 1
    assert audit[0].changes["avant"] == [str(ancien)]
    assert audit[0].changes["apres"] == [str(nouveau)]


async def test_nominal_intention_puis_rejeu_identique_200(client: AsyncClient):
    """Création de l'intention de changement de rôle (201), puis rejeu de la même clé (200)."""
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant nominal BE-140")
    await _operateur(gestionnaire["id"])
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    cible = await _membre(organisation_id)
    role = await _role(organisation_id, "nominal")
    corps = _corps([str(role)])

    premier = await client.post(_chemin(organisation_id, cible), json=corps, headers=_entetes(gestionnaire, organisation_id))
    rejeu = await client.post(_chemin(organisation_id, cible), json=corps, headers=_entetes(gestionnaire, organisation_id))

    assert premier.status_code == 201, premier.text
    assert premier.json()["commandType"] == TYPE_CLASSE_ROLE
    assert premier.json()["status"] == "intention"
    assert premier.json()["tenantId"] == organisation_id
    assert premier.json()["userId"] == cible
    assert premier.json()["roleIds"] == [str(role)]
    assert rejeu.status_code == 200, rejeu.text
    assert rejeu.json()["commandId"] == premier.json()["commandId"]


async def test_membre_absent_de_l_organisation_404(client: AsyncClient):
    """Un utilisateur qui n'est pas membre de l'organisation ne reçoit aucune intention."""
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant membre absent BE-140")
    await _operateur(gestionnaire["id"])
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    role = await _role(organisation_id, "absent")

    reponse = await client.post(
        _chemin(organisation_id, str(uuid.uuid4())), json=_corps([str(role)]), headers=_entetes(gestionnaire, organisation_id),
    )

    assert reponse.status_code == 404, reponse.text
    assert reponse.json()["error"]["code"] == "user_not_found"


async def test_role_d_une_autre_organisation_404(client: AsyncClient):
    """Un rôle qui n'appartient pas à l'organisation visée est refusé, sans intention."""
    gestionnaire = await _nouvel_utilisateur(client)
    organisation_id = await _organisation(client, gestionnaire, "Tenant rôle BE-140")
    autre = await _organisation(client, gestionnaire, "Autre tenant rôle BE-140")
    await _operateur(gestionnaire["id"])
    await _accorder(gestionnaire["id"], ROLE_GESTION, f"tenant:{organisation_id}")
    cible = await _membre(organisation_id)
    role_etranger = await _role(autre, "etranger")

    reponse = await client.post(
        _chemin(organisation_id, cible), json=_corps([str(role_etranger)]), headers=_entetes(gestionnaire, organisation_id),
    )

    assert reponse.status_code == 404, reponse.text
    assert reponse.json()["error"]["code"] == "role_not_found"
