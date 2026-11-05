"""BE-236 : opérations asynchrones consultables.

Tests écrits d'après la définition `### BE-236` de
implementation-backend/tasks-exploitation-architecture.md, avant le code.

Route testée (reco, chemin exact non défini) :
- GET /api/v1/operations/{operation_id}, avec l'en-tête X-Organization-Id.

Permission de lecture par un non-initiateur (nom non défini, recommandation) :
`operations.operation.read`.

Couverture :
- CA-1 : une opération naît en statut « recue », avec identifiant, avant tout résultat
  (test de contrat sur la création et sur la lecture HTTP) ;
- CA-2 : le statut `inconnu` n'est jamais présenté comme échec ni succès (test de transition
  et de sérialisation) ;
- CA-3 : une opération d'un tenant A n'est pas lisible depuis le tenant B (404) ;
- CA-4 : lecture sans droit par un membre non initiateur donne 403.

Les appartenances et rôles de test sont posés directement en base, comme dans
test_be014_membres.py : la tâche ne dépend pas d'une invitation.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import OrganizationUser
from app.operations.models import Operation
from app.operations.permissions import OPERATION_READ
from app.operations.service import (
    creer_operation,
    enregistrer_verification,
    transitionner,
)
from app.rbac.models import Permission, Role, RolePermission, UserRole

MOT_DE_PASSE = "TestPassword123!"
MAINTENANT = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)


async def _inscrire_et_connecter(client: AsyncClient, nom: str) -> dict:
    """Crée un compte et renvoie son en-tête d'authentification et son identifiant."""
    email = f"be236-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": nom})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    assert me.status_code == 200, me.text
    return {"authorization": f"Bearer {jetons['accessToken']}", "userId": me.json()["id"]}


async def _creer_organisation(client: AsyncClient, proprietaire: dict) -> str:
    """Crée une organisation ; son créateur en devient propriétaire et membre."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Org BE236", "slug": f"be236-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": proprietaire["authorization"]},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _ajouter_membre(organisation_id: str, utilisateur_id: str, avec_lecture: bool) -> None:
    """Rattache l'utilisateur à l'organisation ; `avec_lecture` lui accorde OPERATION_READ par un rôle de test."""
    org = uuid.UUID(organisation_id)
    user = uuid.UUID(utilisateur_id)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=org, userId=user))
        if avec_lecture:
            role = Role(organizationId=org, code=f"be236-{uuid.uuid4().hex[:8]}", name="Lecture opérations (test BE-236)")
            db.add(role)
            await db.flush()
            permission = await db.scalar(select(Permission).where(Permission.code == OPERATION_READ))
            if permission is None:
                permission = Permission(code=OPERATION_READ, moduleCode="operations", description="Lecture d'opération (test BE-236)")
                db.add(permission)
                await db.flush()
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=user, organizationId=org, roleId=role.id))
        await db.commit()


async def _nouvelle_operation(tenant: str, acteur: str, type_operation: str = "test.be236") -> uuid.UUID:
    """Crée une opération en base, comme le ferait une commande asynchrone, et renvoie son identifiant."""
    async with AsyncSessionLocal() as db:
        operation = await creer_operation(
            db,
            tenant_id=uuid.UUID(tenant),
            type_operation=type_operation,
            acteur_id=uuid.UUID(acteur),
            maintenant=MAINTENANT,
        )
        await db.commit()
        return operation.id


async def _etat(operation_id: uuid.UUID) -> Operation:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Operation).where(Operation.id == operation_id))


def _entetes(utilisateur: dict, organisation_id: str) -> dict:
    return {"Authorization": utilisateur["authorization"], "X-Organization-Id": organisation_id}


@pytest.mark.asyncio
async def test_be236_ca1_operation_recue_avant_tout_resultat(client: AsyncClient):
    """CA-1 : l'identifiant et le statut « recue » existent avant tout résultat (contrat)."""
    initiateur = await _inscrire_et_connecter(client, "Initiateur")
    organisation = await _creer_organisation(client, initiateur)

    operation_id = await _nouvelle_operation(organisation, initiateur["userId"])
    ligne = await _etat(operation_id)
    assert ligne.statut == "recue"
    assert ligne.resultat is None
    assert ligne.motifEchec is None
    assert len(ligne.transitions) == 1
    assert ligne.transitions[0]["statut"] == "recue"

    res = await client.get(f"/api/v1/operations/{operation_id}", headers=_entetes(initiateur, organisation))
    assert res.status_code == 200, res.text
    corps = res.json()
    assert corps["operationId"] == str(operation_id)
    assert corps["statut"] == "recue"
    assert corps["resultat"] is None


@pytest.mark.asyncio
async def test_be236_ca2_inconnu_jamais_echec_ni_succes(client: AsyncClient):
    """CA-2 : `inconnu` ne passe à succès ou échec qu'après une vérification, et se lit comme inconnu."""
    initiateur = await _inscrire_et_connecter(client, "Initiateur")
    organisation = await _creer_organisation(client, initiateur)
    operation_id = await _nouvelle_operation(organisation, initiateur["userId"])

    async with AsyncSessionLocal() as db:
        operation = await db.scalar(select(Operation).where(Operation.id == operation_id))
        await transitionner(db, operation, "en_cours", maintenant=MAINTENANT)
        await transitionner(db, operation, "inconnu", maintenant=MAINTENANT)
        await db.commit()

    # Lecture : aucun échec ni succès présenté tant que l'issue n'est pas connue.
    res = await client.get(f"/api/v1/operations/{operation_id}", headers=_entetes(initiateur, organisation))
    assert res.status_code == 200, res.text
    corps = res.json()
    assert corps["statut"] == "inconnu"
    assert corps["resultat"] is None
    assert corps["motifEchec"] is None

    # Transition interdite sans vérification préalable.
    async with AsyncSessionLocal() as db:
        operation = await db.scalar(select(Operation).where(Operation.id == operation_id))
        with pytest.raises(AppError) as erreur:
            await transitionner(db, operation, "succes", maintenant=MAINTENANT, resultat={"ok": True})
        assert erreur.value.status_code == 409
        assert erreur.value.code == "transition_operation_interdite"

    # Après vérification, la transition vers succès est permise ; succes est terminal.
    async with AsyncSessionLocal() as db:
        operation = await db.scalar(select(Operation).where(Operation.id == operation_id))
        await enregistrer_verification(db, operation, maintenant=MAINTENANT)
        await transitionner(db, operation, "succes", maintenant=MAINTENANT, resultat={"ok": True})
        await db.commit()
    with pytest.raises(AppError):
        async with AsyncSessionLocal() as db:
            operation = await db.scalar(select(Operation).where(Operation.id == operation_id))
            await transitionner(db, operation, "echec", maintenant=MAINTENANT, motif_echec="tardif")

    res = await client.get(f"/api/v1/operations/{operation_id}", headers=_entetes(initiateur, organisation))
    assert res.json()["statut"] == "succes"
    assert res.json()["resultat"] == {"ok": True}


@pytest.mark.asyncio
async def test_be236_ca3_operation_d_un_tenant_illisible_par_un_autre(client: AsyncClient):
    """CA-3 : l'opération du tenant A renvoie 404 depuis le tenant B, même pour son initiateur."""
    initiateur = await _inscrire_et_connecter(client, "Initiateur")
    tenant_a = await _creer_organisation(client, initiateur)
    tenant_b = await _creer_organisation(client, initiateur)
    operation_id = await _nouvelle_operation(tenant_a, initiateur["userId"])

    res_a = await client.get(f"/api/v1/operations/{operation_id}", headers=_entetes(initiateur, tenant_a))
    assert res_a.status_code == 200, res_a.text

    res_b = await client.get(f"/api/v1/operations/{operation_id}", headers=_entetes(initiateur, tenant_b))
    assert res_b.status_code == 404, res_b.text

    inconnue = await client.get(f"/api/v1/operations/{uuid.uuid4()}", headers=_entetes(initiateur, tenant_a))
    assert inconnue.status_code == 404, inconnue.text


@pytest.mark.asyncio
async def test_be236_ca4_lecture_sans_droit_donne_403(client: AsyncClient):
    """CA-4 : un membre non initiateur sans OPERATION_READ reçoit 403 ; avec le droit, il lit."""
    initiateur = await _inscrire_et_connecter(client, "Initiateur")
    organisation = await _creer_organisation(client, initiateur)
    operation_id = await _nouvelle_operation(organisation, initiateur["userId"])

    sans_droit = await _inscrire_et_connecter(client, "Membre sans droit")
    await _ajouter_membre(organisation, sans_droit["userId"], avec_lecture=False)
    refus = await client.get(f"/api/v1/operations/{operation_id}", headers=_entetes(sans_droit, organisation))
    assert refus.status_code == 403, refus.text
    assert refus.json()["error"]["code"] == "permission_denied"

    avec_droit = await _inscrire_et_connecter(client, "Membre avec droit")
    await _ajouter_membre(organisation, avec_droit["userId"], avec_lecture=True)
    accord = await client.get(f"/api/v1/operations/{operation_id}", headers=_entetes(avec_droit, organisation))
    assert accord.status_code == 200, accord.text
