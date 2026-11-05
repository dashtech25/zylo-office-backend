"""BE-092 : réactivation après incident ou résiliation.

Intention : prouver les critères d'acceptation de BE-092
(implementation-backend/tasks-abonnements-facturation.md, section BE-092) :
- CA-1 : sans paiement confirmé (tentative `succeeded` rattachée à l'abonnement), la réactivation
  est refusée (`PAYMENT_DECLINED`, ou `RECONCILIATION_REQUIRED` si l'issue est `unknown`) et
  l'état reste inchangé ;
- CA-2 : la réactivation d'un abonnement `subscription_closed` renvoie `INVALID_TRANSITION` ;
- CA-3 : sans permission `billing.subscription.manage`, `FORBIDDEN` et rien n'est écrit ;
- CA-4 : un abonnement d'un autre tenant est répondu comme un abonnement inexistant.

Succès : l'axe cycle de vie revient à `active` (depuis `cancel_scheduled`, `cancelled` ou `expired`),
l'axe incident revient à `none` (depuis `past_due`, `grace` ou `suspended`), et un seul
`SubscriptionActivated` est écrit dans l'outbox (BE-074).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.billing import service
from app.billing.models import Invoice, PaymentAttempt, Subscription
from app.core.database import AsyncSessionLocal, engine
from app.evenements.models import OutboxEvenement
from app.identity.models import OrganizationUser, User

TYPE_EVENEMENT = "SubscriptionActivated"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


async def _creer_abonnement(tenant_id: uuid.UUID, lifecycle: str, incident: str = "none") -> uuid.UUID:
    """Abonnement du tenant, période de 30 jours, axes posés explicitement."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be092-{uuid.uuid4().hex[:8]}", "Plan BE-092", 1000, "XAF", 30
        )
        abonnement = Subscription(
            organizationId=tenant_id,
            planId=plan.id,
            status="active",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
            beneficiaryTenantId=tenant_id,
            lifecycleStatus=lifecycle,
            financialStatus="settled",
            incidentStatus=incident,
            cancelMode="end_of_period" if lifecycle == "cancel_scheduled" else None,
            cancelEffectiveAt=maintenant + timedelta(days=30) if lifecycle == "cancel_scheduled" else None,
        )
        db.add(abonnement)
        await db.commit()
        return abonnement.id


async def _creer_tentative(subscription_id: uuid.UUID, statut: str) -> uuid.UUID:
    """Facture de l'abonnement et tentative de paiement de ce statut."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        facture = Invoice(
            subscriptionId=subscription_id, amountCents=1500, amountMinor=1500, currency="XAF",
            status="pending", issuedAt=maintenant, idempotencyKey=f"be092-{uuid.uuid4().hex}",
        )
        db.add(facture)
        await db.flush()
        tentative = PaymentAttempt(
            invoiceId=facture.id, provider="fictif", mode="test",
            idempotencyKey=f"be092-{uuid.uuid4().hex}", amountMinor=1500, currency="XAF",
            status=statut, requestedAt=maintenant, version=1,
        )
        db.add(tentative)
        await db.commit()
        return tentative.id


async def _lire_abonnement(subscription_id: uuid.UUID) -> Subscription:
    """Relit l'abonnement directement en base (pas de cache de session)."""
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Subscription).where(Subscription.id == subscription_id))


async def _evenements_activation(subscription_id: uuid.UUID) -> int:
    """Nombre d'évènements `SubscriptionActivated` de l'outbox visant cet abonnement."""
    async with AsyncSessionLocal() as db:
        lignes = (await db.execute(
            select(OutboxEvenement).where(OutboxEvenement.eventType == TYPE_EVENEMENT)
        )).scalars().all()
    return sum(
        1 for ligne in lignes if (ligne.payload.get("payload") or {}).get("subscriptionId") == str(subscription_id)
    )


async def _inscrire_et_connecter(client, email: str) -> str:
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Membre"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return login.json()["accessToken"]


async def _ajouter_membre_sans_droit(organization_id: str, email: str) -> None:
    async with AsyncSessionLocal() as db:
        utilisateur = await db.scalar(select(User).where(User.email == email))
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=utilisateur.id))
        await db.commit()


def _entete(token: str, organization_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _url(subscription_id: uuid.UUID) -> str:
    return f"/api/v1/billing/subscriptions/{subscription_id}/reactivate"


# CA-1 : sans paiement confirmé, refus et état inchangé.

@pytest.mark.parametrize(
    ("statut_tentative", "code_attendu"),
    [("failed", "PAYMENT_DECLINED"), ("pending", "PAYMENT_DECLINED"), ("unknown", "RECONCILIATION_REQUIRED")],
)
async def test_ca1_paiement_non_confirme_refuse_sans_changement(
    client, registered_user, organization, statut_tentative, code_attendu
):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="cancel_scheduled")
    tentative_id = await _creer_tentative(abonnement_id, statut_tentative)
    avant = await _lire_abonnement(abonnement_id)

    reponse = await client.post(
        _url(abonnement_id),
        json={"paymentAttemptId": str(tentative_id)},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code in (402, 409), reponse.text
    assert reponse.json()["error"]["code"] == code_attendu
    apres = await _lire_abonnement(abonnement_id)
    assert apres.lifecycleStatus == "cancel_scheduled"
    assert apres.version == avant.version
    assert await _evenements_activation(abonnement_id) == 0


async def test_ca1_sans_identifiant_de_paiement_refusee(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="cancel_scheduled")
    avant = await _lire_abonnement(abonnement_id)

    reponse = await client.post(
        _url(abonnement_id),
        json={},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 422, reponse.text
    apres = await _lire_abonnement(abonnement_id)
    assert apres.lifecycleStatus == "cancel_scheduled"
    assert apres.version == avant.version


async def test_ca1_tentative_d_un_autre_abonnement_introuvable(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="cancel_scheduled")
    autre_abonnement = await _creer_abonnement(tenant_id, lifecycle="active")
    tentative_autre = await _creer_tentative(autre_abonnement, "succeeded")

    reponse = await client.post(
        _url(abonnement_id),
        json={"paymentAttemptId": str(tentative_autre)},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 404, reponse.text
    assert reponse.json()["error"]["code"] == "payment_attempt_not_found"
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "cancel_scheduled"


# Succès : réactivation après résiliation puis après incident, un seul événement.

async def test_reactivation_apres_resiliation_repasse_active_et_emet_l_evenement(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="cancel_scheduled")
    tentative_id = await _creer_tentative(abonnement_id, "succeeded")
    avant = await _lire_abonnement(abonnement_id)

    reponse = await client.post(
        _url(abonnement_id),
        json={"paymentAttemptId": str(tentative_id)},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["lifecycleStatus"] == "active"
    assert corps["cancelMode"] is None
    assert corps["cancelEffectiveAt"] is None
    apres = await _lire_abonnement(abonnement_id)
    assert apres.lifecycleStatus == "active"
    assert apres.cancelEffectiveAt is None
    assert apres.version == avant.version + 1
    assert await _evenements_activation(abonnement_id) == 1


async def test_reactivation_apres_suspension_remet_l_incident_a_none(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="active", incident="suspended")
    tentative_id = await _creer_tentative(abonnement_id, "succeeded")

    reponse = await client.post(
        _url(abonnement_id),
        json={"paymentAttemptId": str(tentative_id)},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 200, reponse.text
    apres = await _lire_abonnement(abonnement_id)
    assert apres.lifecycleStatus == "active"
    assert apres.incidentStatus == "none"
    assert apres.financialStatus == "settled"


async def test_reactivation_deja_active_renvoie_invalid_transition_sans_second_evenement(
    client, registered_user, organization
):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="cancel_scheduled")
    tentative_id = await _creer_tentative(abonnement_id, "succeeded")
    entete = _entete(registered_user["accessToken"], organization["id"])
    await client.post(_url(abonnement_id), json={"paymentAttemptId": str(tentative_id)}, headers=entete)

    reponse = await client.post(_url(abonnement_id), json={"paymentAttemptId": str(tentative_id)}, headers=entete)

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["error"]["code"] == "INVALID_TRANSITION"
    assert await _evenements_activation(abonnement_id) == 1


# CA-2 : abonnement clôturé, réactivation refusée.

async def test_ca2_abonnement_clos_renvoie_invalid_transition(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="subscription_closed")
    tentative_id = await _creer_tentative(abonnement_id, "succeeded")
    avant = await _lire_abonnement(abonnement_id)

    reponse = await client.post(
        _url(abonnement_id),
        json={"paymentAttemptId": str(tentative_id)},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["error"]["code"] == "INVALID_TRANSITION"
    apres = await _lire_abonnement(abonnement_id)
    assert apres.lifecycleStatus == "subscription_closed"
    assert apres.version == avant.version
    assert await _evenements_activation(abonnement_id) == 0


# CA-3 : refus FORBIDDEN sans permission, abonnement inchangé.

async def test_ca3_reactivation_sans_permission_renvoie_forbidden(client, registered_user, organization):
    email_membre = f"be092-membre-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token_membre = await _inscrire_et_connecter(client, email_membre)
    await _ajouter_membre_sans_droit(organization["id"], email_membre)
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="cancel_scheduled")
    tentative_id = await _creer_tentative(abonnement_id, "succeeded")

    reponse = await client.post(
        _url(abonnement_id),
        json={"paymentAttemptId": str(tentative_id)},
        headers=_entete(token_membre, organization["id"]),
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "cancel_scheduled"
    assert await _evenements_activation(abonnement_id) == 0


# CA-4 : abonnement d'un autre tenant répondu comme un abonnement inexistant.

async def test_ca4_reactivation_hors_tenant_repond_comme_inexistant(client, registered_user, organization):
    headers_a = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    reponse_b = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"be092-b-{uuid.uuid4().hex[:8]}"},
        headers=headers_a,
    )
    tenant_b = reponse_b.json()["id"]
    abonnement_a = await _creer_abonnement(uuid.UUID(organization["id"]), lifecycle="cancel_scheduled")
    tentative_a = await _creer_tentative(abonnement_a, "succeeded")

    reponse_hors_scope = await client.post(
        _url(abonnement_a),
        json={"paymentAttemptId": str(tentative_a)},
        headers=_entete(registered_user["accessToken"], tenant_b),
    )
    reponse_inexistante = await client.post(
        _url(uuid.uuid4()),
        json={"paymentAttemptId": str(tentative_a)},
        headers=_entete(registered_user["accessToken"], tenant_b),
    )

    assert reponse_hors_scope.status_code == 404, reponse_hors_scope.text
    assert reponse_hors_scope.status_code == reponse_inexistante.status_code
    assert reponse_hors_scope.json()["error"] == reponse_inexistante.json()["error"]
    assert (await _lire_abonnement(abonnement_a)).lifecycleStatus == "cancel_scheduled"
    assert await _evenements_activation(abonnement_a) == 0
