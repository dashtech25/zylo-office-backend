"""BE-090 : résiliation d'abonnement (à échéance ou immédiate).

Intention : prouver les critères d'acceptation de BE-090
(implementation-backend/tasks-abonnements-facturation.md, section BE-090) :
- CA-1 : la résiliation par défaut passe `lifecycleStatus` en `cancel_scheduled` et ne
  coupe rien avant l'échéance (`endDate` inchangée, autres axes inchangés, droits inchangés) ;
- CA-2 : une résiliation immédiate est refusée (`INVALID_TRANSITION`) tant que QE-FAC-08
  n'est pas tranché ; la résiliation à échéance reste disponible ;
- CA-3 : sans permission, `FORBIDDEN` et l'abonnement reste inchangé ;
- CA-4 : un abonnement d'un autre tenant est répondu comme un abonnement inexistant.

Le motif (`reason`) est exigé par BE-073 pour une résiliation (geste sensible
`billing.subscription.terminate`) : sans motif, `APPROVAL_REQUIRED` et rien n'est écrit.
Le périmètre payeur (ACTF-04 acheteur, QE-FAC-03) n'est pas testé ici : il dépend d'une
décision non prise ; seule la permission de gestion sur le tenant bénéficiaire l'est.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.billing import service
from app.billing.models import Subscription
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import Organization, OrganizationUser, User
from app.rbac.service import list_effective_permission_codes


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


async def _creer_organisation_isolee() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="be090", slug=f"be090-{uuid.uuid4().hex[:10]}", status="active")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _creer_abonnement(tenant_id: uuid.UUID, lifecycle: str = "active", financial: str = "none", incident: str = "none") -> uuid.UUID:
    """Abonnement du tenant, période de 30 jours, axes posés explicitement."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be090-{uuid.uuid4().hex[:8]}", "Plan BE-090", 1000, "XAF", 30
        )
        abonnement = Subscription(
            organizationId=tenant_id,
            planId=plan.id,
            status="active",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
            beneficiaryTenantId=tenant_id,
            lifecycleStatus=lifecycle,
            financialStatus=financial,
            incidentStatus=incident,
        )
        db.add(abonnement)
        await db.commit()
        return abonnement.id


async def _lire_abonnement(subscription_id: uuid.UUID) -> Subscription:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Subscription).where(Subscription.id == subscription_id))


async def _entrees_audit_resiliation(subscription_id: uuid.UUID) -> list[AuditEvent]:
    async with AsyncSessionLocal() as db:
        resultat = await db.scalars(
            select(AuditEvent).where(
                AuditEvent.entityId == subscription_id,
                AuditEvent.action == "billing.subscription.terminate",
            )
        )
        return list(resultat)


async def _inscrire_et_connecter(client, email: str) -> str:
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Membre"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return login.json()["accessToken"]


async def _ajouter_membre_sans_droit(organization_id: str, email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        utilisateur = await db.scalar(select(User).where(User.email == email))
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=utilisateur.id))
        await db.commit()
        return utilisateur.id


def _entete(token: str, organization_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _url(subscription_id: uuid.UUID) -> str:
    return f"/api/v1/billing/subscriptions/{subscription_id}/cancel"


# CA-1 : résiliation à échéance par défaut, rien n'est coupé avant l'échéance.

async def test_ca1_resiliation_a_echeance_passe_en_cancel_scheduled(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="active", financial="settled", incident="none")
    avant = await _lire_abonnement(abonnement_id)
    droits_avant = await _droits(tenant_id, registered_user)

    reponse = await client.post(
        _url(abonnement_id),
        json={"reason": "Demande du client"},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["lifecycleStatus"] == "cancel_scheduled"
    assert corps["financialStatus"] == "settled"
    assert corps["incidentStatus"] == "none"
    assert corps["cancelMode"] == "end_of_period"
    assert datetime.fromisoformat(corps["cancelEffectiveAt"]) == avant.endDate  # effet à l'échéance, pas immédiat

    apres = await _lire_abonnement(abonnement_id)
    assert apres.lifecycleStatus == "cancel_scheduled"
    assert apres.endDate == avant.endDate  # rien n'est coupé : la période va à son terme
    assert apres.version == avant.version + 1
    assert await _droits(tenant_id, registered_user) == droits_avant

    entrees = await _entrees_audit_resiliation(abonnement_id)
    assert len(entrees) == 1
    assert entrees[0].reason == "Demande du client"


async def _droits(tenant_id: uuid.UUID, registered_user) -> list[str]:
    async with AsyncSessionLocal() as db:
        utilisateur = await db.scalar(select(User).where(User.email == registered_user["email"]))
        return await list_effective_permission_codes(db, tenant_id, utilisateur.id)


# CA-2 : résiliation immédiate refusée tant que QE-FAC-08 n'est pas tranché.

async def test_ca2_resiliation_immediate_refusee_sans_changement(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="active")
    avant = await _lire_abonnement(abonnement_id)

    reponse = await client.post(
        _url(abonnement_id),
        json={"cancelMode": "immediate", "reason": "Test"},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["error"]["code"] == "INVALID_TRANSITION"
    apres = await _lire_abonnement(abonnement_id)
    assert apres.lifecycleStatus == "active"
    assert apres.version == avant.version
    assert await _entrees_audit_resiliation(abonnement_id) == []


async def test_ca2_sans_motif_renvoie_approval_required_sans_changement(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="active")

    reponse = await client.post(
        _url(abonnement_id),
        json={"cancelMode": "end_of_period"},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code in (409, 422), reponse.text
    assert reponse.json()["error"]["code"] == "APPROVAL_REQUIRED"
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "active"


# CA-3 : refus FORBIDDEN sans permission, abonnement inchangé.

async def test_ca3_resiliation_sans_permission_renvoie_forbidden(client, registered_user, organization):
    email_membre = f"be090-membre-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token_membre = await _inscrire_et_connecter(client, email_membre)
    await _ajouter_membre_sans_droit(organization["id"], email_membre)
    abonnement_id = await _creer_abonnement(uuid.UUID(organization["id"]), lifecycle="active")

    reponse = await client.post(
        _url(abonnement_id),
        json={"reason": "Test"},
        headers=_entete(token_membre, organization["id"]),
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "active"
    assert await _entrees_audit_resiliation(abonnement_id) == []


# CA-4 : abonnement d'un autre tenant répondu comme un abonnement inexistant.

async def test_ca4_resiliation_hors_tenant_repond_comme_inexistant(client, registered_user, organization):
    headers_a = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    reponse_b = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"be090-b-{uuid.uuid4().hex[:8]}"},
        headers=headers_a,
    )
    tenant_b = reponse_b.json()["id"]
    abonnement_a = await _creer_abonnement(uuid.UUID(organization["id"]), lifecycle="active")

    reponse_hors_scope = await client.post(
        _url(abonnement_a),
        json={"reason": "Test"},
        headers=_entete(registered_user["accessToken"], tenant_b),
    )
    reponse_inexistante = await client.post(
        _url(uuid.uuid4()),
        json={"reason": "Test"},
        headers=_entete(registered_user["accessToken"], tenant_b),
    )

    assert reponse_hors_scope.status_code == 404, reponse_hors_scope.text
    assert reponse_hors_scope.status_code == reponse_inexistante.status_code
    assert reponse_hors_scope.json()["error"] == reponse_inexistante.json()["error"]
    assert (await _lire_abonnement(abonnement_a)).lifecycleStatus == "active"
