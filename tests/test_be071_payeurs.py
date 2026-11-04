"""BE-071 : séparation payeur, bénéficiaire (tenant) et administrateur.

Intention : prouver par des tests les critères d'acceptation de BE-071
(implementation-backend/tasks-abonnements-facturation.md, section BE-071) :
- CA-1 : un abonnement peut référencer un payeur différent du tenant
  bénéficiaire, et les deux identifiants sont persistés séparément ;
- CA-2 : un payeur qui n'est pas administrateur du tenant ne peut pas changer
  `adminUserId` (`FORBIDDEN`) ;
- CA-3 : un abonnement du tenant A n'est jamais listé ni lu depuis le scope du
  tenant B ;
- CA-4 : un paiement réussi pour un payeur n'accorde aucun droit ; l'accès
  résultant reste inchangé.

Les tests s'appuient sur la table `subscription` de BE-023 (non redéfinie) et
sur la base de test zylo_t<NNN>_test (tests/conftest.py).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app.billing import service
from app.billing.models import BillingPayer, Invoice, PaymentAttempt, Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import Organization, User


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui.

    Les modules connus (zylo_liquid, clé étrangère de plan.moduleCode) sont semés
    avant chaque test, comme le fait la fixture `client` de tests/conftest.py.
    """
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


async def _creer_organisation(db, nom: str) -> Organization:
    organisation = Organization(name=nom, slug=f"be071-{uuid.uuid4().hex[:10]}", status="active")
    db.add(organisation)
    await db.flush()
    return organisation


async def _creer_utilisateur(db, nom: str) -> User:
    utilisateur = User(
        email=f"be071-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        hashedPassword="non-utilisable-be071",
        fullName=nom,
    )
    db.add(utilisateur)
    await db.flush()
    return utilisateur


async def _creer_abonnement(db, *, tenant_id, payeur_id, admin_id) -> Subscription:
    """Abonnement BE-023 porteur des colonnes de BE-071 ; le plan est créé au passage."""
    maintenant = datetime.now(timezone.utc)
    plan = await service.get_or_create_plan(
        db, "zylo_liquid", f"be071-{uuid.uuid4().hex[:8]}", "Plan BE-071", 1000, "XAF", 30
    )
    abonnement = Subscription(
        organizationId=tenant_id,
        planId=plan.id,
        status="active",
        startDate=maintenant,
        endDate=maintenant + timedelta(days=30),
        payerId=payeur_id,
        beneficiaryTenantId=tenant_id,
        adminUserId=admin_id,
    )
    db.add(abonnement)
    await db.commit()
    return abonnement


# --- CA-1 : payeur et tenant bénéficiaire persistés séparément ----------------------


@pytest.mark.asyncio
async def test_ca1_payeur_different_du_tenant_persiste_separement():
    """CA-1 : le payeur (table billing_payer) et le tenant bénéficiaire sont deux colonnes distinctes."""
    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA1")
        payeur_org = await _creer_organisation(db, "Payeur CA1")
        admin = await _creer_utilisateur(db, "Admin CA1")
        payeur = BillingPayer(payerKind="organisation", accountRef=str(payeur_org.id))
        db.add(payeur)
        await db.commit()
        abonnement = await _creer_abonnement(db, tenant_id=tenant.id, payeur_id=payeur.id, admin_id=admin.id)
        abonnement_id, tenant_id, payeur_id = abonnement.id, tenant.id, payeur.id

    async with AsyncSessionLocal() as db:
        lu = await db.get(Subscription, abonnement_id)
        assert lu.payerId == payeur_id
        assert lu.beneficiaryTenantId == tenant_id
        assert lu.payerId != lu.beneficiaryTenantId


@pytest.mark.asyncio
async def test_ca1_table_billing_payer_a_les_colonnes_definies():
    """CA-1 : billing_payer porte id, payerKind, accountRef, createdAt (et seulement celles-là)."""
    async with engine.connect() as conn:
        colonnes = set((await conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'billing_payer'"
        ))).scalars().all())
    assert colonnes == {"id", "payerKind", "accountRef", "createdAt"}


# --- CA-2 : seul l'administrateur du tenant change adminUserId ----------------------


@pytest.mark.asyncio
async def test_ca2_payeur_non_administrateur_ne_change_pas_l_administrateur():
    """CA-2 : un payeur qui n'administre pas le tenant reçoit FORBIDDEN ; adminUserId reste intact."""
    from app.billing.payers import changer_administrateur

    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA2")
        payeur_org = await _creer_organisation(db, "Payeur CA2")
        admin = await _creer_utilisateur(db, "Admin CA2")
        payeur_user = await _creer_utilisateur(db, "Payeur user CA2")
        nouvel_admin = await _creer_utilisateur(db, "Nouvel admin CA2")
        payeur = BillingPayer(payerKind="organisation", accountRef=str(payeur_org.id))
        db.add(payeur)
        await db.commit()
        abonnement = await _creer_abonnement(db, tenant_id=tenant.id, payeur_id=payeur.id, admin_id=admin.id)
        abonnement_id, admin_id, nouvel_admin_id, payeur_user_id = abonnement.id, admin.id, nouvel_admin.id, payeur_user.id
        tenant_id = tenant.id

    async with AsyncSessionLocal() as db:
        with pytest.raises(Exception) as exc_info:
            await changer_administrateur(db, abonnement_id, tenant_id, payeur_user_id, nouvel_admin_id)
        assert getattr(exc_info.value, "code", None) == "FORBIDDEN"
        assert getattr(exc_info.value, "status_code", None) == 403

    async with AsyncSessionLocal() as db:
        lu = await db.get(Subscription, abonnement_id)
        assert lu.adminUserId == admin_id


@pytest.mark.asyncio
async def test_ca2_administrateur_du_tenant_peut_changer_adminuserid():
    """CA-2 (contrepartie) : l'administrateur courant du tenant peut transmettre la fonction."""
    from app.billing.payers import changer_administrateur

    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA2b")
        payeur_org = await _creer_organisation(db, "Payeur CA2b")
        admin = await _creer_utilisateur(db, "Admin CA2b")
        nouvel_admin = await _creer_utilisateur(db, "Nouvel admin CA2b")
        payeur = BillingPayer(payerKind="organisation", accountRef=str(payeur_org.id))
        db.add(payeur)
        await db.commit()
        abonnement = await _creer_abonnement(db, tenant_id=tenant.id, payeur_id=payeur.id, admin_id=admin.id)
        abonnement_id, tenant_id, admin_id, nouvel_admin_id = abonnement.id, tenant.id, admin.id, nouvel_admin.id

    async with AsyncSessionLocal() as db:
        modifie = await changer_administrateur(db, abonnement_id, tenant_id, admin_id, nouvel_admin_id)
        assert modifie.adminUserId == nouvel_admin_id


# --- CA-3 : isolation tenant --------------------------------------------------------


@pytest.mark.asyncio
async def test_ca3_abonnement_du_tenant_a_jamais_lu_depuis_le_tenant_b():
    """CA-3 : l'abonnement du tenant A n'apparaît ni dans la lecture ni dans la liste du tenant B."""
    from app.billing.payers import changer_administrateur

    async with AsyncSessionLocal() as db:
        tenant_a = await _creer_organisation(db, "Tenant A CA3")
        tenant_b = await _creer_organisation(db, "Tenant B CA3")
        payeur_org = await _creer_organisation(db, "Payeur CA3")
        admin = await _creer_utilisateur(db, "Admin CA3")
        nouvel_admin = await _creer_utilisateur(db, "Nouvel admin CA3")
        payeur = BillingPayer(payerKind="organisation", accountRef=str(payeur_org.id))
        db.add(payeur)
        await db.commit()
        abonnement = await _creer_abonnement(db, tenant_id=tenant_a.id, payeur_id=payeur.id, admin_id=admin.id)
        abonnement_id = abonnement.id
        tenant_a_id, tenant_b_id = tenant_a.id, tenant_b.id
        admin_id, nouvel_admin_id = admin.id, nouvel_admin.id

    async with AsyncSessionLocal() as db:
        assert await service.current_subscription(db, tenant_b_id) is None
        lignes_b = (await db.scalars(select(Subscription).where(Subscription.beneficiaryTenantId == tenant_b_id))).all()
        assert lignes_b == []
        vu_par_a = await service.current_subscription(db, tenant_a_id)
        assert vu_par_a is not None and vu_par_a[0].id == abonnement_id

    async with AsyncSessionLocal() as db:
        with pytest.raises(Exception) as exc_info:
            await changer_administrateur(db, abonnement_id, tenant_b_id, admin_id, nouvel_admin_id)
        assert getattr(exc_info.value, "code", None) == "subscription_not_found"
        assert getattr(exc_info.value, "status_code", None) == 404


# --- CA-4 : un paiement n'accorde aucun droit ---------------------------------------


@pytest.mark.asyncio
async def test_ca4_paiement_reussi_pour_un_payeur_n_accorde_aucun_droit():
    """CA-4 : paiement réussi pour le payeur, aucune ligne d'entitlement ajoutée, accès inchangé."""
    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA4")
        payeur_org = await _creer_organisation(db, "Payeur CA4")
        admin = await _creer_utilisateur(db, "Admin CA4")
        payeur = BillingPayer(payerKind="organisation", accountRef=str(payeur_org.id))
        db.add(payeur)
        await db.commit()
        abonnement = await _creer_abonnement(db, tenant_id=tenant.id, payeur_id=payeur.id, admin_id=admin.id)
        db.add(SubscriptionEntitlement(
            organizationId=tenant.id,
            subscriptionId=abonnement.id,
            moduleCode="zylo_liquid",
            entitlementCode="be071.acces.test",
            status="active",
            startsAt=datetime.now(timezone.utc),
            endsAt=abonnement.endDate,
            sourceAttribution="offre",
            niveauApplication="organisation",
        ))
        facture = Invoice(
            subscriptionId=abonnement.id, amountCents=1000, amountMinor=1000, currency="XAF",
            status="paid", issuedAt=datetime.now(timezone.utc), paidAt=datetime.now(timezone.utc),
        )
        db.add(facture)
        await db.flush()
        db.add(PaymentAttempt(
            invoiceId=facture.id, provider="test", mode="test", idempotencyKey=f"be071-{uuid.uuid4().hex}",
            providerReference=f"ref-{uuid.uuid4().hex}", amountMinor=1000, currency="XAF",
            status="succeeded", requestedAt=datetime.now(timezone.utc),
        ))
        await db.commit()
        abonnement_id, tenant_id = abonnement.id, tenant.id

    async with AsyncSessionLocal() as db:
        avant = await service.current_subscription(db, tenant_id)
        avant_droits = sorted(avant[1])
        nombre_avant = await db.scalar(
            select(func.count()).select_from(SubscriptionEntitlement).where(SubscriptionEntitlement.subscriptionId == abonnement_id)
        )

    async with AsyncSessionLocal() as db:
        db.add(PaymentAttempt(
            invoiceId=(await db.scalar(select(Invoice.id).where(Invoice.subscriptionId == abonnement_id))),
            provider="test", mode="test", idempotencyKey=f"be071-{uuid.uuid4().hex}",
            providerReference=f"ref-{uuid.uuid4().hex}", amountMinor=1000, currency="XAF",
            status="succeeded", requestedAt=datetime.now(timezone.utc),
        ))
        await db.commit()

    async with AsyncSessionLocal() as db:
        apres = await service.current_subscription(db, tenant_id)
        nombre_apres = await db.scalar(
            select(func.count()).select_from(SubscriptionEntitlement).where(SubscriptionEntitlement.subscriptionId == abonnement_id)
        )
        assert sorted(apres[1]) == avant_droits
        assert nombre_apres == nombre_avant
