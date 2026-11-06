"""Tests BE-189 : membership et sélection de contexte (CA-1 à CA-6).

Source : implementation-backend/tasks-donnees-api-contrats.md, section BE-189.

Décisions de cette branche (écarts consignés, recommandation la plus simple) :
- tenant = organisation : la table `organization_user` (BE-004) porte le rôle de
  `membership` (couple unique organisation/utilisateur). Elle reçoit une colonne
  `version` et un état `status` parmi invited, active, suspended, revoked.
- la révocation garde la ligne (historique, QE-API-15) et coupe l'accès : une
  appartenance non `active` n'ouvre plus de contexte (`assert_active_membership`).
- les corps JSON nomment le tenant `organizationId` (routes existantes en /organizations).
- une invitation vise un utilisateur existant (par e-mail) et le place en `invited` ;
  l'activation se fait par PATCH (droit `membership.manage`).
- l'idempotence repose sur l'unicité (organisation, utilisateur) : un rejeu ne crée
  jamais un second membership.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.service import get_or_create_permission
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
PERMISSION_GESTION = "membership.manage"
CLE_IDEMPOTENCE = "be189-invitation-0000000001"


def _entetes(utilisateur: dict, organisation_id: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['token']}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _creer_utilisateur(client: AsyncClient, nom: str = "Acteur BE-189") -> dict:
    """Crée un compte et renvoie son identifiant, son e-mail et son jeton d'accès."""
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": nom})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "email": email, "token": token}


async def _creer_organisation(client: AsyncClient, proprietaire: dict) -> str:
    """Crée une organisation dont `proprietaire` est le premier membre ; renvoie son identifiant."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Org BE-189", "slug": f"be189-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _ajouter_membre(organisation_id: str, user_id: str, codes_permissions: list[str] | None = None) -> None:
    """Rend `user_id` membre actif de l'organisation, avec un rôle portant `codes_permissions`."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(user_id)))
        if codes_permissions:
            role = Role(organizationId=uuid.UUID(organisation_id), code=f"be189-{uuid.uuid4().hex[:8]}", name="Rôle BE-189")
            db.add(role)
            await db.flush()
            for code in codes_permissions:
                permission = await get_or_create_permission(db, code, "identity", "Permission de test BE-189")
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=uuid.UUID(user_id), organizationId=uuid.UUID(organisation_id), roleId=role.id))
        await db.commit()


async def _definir_statut(organisation_id: str, user_id: str, statut: str) -> None:
    """Force le statut d'une appartenance (contournement de test, hors API)."""
    async with AsyncSessionLocal() as db:
        appartenance = await db.scalar(
            select(OrganizationUser).where(
                OrganizationUser.organizationId == uuid.UUID(organisation_id),
                OrganizationUser.userId == uuid.UUID(user_id),
            )
        )
        appartenance.status = statut
        await db.commit()


async def _nombre_memberships(organisation_id: str, user_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(OrganizationUser)
            .where(OrganizationUser.organizationId == uuid.UUID(organisation_id), OrganizationUser.userId == uuid.UUID(user_id))
        )


async def _nombre_audits(organisation_id: str, action: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.organizationId == uuid.UUID(organisation_id), AuditEvent.action == action)
        )


async def _gestionnaire(client: AsyncClient, organisation_id: str) -> dict:
    """Membre actif de l'organisation portant la permission `membership.manage`."""
    gestionnaire = await _creer_utilisateur(client, "Gestionnaire BE-189")
    await _ajouter_membre(organisation_id, gestionnaire["id"], [PERMISSION_GESTION])
    return gestionnaire


async def _membership_id(client: AsyncClient, gestionnaire: dict, organisation_id: str, user_id: str) -> str:
    res = await client.get("/api/v1/memberships", headers=_entetes(gestionnaire, organisation_id))
    assert res.status_code == 200, res.text
    return next(m["membershipId"] for m in res.json() if m["userId"] == user_id)


# ---------------------------------------------------------------------------
# CA-1 : une sélection de contexte sans membership actif renvoie 404 (refus opaque)
# ---------------------------------------------------------------------------


async def test_ca1_selection_sans_membership_actif_renvoie_404(client: AsyncClient, organization: dict):
    organisation_id = organization["id"]
    etranger = await _creer_utilisateur(client)
    suspendu = await _creer_utilisateur(client)
    await _ajouter_membre(organisation_id, suspendu["id"])
    await _definir_statut(organisation_id, suspendu["id"], "suspended")

    res_etranger = await client.post(
        "/api/v1/contexts/select", json={"organizationId": organisation_id}, headers=_entetes(etranger)
    )
    res_suspendu = await client.post(
        "/api/v1/contexts/select", json={"organizationId": organisation_id}, headers=_entetes(suspendu)
    )

    assert res_etranger.status_code == 404
    assert res_suspendu.status_code == 404
    assert res_etranger.json()["code"] == res_suspendu.json()["code"] == "organization_not_found"


async def test_ca1_selection_avec_membership_actif_reussit(client: AsyncClient, organization: dict):
    membre = await _creer_utilisateur(client)
    await _ajouter_membre(organization["id"], membre["id"])

    res = await client.post("/api/v1/contexts/select", json={"organizationId": organization["id"]}, headers=_entetes(membre))

    assert res.status_code == 200, res.text
    assert res.json()["organizationId"] == organization["id"]
    assert res.json()["state"] == "active"


async def test_ca1_contexts_ne_liste_que_les_memberships_actifs(client: AsyncClient, organization: dict):
    membre = await _creer_utilisateur(client)
    await _ajouter_membre(organization["id"], membre["id"])
    avant = await client.get("/api/v1/contexts", headers=_entetes(membre))
    await _definir_statut(organization["id"], membre["id"], "suspended")
    apres = await client.get("/api/v1/contexts", headers=_entetes(membre))

    assert avant.status_code == 200
    assert [c["organizationId"] for c in avant.json()] == [organization["id"]]
    assert apres.status_code == 200
    assert apres.json() == []


async def test_ca1_suspension_par_patch_coupe_puis_retablit_lacces(client: AsyncClient, organization: dict):
    gestionnaire = await _gestionnaire(client, organization["id"])
    cible = await _creer_utilisateur(client)
    await _ajouter_membre(organization["id"], cible["id"])
    membership_id = await _membership_id(client, gestionnaire, organization["id"], cible["id"])

    suspendre = await client.patch(
        f"/api/v1/memberships/{membership_id}", json={"state": "suspended"}, headers=_entetes(gestionnaire, organization["id"])
    )
    acces_coupe = await client.get("/api/v1/memberships", headers=_entetes(cible, organization["id"]))
    reactiver = await client.patch(
        f"/api/v1/memberships/{membership_id}", json={"state": "active"}, headers=_entetes(gestionnaire, organization["id"])
    )
    acces_retabli = await client.get("/api/v1/memberships", headers=_entetes(cible, organization["id"]))

    assert suspendre.status_code == 200, suspendre.text
    assert suspendre.json()["state"] == "suspended"
    assert suspendre.json()["version"] == 2
    assert acces_coupe.status_code == 404
    assert reactiver.status_code == 200, reactiver.text
    assert reactiver.json()["version"] == 3
    assert acces_retabli.status_code == 200


# ---------------------------------------------------------------------------
# CA-2 : deux invitations identiques (même Idempotency-Key) n'ajoutent qu'un membership
# ---------------------------------------------------------------------------


async def test_ca2_invitation_rejouee_ne_cree_qu_un_membership(client: AsyncClient, organization: dict):
    organisation_id = organization["id"]
    gestionnaire = await _gestionnaire(client, organisation_id)
    invite = await _creer_utilisateur(client, "Invité BE-189")
    entetes = {**_entetes(gestionnaire, organisation_id), "Idempotency-Key": CLE_IDEMPOTENCE}

    premiere = await client.post("/api/v1/memberships", json={"email": invite["email"]}, headers=entetes)
    rejeu = await client.post("/api/v1/memberships", json={"email": invite["email"]}, headers=entetes)

    assert premiere.status_code in (200, 201), premiere.text
    assert rejeu.status_code in (200, 201), rejeu.text
    assert premiere.json()["membershipId"] == rejeu.json()["membershipId"]
    assert await _nombre_memberships(organisation_id, invite["id"]) == 1


# ---------------------------------------------------------------------------
# CA-3 : invitation sans `membership.manage` renvoie 403
# ---------------------------------------------------------------------------


async def test_ca3_invitation_sans_permission_renvoie_403(client: AsyncClient, organization: dict):
    organisation_id = organization["id"]
    sans_droit = await _creer_utilisateur(client)
    await _ajouter_membre(organisation_id, sans_droit["id"])
    invite = await _creer_utilisateur(client, "Invité BE-189")

    res = await client.post("/api/v1/memberships", json={"email": invite["email"]}, headers=_entetes(sans_droit, organisation_id))

    assert res.status_code == 403
    assert res.json()["code"] == "permission_denied"
    assert await _nombre_memberships(organisation_id, invite["id"]) == 0


# ---------------------------------------------------------------------------
# CA-4 : GET /memberships ne renvoie que les membres du tenant courant
# ---------------------------------------------------------------------------


async def test_ca4_liste_des_memberships_limitee_au_tenant_courant(client: AsyncClient, organization: dict):
    organisation_id = organization["id"]
    gestionnaire = await _gestionnaire(client, organisation_id)
    autre_proprietaire = await _creer_utilisateur(client, "Autre propriétaire BE-189")
    autre_organisation = await _creer_organisation(client, autre_proprietaire)

    res = await client.get("/api/v1/memberships", headers=_entetes(gestionnaire, organisation_id))
    refus = await client.get("/api/v1/memberships", headers=_entetes(gestionnaire, autre_organisation))

    assert res.status_code == 200, res.text
    user_ids = {m["userId"] for m in res.json()}
    assert gestionnaire["id"] in user_ids
    assert autre_proprietaire["id"] not in user_ids
    assert all(m["organizationId"] == organisation_id for m in res.json())
    assert refus.status_code == 404


# ---------------------------------------------------------------------------
# CA-5 : après DELETE (révocation), la sélection du contexte renvoie 404
# ---------------------------------------------------------------------------


async def test_ca5_apres_revocation_selection_renvoie_404(client: AsyncClient, organization: dict):
    organisation_id = organization["id"]
    gestionnaire = await _gestionnaire(client, organisation_id)
    cible = await _creer_utilisateur(client)
    await _ajouter_membre(organisation_id, cible["id"])
    membership_id = await _membership_id(client, gestionnaire, organisation_id, cible["id"])

    revocation = await client.delete(f"/api/v1/memberships/{membership_id}", headers=_entetes(gestionnaire, organisation_id))
    selection = await client.post("/api/v1/contexts/select", json={"organizationId": organisation_id}, headers=_entetes(cible))
    contextes = await client.get("/api/v1/contexts", headers=_entetes(cible))

    assert revocation.status_code in (200, 204), revocation.text
    assert selection.status_code == 404
    assert contextes.json() == []
    assert await _definir_et_lire_statut(organisation_id, cible["id"]) == "revoked"


async def _definir_et_lire_statut(organisation_id: str, user_id: str) -> str:
    async with AsyncSessionLocal() as db:
        appartenance = await db.scalar(
            select(OrganizationUser).where(
                OrganizationUser.organizationId == uuid.UUID(organisation_id),
                OrganizationUser.userId == uuid.UUID(user_id),
            )
        )
        return appartenance.status


# ---------------------------------------------------------------------------
# CA-6 : chaque changement de contexte et de membership écrit une entrée d'audit
# ---------------------------------------------------------------------------


async def test_ca6_chaque_changement_ecrit_une_entree_d_audit(client: AsyncClient, organization: dict):
    organisation_id = organization["id"]
    gestionnaire = await _gestionnaire(client, organisation_id)
    cible = await _creer_utilisateur(client)
    await _ajouter_membre(organisation_id, cible["id"])

    await client.post("/api/v1/contexts/select", json={"organizationId": organisation_id}, headers=_entetes(cible))
    invite = await _creer_utilisateur(client, "Invité BE-189")
    await client.post("/api/v1/memberships", json={"email": invite["email"]}, headers=_entetes(gestionnaire, organisation_id))
    membership_id = await _membership_id(client, gestionnaire, organisation_id, invite["id"])
    await client.patch(
        f"/api/v1/memberships/{membership_id}", json={"state": "active"}, headers=_entetes(gestionnaire, organisation_id)
    )
    await client.delete(f"/api/v1/memberships/{membership_id}", headers=_entetes(gestionnaire, organisation_id))

    assert await _nombre_audits(organisation_id, "contexte.select") == 1
    assert await _nombre_audits(organisation_id, "membership.invite") == 1
    assert await _nombre_audits(organisation_id, "membership.update") == 1
    assert await _nombre_audits(organisation_id, "membership.revoke") == 1
