"""BE-146 : révocation et fin de fenêtre des droits temporaires (administration).

Tests écrits d'après la définition `### BE-146` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Couverture :
- CA-1 : après `expiresAt` l'accès est refusé (403) sans action humaine. Le
  temps est simulé en remplaçant l'horloge du module `app.rbac.role_assignments`
  (pas de `sleep`, pas de test dépendant de l'heure réelle) ;
- CA-2 (refus de droit) : révocation par un agent L1 : 403 ; révocation hors
  portée plateforme : 403 ;
- CA-3 : une affectation sur identité partagée est refusée (422). NON
  IMPLÉMENTABLE EN L'ÉTAT : le modèle `User` ne porte aucun attribut de compte
  partagé. Le test est présent, désactivé avec renvoi à QE-ADM-15 ;
- CA-4 : la révocation crée un événement d'audit et ne supprime pas
  l'affectation (présence et intégrité des colonnes d'origine).

Tests complémentaires (définition BE-146 et BE-121) : la révocation retire
l'autorité plateforme immédiatement, une seconde révocation renvoie 409, une
affectation inconnue renvoie 404.

Les affectations d'amorçage sont posées directement en base par `_accorder`,
comme dans les tests de BE-121 (il n'existe pas encore de bootstrap).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.rbac import role_assignments as domaine_affectations
from app.rbac.role_assignments import AdminRoleAssignment

CHEMIN_AFFECTATIONS = "/api/v1/admin/role-assignments"
MOT_DE_PASSE = "TestPassword123!"
ACTION_REVOCATION = "admin.role_assignment.revoke"


def _chemin_revocation(affectation_id: str) -> str:
    return f"{CHEMIN_AFFECTATIONS}/{affectation_id}/revoke"


def _entetes(utilisateur: dict, portee: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['accessToken']}"}
    if portee is not None:
        entetes["X-Admin-Scope"] = portee
    return entetes


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    """Compte sans adhésion à l'organisation de test."""
    email = f"be146-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-146"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    return {"id": me.json()["id"], "accessToken": jetons["accessToken"]}


async def _accorder(actor_id: str, role_code: str, scope: str, expires_at: datetime | None = None) -> str:
    """Pose une affectation directement en base (autorité d'amorçage). Renvoie son id."""
    async with AsyncSessionLocal() as db:
        ligne = AdminRoleAssignment(
            actorId=uuid.UUID(actor_id),
            roleCode=role_code,
            scope=scope,
            grantedBy=uuid.UUID(actor_id),
            grantedAt=datetime.now(timezone.utc),
            expiresAt=expires_at,
            revokedAt=None,
        )
        db.add(ligne)
        await db.commit()
        return str(ligne.id)


async def _ligne(affectation_id: str) -> AdminRoleAssignment | None:
    async with AsyncSessionLocal() as db:
        return await db.get(AdminRoleAssignment, uuid.UUID(affectation_id))


class _HorlogeSimulee(datetime):
    """Remplace `datetime` dans `app.rbac.role_assignments` : `now()` renvoie `instant`."""

    instant: datetime = datetime.now(timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.instant


@pytest.fixture
def horloge(monkeypatch):
    """Horloge du module de domaine, réglable par le test (`horloge.instant = ...`)."""
    _HorlogeSimulee.instant = datetime.now(timezone.utc)
    monkeypatch.setattr(domaine_affectations, "datetime", _HorlogeSimulee)
    return _HorlogeSimulee


# ---------------------------------------------------------------------------
# CA-1 : fin de fenêtre sans action humaine
# ---------------------------------------------------------------------------


async def test_be146_ca1_acces_refuse_apres_expiresAt_sans_action_humaine(client: AsyncClient, registered_user: dict, monkeypatch, horloge):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    maintenant = datetime.now(timezone.utc)
    echeance = maintenant + timedelta(hours=2)
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform", expires_at=echeance)
    cible = await _nouvel_utilisateur(client)
    corps = {"actorId": cible["id"], "roleCode": "auditeur", "scope": "platform", "expiresAt": None}

    # Avant l'échéance : l'autorité est active.
    horloge.instant = maintenant + timedelta(hours=1)
    reponse = await client.post(CHEMIN_AFFECTATIONS, json=corps, headers=_entetes(operateur, "platform"))
    assert reponse.status_code == 201, reponse.text

    # Après l'échéance, sans aucune action : refus.
    horloge.instant = echeance + timedelta(seconds=1)
    reponse = await client.post(CHEMIN_AFFECTATIONS, json=corps, headers=_entetes(operateur, "platform"))
    assert reponse.status_code == 403


# ---------------------------------------------------------------------------
# CA-2 : refus de droit pour la révocation
# ---------------------------------------------------------------------------


async def test_be146_ca2_agent_l1_recoit_403_pour_revoquer(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    agent = await _nouvel_utilisateur(client)
    await _accorder(agent["id"], "agent_support_l1", "platform")
    cible = await _nouvel_utilisateur(client)
    affectation_id = await _accorder(cible["id"], "auditeur", "platform")

    reponse = await client.post(_chemin_revocation(affectation_id), headers=_entetes(agent, "platform"))

    assert reponse.status_code == 403
    assert (await _ligne(affectation_id)).revokedAt is None


async def test_be146_ca2_revocation_hors_portee_plateforme_recoit_403(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    cible = await _nouvel_utilisateur(client)
    affectation_id = await _accorder(cible["id"], "auditeur", "platform")

    reponse = await client.post(
        _chemin_revocation(affectation_id),
        headers=_entetes(operateur, f"tenant:{organization['id']}"),
    )

    assert reponse.status_code == 403
    assert (await _ligne(affectation_id)).revokedAt is None


# ---------------------------------------------------------------------------
# CA-3 : identité partagée refusée (422), QE-ADM-15
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="QE-ADM-15 : le modèle User ne porte aucun attribut de compte partagé ; "
    "la détection et le refus 422 ne peuvent pas être écrits avant l'arbitrage de la QE."
)
async def test_be146_ca3_affectation_sur_identite_partagee_refusee_422(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    compte_partage = await _nouvel_utilisateur(client)

    reponse = await client.post(
        CHEMIN_AFFECTATIONS,
        json={"actorId": compte_partage["id"], "roleCode": "auditeur", "scope": "platform", "expiresAt": None},
        headers=_entetes(operateur, "platform"),
    )

    assert reponse.status_code == 422


# ---------------------------------------------------------------------------
# CA-4 : révocation auditée, affectation conservée
# ---------------------------------------------------------------------------


async def test_be146_ca4_revocation_cree_un_evenement_d_audit_et_conserve_la_ligne(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    cible = await _nouvel_utilisateur(client)
    echeance = datetime.now(timezone.utc) + timedelta(days=3)
    affectation_id = await _accorder(cible["id"], "auditeur", "platform", expires_at=echeance)
    avant = await _ligne(affectation_id)

    reponse = await client.post(_chemin_revocation(affectation_id), headers=_entetes(operateur, "platform"))

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["revokedAt"] is not None
    assert reponse.json()["revokedBy"] == operateur["id"]

    # Intégrité : la ligne existe toujours, seules les colonnes de révocation changent.
    apres = await _ligne(affectation_id)
    assert apres is not None
    assert apres.revokedAt is not None
    assert apres.revokedBy == uuid.UUID(operateur["id"])
    assert apres.actorId == avant.actorId
    assert apres.roleCode == avant.roleCode
    assert apres.scope == avant.scope
    assert apres.grantedAt == avant.grantedAt
    assert apres.expiresAt == avant.expiresAt

    async with AsyncSessionLocal() as db:
        evenements = (await db.execute(
            select(AuditEvent).where(AuditEvent.entityId == uuid.UUID(affectation_id), AuditEvent.action == ACTION_REVOCATION)
        )).scalars().all()
    assert len(evenements) == 1
    assert str(evenements[0].actorUserId) == operateur["id"]
    assert evenements[0].entityType == "AdminRoleAssignment"
    assert evenements[0].result == "success"
    assert evenements[0].request_id


# ---------------------------------------------------------------------------
# Compléments : retrait immédiat de l'autorité, 409 et 404
# ---------------------------------------------------------------------------


async def test_be146_revocation_retire_l_autorite_plateforme_immediatement(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    affectation_id = await _accorder(operateur["id"], "operateur_plateforme", "platform")
    cible = await _nouvel_utilisateur(client)
    corps = {"actorId": cible["id"], "roleCode": "auditeur", "scope": "platform", "expiresAt": None}

    reponse = await client.post(_chemin_revocation(affectation_id), headers=_entetes(registered_user, "platform"))
    assert reponse.status_code == 403  # l'appelant n'a pas d'autorité : aucune révocation faite

    # L'opérateur lui-même ne peut pas révoquer sa propre autorité sans être plateforme :
    # on vérifie donc la révocation par un autre opérateur plateforme.
    administrateur = await _nouvel_utilisateur(client)
    await _accorder(administrateur["id"], "operateur_plateforme", "platform")
    reponse = await client.post(_chemin_revocation(affectation_id), headers=_entetes(administrateur, "platform"))
    assert reponse.status_code == 200, reponse.text

    reponse = await client.post(CHEMIN_AFFECTATIONS, json=corps, headers=_entetes(operateur, "platform"))
    assert reponse.status_code == 403


async def test_be146_second_revocation_renvoie_409(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")
    cible = await _nouvel_utilisateur(client)
    affectation_id = await _accorder(cible["id"], "auditeur", "platform")

    premiere = await client.post(_chemin_revocation(affectation_id), headers=_entetes(operateur, "platform"))
    seconde = await client.post(_chemin_revocation(affectation_id), headers=_entetes(operateur, "platform"))

    assert premiere.status_code == 200, premiere.text
    assert seconde.status_code == 409


async def test_be146_affectation_inconnue_renvoie_404(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    operateur = await _nouvel_utilisateur(client)
    await _accorder(operateur["id"], "operateur_plateforme", "platform")

    reponse = await client.post(_chemin_revocation(str(uuid.uuid4())), headers=_entetes(operateur, "platform"))

    assert reponse.status_code == 404
