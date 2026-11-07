"""BE-201 : entitlements (octroi, changement, révocation) et décision d'accès.

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-donnees-api-contrats.md,
section BE-201) avant le code. Dépendance : BE-196 (cycle de vie OrganizationModule) n'est pas
fusionné ; ces tests sont donc attendus en échec tant que les routes ci-dessous n'existent pas.

Routes visées (préfixe `/api/v1`, QE-API-01) :
- `POST /api/v1/entitlements` (octroi) ;
- `POST /api/v1/entitlements/{entitlementId}/revoke` (révocation) ;
- `GET /api/v1/access/decisions?capability=...` (décision et provenance).

Décisions de test (écarts consignés dans le rapport BE-201) :
- la table est `subscription_entitlement` telle que BE-024 l'a créée (colonnes `entitlementCode`,
  `status`, `startsAt`, `endsAt`, `sourceAttribution`, `niveauApplication`, `subscriptionId`) ; la
  spec nomme d'autres colonnes (`capability`, `source`, `state`, `beneficiaryId`) : BE-201 n'ajoute
  aucune colonne, les noms BE-024 prévalent ;
- le corps de l'octroi et la forme de la réponse de décision (`decision`, `provenance`) ne sont pas
  définis par la spec : les noms choisis ici sont les seuls supposés ;
- l'unicité réelle est `(subscriptionId, entitlementCode)` (BE-024), pas la clé de la spec ;
- le code d'action du journal d'audit n'est pas défini : le test vérifie seulement qu'une entrée
  d'audit, liée à l'entitlement, est ajoutée par la révocation.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditEvent
from app.billing import service
from app.billing.models import Subscription, SubscriptionEntitlement
from app.billing.permissions import ENTITLEMENT_MANAGE
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser
from app.identity.permissions import ORGANIZATION_READ
from app.rbac.models import Permission, Role, RolePermission, UserRole

MOT_DE_PASSE = "TestPassword123!"
MODULE = "zylo_liquid"
CAPACITE = "zylo_liquid.commande.creer"
URL_ENTITLEMENTS = "/api/v1/entitlements"
URL_DECISIONS = "/api/v1/access/decisions"


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    await engine.dispose()
    yield


async def _inscrire_et_connecter(client: AsyncClient, nom: str) -> dict:
    """Crée un compte et renvoie ses en-têtes d'authentification et son identifiant."""
    email = f"be201-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": nom})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    assert me.status_code == 200, me.text
    return {"authorization": f"Bearer {jetons['accessToken']}", "userId": me.json()["id"]}


async def _creer_organisation(client: AsyncClient, proprietaire: dict, nom: str) -> str:
    """Crée une organisation ; son créateur en devient propriétaire et membre."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be201-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": proprietaire["authorization"]},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _permission(db, code: str) -> Permission:
    permission = await db.scalar(select(Permission).where(Permission.code == code))
    if permission is None:
        permission = Permission(code=code, moduleCode="billing", description="Permission de test BE-201")
        db.add(permission)
        await db.flush()
    return permission


async def _ajouter_membre(organisation_id: str, utilisateur: dict, permissions: list[str]) -> None:
    """Rattache l'utilisateur à l'organisation avec un rôle ne contenant que ces permissions."""
    org = uuid.UUID(organisation_id)
    user = uuid.UUID(utilisateur["userId"])
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=org, userId=user))
        role = Role(organizationId=org, code=f"be201-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-201")
        db.add(role)
        await db.flush()
        for code in permissions:
            permission = await _permission(db, code)
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        db.add(UserRole(userId=user, organizationId=org, roleId=role.id))
        await db.commit()


async def _abonnement(organisation_id: str) -> uuid.UUID:
    """Abonnement actif de l'organisation, rattaché à un plan réel du module zylo_liquid."""
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, MODULE, f"be201-{uuid.uuid4().hex[:10]}", "Plan BE-201", 0, "XAF", 30
        )
        version = await service.ensure_initial_plan_version(db, plan)
        maintenant = datetime.now(timezone.utc)
        abonnement = Subscription(
            organizationId=uuid.UUID(organisation_id), planId=plan.id, planVersionId=version.id,
            status="active", startDate=maintenant, endDate=maintenant + timedelta(days=30),
        )
        db.add(abonnement)
        await db.commit()
        return abonnement.id


def _entetes(acteur: dict, organisation_id: str) -> dict:
    return {"Authorization": acteur["authorization"], "X-Organization-Id": organisation_id}


def _corps_octroi(abonnement_id: uuid.UUID) -> dict:
    return {
        "subscriptionId": str(abonnement_id),
        "moduleCode": MODULE,
        "entitlementCode": CAPACITE,
        "sourceAttribution": "offre",
        "niveauApplication": "organisation",
        "startsAt": datetime.now(timezone.utc).isoformat(),
        "endsAt": None,
    }


async def _octroyer(client: AsyncClient, gestionnaire: dict, organisation_id: str, abonnement_id: uuid.UUID) -> str:
    """Octroie l'entitlement via la route BE-201 ; renvoie son identifiant."""
    res = await client.post(URL_ENTITLEMENTS, json=_corps_octroi(abonnement_id), headers=_entetes(gestionnaire, organisation_id))
    assert res.status_code in (200, 201), res.text
    return res.json()["entitlementId"]


async def _decision(client: AsyncClient, acteur: dict, organisation_id: str) -> dict:
    res = await client.get(URL_DECISIONS, params={"capability": CAPACITE}, headers=_entetes(acteur, organisation_id))
    assert res.status_code == 200, res.text
    return res.json()


async def _nombre_entitlements(abonnement_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.scalar(
                select(func.count(SubscriptionEntitlement.id)).where(
                    SubscriptionEntitlement.subscriptionId == abonnement_id,
                    SubscriptionEntitlement.entitlementCode == CAPACITE,
                )
            )
        ) or 0


async def _nombre_audit_de(entitlement_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.entityId == uuid.UUID(entitlement_id)))
        ) or 0


async def _gestionnaire_et_organisation(client: AsyncClient) -> tuple[dict, str]:
    """Organisation dont un gestionnaire détient `entitlement.manage` (le propriétaire ne l'a pas)."""
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire BE-201")
    organisation = await _creer_organisation(client, proprietaire, "Org BE-201")
    gestionnaire = await _inscrire_et_connecter(client, "Gestionnaire BE-201")
    await _ajouter_membre(organisation, gestionnaire, [ENTITLEMENT_MANAGE])
    return gestionnaire, organisation


# CA-1 : une action dont seul l'entitlement est présent renvoie 403 (non-substitution).


async def test_ca1_entitlement_present_ne_vaut_pas_permission_d_action(client: AsyncClient):
    gestionnaire, organisation = await _gestionnaire_et_organisation(client)
    membre = await _inscrire_et_connecter(client, "Membre sans droit d'action")
    await _ajouter_membre(organisation, membre, [ORGANIZATION_READ])
    abonnement = await _abonnement(organisation)
    await _octroyer(client, gestionnaire, organisation, abonnement)

    decision = await _decision(client, membre, organisation)
    assert decision["decision"] == "granted"

    action = await client.patch(
        f"/api/v1/organizations/{organisation}",
        json={"name": "Nom CA-1", "expectedVersion": 1},
        headers=_entetes(membre, organisation),
    )
    assert action.status_code == 403, action.text


# CA-2 : la décision renvoie la décision et sa provenance.


async def test_ca2_decision_renvoie_decision_et_provenance(client: AsyncClient):
    gestionnaire, organisation = await _gestionnaire_et_organisation(client)
    abonnement = await _abonnement(organisation)
    entitlement_id = await _octroyer(client, gestionnaire, organisation, abonnement)

    corps = await _decision(client, gestionnaire, organisation)
    assert corps["decision"] == "granted"
    assert corps["provenance"]["entitlementId"] == entitlement_id
    assert corps["provenance"]["source"] == "offre"


# CA-3 : après révocation, un cache obsolète n'accorde plus l'accès.


async def test_ca3_revocation_invalide_la_decision_mise_en_cache(client: AsyncClient):
    gestionnaire, organisation = await _gestionnaire_et_organisation(client)
    abonnement = await _abonnement(organisation)
    entitlement_id = await _octroyer(client, gestionnaire, organisation, abonnement)

    # Premiere lecture : la décision accordée peut être mise en cache.
    assert (await _decision(client, gestionnaire, organisation))["decision"] == "granted"

    revocation = await client.post(
        f"/api/v1/entitlements/{entitlement_id}/revoke", headers=_entetes(gestionnaire, organisation)
    )
    assert revocation.status_code == 200, revocation.text

    assert (await _decision(client, gestionnaire, organisation))["decision"] == "denied"


# CA-4 : une décision pour le tenant B ne reflète pas un entitlement du tenant A (isolation).


async def test_ca4_decision_du_tenant_b_ne_reflete_pas_l_entitlement_du_tenant_a(client: AsyncClient):
    gestionnaire_a, organisation_a = await _gestionnaire_et_organisation(client)
    abonnement_a = await _abonnement(organisation_a)
    entitlement_a = await _octroyer(client, gestionnaire_a, organisation_a, abonnement_a)

    proprietaire_b = await _inscrire_et_connecter(client, "Propriétaire tenant B")
    organisation_b = await _creer_organisation(client, proprietaire_b, "Org tenant B")

    corps = await _decision(client, proprietaire_b, organisation_b)
    assert corps["decision"] == "denied"
    assert entitlement_a not in str(corps)


# CA-5 : un double octroi identique ne crée pas de second entitlement (idempotence).


async def test_ca5_double_octroi_identique_ne_cree_pas_de_second_entitlement(client: AsyncClient):
    gestionnaire, organisation = await _gestionnaire_et_organisation(client)
    abonnement = await _abonnement(organisation)

    premier = await _octroyer(client, gestionnaire, organisation, abonnement)
    second = await _octroyer(client, gestionnaire, organisation, abonnement)

    assert second == premier
    assert await _nombre_entitlements(abonnement) == 1


# CA-6 : chaque révocation écrit une entrée d'audit.


async def test_ca6_chaque_revocation_ecrit_une_entree_d_audit(client: AsyncClient):
    gestionnaire, organisation = await _gestionnaire_et_organisation(client)
    abonnement = await _abonnement(organisation)
    entitlement_id = await _octroyer(client, gestionnaire, organisation, abonnement)
    avant = await _nombre_audit_de(entitlement_id)

    revocation = await client.post(
        f"/api/v1/entitlements/{entitlement_id}/revoke", headers=_entetes(gestionnaire, organisation)
    )
    assert revocation.status_code == 200, revocation.text

    assert await _nombre_audit_de(entitlement_id) > avant
