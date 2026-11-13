"""BE-036 : cycle de vie de l'organisation (états et transitions).

Tests écrits d'après la définition `### BE-036` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.

Décisions appliquées (définition « NON DÉFINI », recommandations écrites) :
- routes (chemins de la définition, QE-SOC-10) :
  POST /api/v1/organizations/current/suspension,
  POST /api/v1/organizations/current/reactivation,
  POST /api/v1/organizations/current/closure ;
- permission : `identity.organization.manage` (permission d'administration du
  socle, accordée au propriétaire ; code non défini dans la définition, QE-SOC-06) ;
- transitions acceptées (QE-SOC-10) : actif -> suspendu, suspendu -> actif,
  actif -> clôturé, suspendu -> clôturé ; toute autre transition est refusée
  en 409 `organization_transition_invalide` (rien n'est écrit) ;
- valeurs stockées : celles déjà présentes dans le code (`active`, `suspended`,
  `closed`) plutôt que `actif`, `suspendu`, `clôturé`, pour ne pas renommer la
  colonne `organization.status` existante (BE-002) ; voir la note de rapport.

Couverture : CA-1 (table des transitions, matrice complète état x action),
CA-2 (403 sans permission, rien n'est écrit), CA-3 (une entrée d'audit par
transition réussie, aucune pour une transition refusée), CA-4 (isolation : la
transition de O1 n'affecte pas O2).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.identity.models import Organization, OrganizationUser
from app.rbac.models import Permission, Role, RolePermission, UserRole

MOT_DE_PASSE = "TestPassword123!"
PERMISSION_ADMINISTRATION = "identity.organization.manage"
PERMISSION_LECTURE_MEMBRES = "organization.members.read"
CODE_TRANSITION_REFUSEE = "organization_transition_invalide"

ACTIONS = {
    "suspension": "identity.organization.suspend",
    "reactivation": "identity.organization.reactivate",
    "closure": "identity.organization.close",
}

# Table des transitions (recommandation QE-SOC-10), exprimée en valeurs stockées.
TRANSITIONS_ACCEPTEES = {
    ("active", "suspension"): "suspended",
    ("suspended", "reactivation"): "active",
    ("active", "closure"): "closed",
    ("suspended", "closure"): "closed",
}


async def _inscrire_et_connecter(client: AsyncClient, nom: str) -> dict:
    email = f"be036-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": nom})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    assert me.status_code == 200, me.text
    return {"authorization": f"Bearer {jetons['accessToken']}", "userId": me.json()["id"]}


async def _creer_organisation(client: AsyncClient, proprietaire: dict, nom: str) -> str:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be036-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": proprietaire["authorization"]},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _ajouter_membre(organisation_id: str, utilisateur_id: str, permissions: list[str]) -> None:
    """Rattache l'utilisateur à l'organisation avec un rôle ne contenant que `permissions`."""
    org = uuid.UUID(organisation_id)
    user = uuid.UUID(utilisateur_id)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=org, userId=user))
        if permissions:
            role = Role(organizationId=org, code=f"be036-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-036")
            db.add(role)
            await db.flush()
            for code in permissions:
                permission = await db.scalar(select(Permission).where(Permission.code == code))
                if permission is None:
                    permission = Permission(code=code, moduleCode="identity", description="Permission de test BE-036")
                    db.add(permission)
                    await db.flush()
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=user, organizationId=org, roleId=role.id))
        await db.commit()


async def _fixer_statut(organisation_id: str, statut: str) -> None:
    """Pose directement le statut en base pour amorcer un scénario (hors transition API)."""
    async with AsyncSessionLocal() as db:
        org = await db.get(Organization, uuid.UUID(organisation_id))
        org.status = statut
        await db.commit()


async def _statut_en_base(organisation_id: str) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.get(Organization, uuid.UUID(organisation_id))).status


async def _audits(organisation_id: str, action: str | None = None) -> int:
    requete = select(func.count(AuditEvent.id)).where(AuditEvent.organizationId == uuid.UUID(organisation_id))
    if action is not None:
        requete = requete.where(AuditEvent.action == action)
    async with AsyncSessionLocal() as db:
        return (await db.scalar(requete)) or 0


def _entetes(utilisateur: dict, organisation_id: str) -> dict:
    return {"Authorization": utilisateur["authorization"], "X-Organization-Id": organisation_id}


def _url(action: str) -> str:
    return f"/api/v1/organizations/current/{action}"


@pytest.mark.parametrize(
    ("depart", "action"),
    [
        ("active", "suspension"),
        ("suspended", "reactivation"),
        ("active", "closure"),
        ("suspended", "closure"),
    ],
)
async def test_be036_ca1_transition_acceptee_change_le_statut(client: AsyncClient, depart: str, action: str):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire BE-036")
    org = await _creer_organisation(client, proprietaire, "Cycle BE-036")
    await _fixer_statut(org, depart)

    res = await client.post(_url(action), headers=_entetes(proprietaire, org))

    assert res.status_code == 200, res.text
    assert res.json()["status"] == TRANSITIONS_ACCEPTEES[(depart, action)]
    assert await _statut_en_base(org) == TRANSITIONS_ACCEPTEES[(depart, action)]


async def test_be036_ca1_transitions_refusees_renvoient_409_sans_changement(client: AsyncClient):
    """Matrice complète : toute combinaison état x action absente de la table est refusée."""
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire BE-036 refus")
    org = await _creer_organisation(client, proprietaire, "Refus BE-036")

    for depart in ("active", "suspended", "closed"):
        for action in ACTIONS:
            if (depart, action) in TRANSITIONS_ACCEPTEES:
                continue
            await _fixer_statut(org, depart)
            res = await client.post(_url(action), headers=_entetes(proprietaire, org))
            assert res.status_code == 409, f"{depart} + {action} : {res.status_code} {res.text}"
            assert res.json()["error"]["code"] == CODE_TRANSITION_REFUSEE, res.text
            assert await _statut_en_base(org) == depart, f"{depart} + {action} a modifié le statut"


async def test_be036_ca1_organisation_cloturee_est_terminale(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire BE-036 terminal")
    org = await _creer_organisation(client, proprietaire, "Terminal BE-036")
    await _fixer_statut(org, "closed")

    for action in ACTIONS:
        res = await client.post(_url(action), headers=_entetes(proprietaire, org))
        assert res.status_code == 409, res.text
    assert await _statut_en_base(org) == "closed"


async def test_be036_ca2_membre_sans_permission_recoit_403_et_rien_ne_change(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire BE-036 refus droit")
    org = await _creer_organisation(client, proprietaire, "Droits BE-036")
    membre = await _inscrire_et_connecter(client, "Membre BE-036")
    await _ajouter_membre(org, membre["userId"], [PERMISSION_LECTURE_MEMBRES])

    for action in ACTIONS:
        res = await client.post(_url(action), headers=_entetes(membre, org))
        assert res.status_code == 403, res.text
    assert await _statut_en_base(org) == "active"
    assert await _audits(org) == 0


async def test_be036_ca3_chaque_transition_reussie_ecrit_une_entree_d_audit(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire BE-036 audit")
    org = await _creer_organisation(client, proprietaire, "Audit BE-036")

    await client.post(_url("suspension"), headers=_entetes(proprietaire, org))
    await client.post(_url("reactivation"), headers=_entetes(proprietaire, org))
    await client.post(_url("closure"), headers=_entetes(proprietaire, org))

    for action in ACTIONS.values():
        assert await _audits(org, action) == 1, action


async def test_be036_ca3_transition_refusee_n_ecrit_aucun_audit(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire BE-036 audit refus")
    org = await _creer_organisation(client, proprietaire, "Audit refus BE-036")
    avant = await _audits(org)

    res = await client.post(_url("reactivation"), headers=_entetes(proprietaire, org))

    assert res.status_code == 409, res.text
    assert await _audits(org) == avant


async def test_be036_ca4_isolation_la_transition_de_o1_n_affecte_pas_o2(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire BE-036 isolation")
    o1 = await _creer_organisation(client, proprietaire, "Organisation 1 BE-036")
    o2 = await _creer_organisation(client, proprietaire, "Organisation 2 BE-036")

    res = await client.post(_url("suspension"), headers=_entetes(proprietaire, o1))

    assert res.status_code == 200, res.text
    assert await _statut_en_base(o1) == "suspended"
    assert await _statut_en_base(o2) == "active"
    assert await _audits(o2) == 0
