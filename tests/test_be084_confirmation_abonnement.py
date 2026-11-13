"""BE-084 : confirmation d'abonnement à partir d'un paiement confirmé.

Intention : prouver les critères d'acceptation de BE-084
(implementation-backend/tasks-abonnements-facturation.md, section BE-084) :
- CA-1 : un paiement `succeeded` confirmé passe l'abonnement à `active` et émet `SubscriptionActivated` ;
- CA-2 : un succès fournisseur avec échec local est repris par la finalisation, sans nouvelle capture ;
- CA-3 : un paiement `unknown` (ou non confirmé) ne déclenche pas l'activation ;
- CA-4 : la confirmation ne modifie que l'abonnement du checkout concerné, et jamais celui d'un autre tenant.

Service testé : app/billing/activation/service.py (`confirmer_abonnement`).
"""

import inspect
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.billing import service
from app.billing.activation import service as activation
from app.billing.models import BillingPayer, Checkout, PaymentAttempt, PlanVersionSnapshot, Quote, Subscription
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.evenements.models import OutboxEvenement
from app.identity.models import Organization

TYPE_EVENEMENT = "SubscriptionActivated"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


async def _organisation() -> uuid.UUID:
    """Organisation (tenant) sans lien HTTP, pour les tests de service."""
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="be084", slug=f"be084-{uuid.uuid4().hex[:10]}", status="active")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _payeur() -> uuid.UUID:
    """Compte payeur de facturation."""
    async with AsyncSessionLocal() as db:
        payeur = BillingPayer(payerKind="organization", accountRef=f"be084-{uuid.uuid4().hex}")
        db.add(payeur)
        await db.commit()
        return payeur.id


async def _abonnement_pending(tenant_id: uuid.UUID, payer_id: uuid.UUID) -> uuid.UUID:
    """Abonnement du tenant payé par `payer_id`, cycle de vie `pending` ; renvoie son identifiant."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be084-{uuid.uuid4().hex[:8]}", "Plan BE-084", 4990, "XAF", 30
        )
        abonnement = Subscription(
            organizationId=tenant_id,
            planId=plan.id,
            status="trial",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
            beneficiaryTenantId=tenant_id,
            payerId=payer_id,
            lifecycleStatus="pending",
        )
        db.add(abonnement)
        await db.commit()
        return abonnement.id


async def _checkout_avec_tentative(tenant_id: uuid.UUID, payer_id: uuid.UUID, statut: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Devis accepté du tenant pour le payeur, checkout `pending` et tentative au `statut` donné.

    Renvoie (identifiant de la tentative, identifiant du checkout).
    """
    maintenant = datetime.now(timezone.utc)
    snapshot_id = uuid.uuid4()
    devis_id = uuid.uuid4()
    checkout_id = uuid.uuid4()
    tentative_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(PlanVersionSnapshot(
            id=snapshot_id,
            organizationId=tenant_id,
            planRef="be084",
            planVersion=1,
            sourceCatalogueRef=f"be084-{uuid.uuid4().hex}",
            snapshotJson={"offre": "be084"},
        ))
        await db.flush()
        db.add(Quote(
            id=devis_id,
            payerId=payer_id,
            beneficiaryTenantId=tenant_id,
            planVersionSnapshotId=snapshot_id,
            status="accepted",
            pricingSnapshotJson={"amountMinor": 4990, "currency": "XAF"},
        ))
        await db.flush()
        db.add(Checkout(id=checkout_id, quoteId=devis_id, status="pending", version=1))
        await db.flush()
        db.add(PaymentAttempt(
            id=tentative_id,
            checkoutId=checkout_id,
            provider="flutterwave",
            mode="test",
            idempotencyKey=f"be084-{uuid.uuid4().hex}",
            amountMinor=4990,
            currency="XAF",
            status=statut,
            requestedAt=maintenant,
        ))
        await db.commit()
    return tentative_id, checkout_id


async def _lire_cycle(subscription_id: uuid.UUID) -> str:
    """Relit le cycle de vie directement en base (pas de cache de session)."""
    async with AsyncSessionLocal() as db:
        abonnement = await db.scalar(select(Subscription).where(Subscription.id == subscription_id))
        return abonnement.lifecycleStatus


async def _evenements_activation(subscription_id: uuid.UUID) -> int:
    """Nombre d'évènements `SubscriptionActivated` de l'outbox visant cet abonnement."""
    async with AsyncSessionLocal() as db:
        lignes = (await db.execute(
            select(OutboxEvenement).where(OutboxEvenement.eventType == TYPE_EVENEMENT)
        )).scalars().all()
    # La colonne `payload` de l'outbox porte l'enveloppe complète ; les données métier sont sous `payload`.
    return sum(
        1 for ligne in lignes if (ligne.payload.get("payload") or {}).get("subscriptionId") == str(subscription_id)
    )


async def _confirmer(tenant_id: uuid.UUID, tentative_id: uuid.UUID):
    async with AsyncSessionLocal() as db:
        return await activation.confirmer_abonnement(db, tenant_id=tenant_id, payment_attempt_id=tentative_id)


# CA-1 : paiement succeeded confirmé -> abonnement active et évènement émis.

async def test_ca1_paiement_succeeded_passe_l_abonnement_a_active_et_emet_l_evenement():
    tenant = await _organisation()
    payeur = await _payeur()
    abonnement = await _abonnement_pending(tenant, payeur)
    tentative, _ = await _checkout_avec_tentative(tenant, payeur, "succeeded")

    confirme = await _confirmer(tenant, tentative)

    assert confirme.id == abonnement
    assert confirme.lifecycleStatus == "active"
    assert await _lire_cycle(abonnement) == "active"
    assert await _evenements_activation(abonnement) == 1, "SubscriptionActivated est écrit une seule fois dans l'outbox"


# CA-2 : succès fournisseur, échec local, reprise par la finalisation sans nouvelle capture.

async def test_ca2_echec_local_puis_reprise_sans_nouvelle_capture(monkeypatch):
    tenant = await _organisation()
    payeur = await _payeur()
    abonnement = await _abonnement_pending(tenant, payeur)
    tentative, _ = await _checkout_avec_tentative(tenant, payeur, "succeeded")

    def emission_en_panne(*args, **kwargs):
        raise RuntimeError("panne locale de l'outbox")

    monkeypatch.setattr(activation, "emettre_evenement_facturation", emission_en_panne)
    with pytest.raises(RuntimeError):
        await _confirmer(tenant, tentative)
    monkeypatch.undo()

    assert await _lire_cycle(abonnement) == "pending", "l'échec local annule l'activation"
    assert await _evenements_activation(abonnement) == 0

    # Reprise : la finalisation rejoue la confirmation. Le service ne reçoit aucun fournisseur :
    # aucune capture ne peut donc être relancée.
    parametres = set(inspect.signature(activation.confirmer_abonnement).parameters)
    assert not {"fournisseur", "provider", "charge"} & parametres

    await _confirmer(tenant, tentative)

    assert await _lire_cycle(abonnement) == "active"
    assert await _evenements_activation(abonnement) == 1, "la reprise émet l'évènement une seule fois"


# CA-3 : un paiement non confirmé ne déclenche pas l'activation.

async def test_ca3_paiement_unknown_ne_declenche_pas_l_activation():
    tenant = await _organisation()
    payeur = await _payeur()
    abonnement = await _abonnement_pending(tenant, payeur)
    tentative, _ = await _checkout_avec_tentative(tenant, payeur, "unknown")

    with pytest.raises(AppError) as erreur:
        await _confirmer(tenant, tentative)

    assert erreur.value.code == "RESULT_UNKNOWN"
    assert await _lire_cycle(abonnement) == "pending"
    assert await _evenements_activation(abonnement) == 0


@pytest.mark.parametrize("statut", ["created", "submitted", "pending", "failed", "cancelled"])
async def test_ca3_paiement_non_succeeded_renvoie_invalid_transition_sans_effet(statut: str):
    tenant = await _organisation()
    payeur = await _payeur()
    abonnement = await _abonnement_pending(tenant, payeur)
    tentative, _ = await _checkout_avec_tentative(tenant, payeur, statut)

    with pytest.raises(AppError) as erreur:
        await _confirmer(tenant, tentative)

    assert erreur.value.code == "INVALID_TRANSITION"
    assert await _lire_cycle(abonnement) == "pending"
    assert await _evenements_activation(abonnement) == 0


# CA-4 : isolation tenant, seul l'abonnement du checkout concerné change.

async def test_ca4_ne_modifie_que_l_abonnement_du_checkout():
    tenant = await _organisation()
    payeur_du_checkout = await _payeur()
    autre_payeur = await _payeur()
    abonnement_concerne = await _abonnement_pending(tenant, payeur_du_checkout)
    abonnement_voisin = await _abonnement_pending(tenant, autre_payeur)
    tentative, _ = await _checkout_avec_tentative(tenant, payeur_du_checkout, "succeeded")

    await _confirmer(tenant, tentative)

    assert await _lire_cycle(abonnement_concerne) == "active"
    assert await _lire_cycle(abonnement_voisin) == "pending", "l'abonnement d'un autre payeur n'est pas touché"
    assert await _evenements_activation(abonnement_voisin) == 0


async def test_ca4_tentative_d_un_autre_tenant_traitee_comme_inexistante():
    tenant_a = await _organisation()
    tenant_b = await _organisation()
    payeur = await _payeur()
    abonnement_a = await _abonnement_pending(tenant_a, payeur)
    tentative_a, _ = await _checkout_avec_tentative(tenant_a, payeur, "succeeded")

    with pytest.raises(AppError) as erreur:
        await _confirmer(tenant_b, tentative_a)

    assert erreur.value.code == "payment_attempt_not_found"
    assert erreur.value.status_code == 404
    assert await _lire_cycle(abonnement_a) == "pending"
    assert await _evenements_activation(abonnement_a) == 0
