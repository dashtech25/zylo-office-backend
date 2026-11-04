"""BE-046 : allocation des entitlements aux utilisateurs (sièges).

Intention : prouver par des tests les critères d'acceptation de BE-046
(implementation-backend/tasks-modules-droits.md, section BE-046), écrits d'après la
définition avant le code :
- CA-1 : allouer au-delà de `quotaLimite` renvoie 409 `ENTITLEMENT_SEAT_LIMIT_REACHED`
  et ne crée aucune ligne ;
- CA-2 : un acteur sans `organization.entitlement.allocate` reçoit 403 ; la révocation
  exige la permission distincte `organization.entitlement.revoke` ;
- CA-3 (isolation) : un entitlement de A alloué avec `orgId = B` renvoie 404 ; un
  `userId` non membre de A renvoie 422 ;
- CA-4 : révoquer une allocation la rend inactive sans supprimer la ligne (`revokedAt`
  renseigné), libère le siège et déclenche l'événement de changement ;
- CA-5 : deux allocations simultanées sur le dernier siège : une seule réussit.

Routes : `POST /api/v1/organizations/{orgId}/entitlements/{entitlementId}/allocations`
(corps `userId`, `stateVersion`) et `DELETE .../allocations/{userId}` (révocation).
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.billing import service
from app.billing.models import Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.rbac.service import create_grant

MOT_DE_PASSE = "TestPassword123!"
# Codes de permission de BE-046 (la définition donne `allocate` ; `revoke` est la permission
# distincte retenue par recommandation, QE-MOD-16).
ALLOCATE = "organization.entitlement.allocate"
REVOKE = "organization.entitlement.revoke"


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(User.id).where(User.email == email))


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def _abonnement(organization_id: uuid.UUID) -> uuid.UUID:
    """Abonnement actif rattaché à un plan du catalogue ; retourne son identifiant."""
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be046-{uuid.uuid4().hex[:10]}", "Plan BE-046", 0, "XAF", 30
        )
        version = await service.ensure_initial_plan_version(db, plan)
        maintenant = datetime.now(timezone.utc)
        subscription = Subscription(
            organizationId=organization_id, planId=plan.id, planVersionId=version.id,
            status="active", startDate=maintenant, endDate=maintenant + timedelta(days=30),
        )
        db.add(subscription)
        await db.commit()
        return subscription.id


async def _entitlement(organization_id: uuid.UUID, subscription_id: uuid.UUID, **champs) -> uuid.UUID:
    """Entitlement d'organisation (source `offre`, niveau `organisation`) ; retourne son id."""
    maintenant = datetime.now(timezone.utc)
    valeurs = {
        "organizationId": organization_id, "subscriptionId": subscription_id, "moduleCode": "zylo_liquid",
        "entitlementCode": f"be046.code.{uuid.uuid4().hex[:8]}", "status": "active",
        "startsAt": maintenant, "endsAt": maintenant + timedelta(days=30),
        "sourceAttribution": "offre", "niveauApplication": "organisation",
    }
    valeurs.update(champs)
    async with AsyncSessionLocal() as db:
        ligne = SubscriptionEntitlement(**valeurs)
        db.add(ligne)
        await db.commit()
        return ligne.id


async def _membre(client: AsyncClient, organization_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    """Crée un utilisateur rattaché à l'organisation, sans rôle ; retourne (identifiant, jeton)."""
    cree = await client.post("/api/v1/auth/register", json={
        "email": f"be046-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-046",
    })
    login = await client.post("/api/v1/auth/login", json={"email": cree.json()["email"], "password": MOT_DE_PASSE})
    user_id = uuid.UUID(cree.json()["id"])
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=user_id))
        await db.commit()
    return user_id, login.json()["accessToken"]


async def _utilisateur_hors_organisation(client: AsyncClient) -> uuid.UUID:
    """Utilisateur existant qui n'appartient à aucune organisation de test."""
    cree = await client.post("/api/v1/auth/register", json={
        "email": f"be046-hors-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Hors organisation BE-046",
    })
    return uuid.UUID(cree.json()["id"])


async def _nombre_allocations_actives(entitlement_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(text(
            'SELECT count(*) FROM entitlement_allocations WHERE "entitlementId" = :e AND "revokedAt" IS NULL'
        ).bindparams(e=entitlement_id)) or 0


async def _allouer(client: AsyncClient, token: str, organization_id: str, entitlement_id: uuid.UUID,
                   user_id: uuid.UUID, state_version: int = 1):
    return await client.post(
        f"/api/v1/organizations/{organization_id}/entitlements/{entitlement_id}/allocations",
        json={"userId": str(user_id), "stateVersion": state_version},
        headers=_entete(token, organization_id),
    )


async def _version_etat(entitlement_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(SubscriptionEntitlement.stateVersion).where(
            SubscriptionEntitlement.id == entitlement_id))


async def test_migration_cree_table_allocations_avec_unicite_active(client: AsyncClient):
    """Table `entitlement_allocations` : colonnes requises, unicité (entitlement, user) sur les
    lignes actives seulement (une révocation libère le couple), FK composée vers l'organisation."""
    async with AsyncSessionLocal() as db:
        colonnes = {
            ligne[0] for ligne in (await db.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'entitlement_allocations'"
            ))).all()
        }
        index = {
            ligne[0]: ligne[1] for ligne in (await db.execute(text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'entitlement_allocations'"
            ))).all()
        }
    assert {"id", "entitlementId", "organizationId", "userId", "grantedBy", "grantedAt", "revokedAt"} <= colonnes
    unicite_active = [definition for nom, definition in index.items() if "UNIQUE" in definition]
    assert any('("entitlementId", "userId")' in d and '"revokedAt" IS NULL' in d for d in unicite_active)


async def test_allocation_au_dela_du_quota_renvoie_409_sans_ligne(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : quota 1 déjà consommé ; une allocation de plus renvoie 409 et ne crée aucune ligne."""
    org_id = uuid.UUID(organization["id"])
    entitlement_id = await _entitlement(org_id, await _abonnement(org_id), quotaLimite=1)
    premier, _ = await _membre(client, org_id)
    second, _ = await _membre(client, org_id)
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            'INSERT INTO entitlement_allocations (id, "entitlementId", "organizationId", "userId", "grantedBy", "grantedAt") '
            'VALUES (:id, :e, :o, :u, :g, now())'
        ).bindparams(id=uuid.uuid4(), e=entitlement_id, o=org_id, u=premier, g=premier))
        await db.commit()

    reponse = await _allouer(client, registered_user["accessToken"], organization["id"], entitlement_id, second)

    assert reponse.status_code == 409
    assert reponse.json()["error"]["code"] == "ENTITLEMENT_SEAT_LIMIT_REACHED"
    assert await _nombre_allocations_actives(entitlement_id) == 1


async def test_membre_sans_allocate_recoit_403_et_revocation_exige_revoke(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : sans `organization.entitlement.allocate`, 403 et aucune ligne. Avec `allocate` seul,
    l'attribution passe mais la révocation reste refusée (permission distincte, 403)."""
    org_id = uuid.UUID(organization["id"])
    entitlement_id = await _entitlement(org_id, await _abonnement(org_id), quotaLimite=5)
    cible, _ = await _membre(client, org_id)
    sans_droit, jeton_sans_droit = await _membre(client, org_id)
    avec_allocate, jeton_allocate = await _membre(client, org_id)
    proprietaire = await _id_utilisateur(registered_user["email"])
    async with AsyncSessionLocal() as db:
        await create_grant(db, org_id, proprietaire, avec_allocate, ALLOCATE, "allow")
        await db.commit()

    refus = await _allouer(client, jeton_sans_droit, organization["id"], entitlement_id, cible)
    assert refus.status_code == 403
    assert await _nombre_allocations_actives(entitlement_id) == 0

    accord = await _allouer(client, jeton_allocate, organization["id"], entitlement_id, cible)
    assert accord.status_code in (200, 201)

    revocation = await client.delete(
        f"/api/v1/organizations/{organization['id']}/entitlements/{entitlement_id}/allocations/{cible}",
        headers=_entete(jeton_allocate, organization["id"]),
    )
    assert revocation.status_code == 403
    assert await _nombre_allocations_actives(entitlement_id) == 1


async def test_entitlement_d_un_autre_tenant_ou_membre_etranger_refuses(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 : `orgId = B` avec un acteur de A renvoie 404 ; un entitlement de A passé sous B
    (acteur propriétaire de B) renvoie 404 ; un `userId` non membre de A renvoie 422 sans ligne."""
    org_a = uuid.UUID(organization["id"])
    entitlement_a = await _entitlement(org_a, await _abonnement(org_a), quotaLimite=5)
    autre = await client.post("/api/v1/auth/register", json={
        "email": f"be046-proprio-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Proprietaire B BE-046",
    })
    login_autre = await client.post("/api/v1/auth/login", json={"email": autre.json()["email"], "password": MOT_DE_PASSE})
    res_b = await client.post(
        "/api/v1/organizations", json={"name": "Org B BE-046", "slug": f"be046-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {login_autre.json()['accessToken']}"},
    )
    org_b = res_b.json()["id"]
    cible_a, _ = await _membre(client, org_a)

    depuis_a_vers_b = await _allouer(client, registered_user["accessToken"], org_b, entitlement_a, cible_a)
    assert depuis_a_vers_b.status_code == 404

    depuis_b_sur_entitlement_a = await _allouer(
        client, login_autre.json()["accessToken"], org_b, entitlement_a, cible_a
    )
    assert depuis_b_sur_entitlement_a.status_code == 404
    assert await _nombre_allocations_actives(entitlement_a) == 0

    etranger = await _utilisateur_hors_organisation(client)
    non_membre = await _allouer(client, registered_user["accessToken"], organization["id"], entitlement_a, etranger)
    assert non_membre.status_code == 422
    assert await _nombre_allocations_actives(entitlement_a) == 0


async def test_revocation_garde_la_ligne_libere_le_siege_et_emet_evenement(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : la révocation renseigne `revokedAt` sans supprimer la ligne, rend le siège à nouveau
    disponible, et écrit l'événement de changement d'allocation dans le journal d'audit."""
    org_id = uuid.UUID(organization["id"])
    entitlement_id = await _entitlement(org_id, await _abonnement(org_id), quotaLimite=1)
    cible, _ = await _membre(client, org_id)
    token = registered_user["accessToken"]
    attribution = await _allouer(client, token, organization["id"], entitlement_id, cible)
    assert attribution.status_code in (200, 201)
    allocation_id = attribution.json()["id"]

    revocation = await client.delete(
        f"/api/v1/organizations/{organization['id']}/entitlements/{entitlement_id}/allocations/{cible}",
        headers=_entete(token, organization["id"]),
    )

    assert revocation.status_code == 200
    async with AsyncSessionLocal() as db:
        ligne = (await db.execute(text(
            'SELECT "revokedAt" FROM entitlement_allocations WHERE id = :i'
        ).bindparams(i=uuid.UUID(allocation_id)))).one()
        evenements = await db.scalar(text(
            "SELECT count(*) FROM audit_event WHERE action = 'EntitlementAllocationChanged' AND \"entityId\" = :i"
        ).bindparams(i=uuid.UUID(allocation_id))) or 0
    assert ligne[0] is not None
    assert evenements >= 2
    assert await _nombre_allocations_actives(entitlement_id) == 0
    autre_cible, _ = await _membre(client, org_id)
    nouvelle = await _allouer(client, token, organization["id"], entitlement_id, autre_cible,
                              state_version=await _version_etat(entitlement_id))
    assert nouvelle.status_code in (200, 201)


async def test_deux_allocations_simultanees_sur_le_dernier_siege(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-5 : deux requêtes concurrentes sur le dernier siège, avec la même version lue avant
    la course : une seule réussit, l'autre renvoie 409, et une seule ligne active existe."""
    org_id = uuid.UUID(organization["id"])
    entitlement_id = await _entitlement(org_id, await _abonnement(org_id), quotaLimite=1)
    premier, _ = await _membre(client, org_id)
    second, _ = await _membre(client, org_id)
    version_lue = await _version_etat(entitlement_id)
    token = registered_user["accessToken"]

    reponses = await asyncio.gather(
        _allouer(client, token, organization["id"], entitlement_id, premier, state_version=version_lue),
        _allouer(client, token, organization["id"], entitlement_id, second, state_version=version_lue),
    )

    codes = sorted(r.status_code for r in reponses)
    assert codes[0] in (200, 201) and codes[1] == 409
    assert await _nombre_allocations_actives(entitlement_id) == 1
    assert await _version_etat(entitlement_id) == version_lue + 1
