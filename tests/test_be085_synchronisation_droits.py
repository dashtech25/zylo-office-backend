"""BE-085 : demande et suivi de changement de droits (entitlement sync).

Intention : prouver les critères d'acceptation de BE-085
(implementation-backend/tasks-abonnements-facturation.md, section BE-085) :
- CA-1 : une synchronisation `failed` ne repasse jamais à `applied` sans nouvelle demande ;
  tant que les droits ne sont pas appliqués, la lecture renvoie `ENTITLEMENT_SYNC_PENDING` ;
- CA-2 : paiement réussi et droits non confirmés : l'abonnement reste `active`, l'incident de
  cohérence est ouvert (sync `failed`), et aucun paiement n'est écrit (pas de re-débit) ;
- CA-3 : la synchronisation ne peut pas être déclenchée depuis une route publique ;
- CA-4 : une synchronisation ne touche que l'abonnement du tenant de son scope.

Service testé : app/billing/entitlement_sync/service.py.
"""

import importlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.billing import service
from app.billing.models import (
    BillingPayer,
    Checkout,
    EntitlementSync,
    PaymentAttempt,
    PlanVersionSnapshot,
    Quote,
    Subscription,
)
from app.billing.entitlement_sync import service as synchronisation
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.identity.models import Organization


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
        organisation = Organization(name="be085", slug=f"be085-{uuid.uuid4().hex[:10]}", status="active")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _payeur() -> uuid.UUID:
    """Compte payeur de facturation."""
    async with AsyncSessionLocal() as db:
        payeur = BillingPayer(payerKind="organization", accountRef=f"be085-{uuid.uuid4().hex}")
        db.add(payeur)
        await db.commit()
        return payeur.id


async def _abonnement(tenant_id: uuid.UUID, payer_id: uuid.UUID | None = None) -> uuid.UUID:
    """Abonnement actif du tenant ; renvoie son identifiant."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be085-{uuid.uuid4().hex[:8]}", "Plan BE-085", 4990, "XAF", 30
        )
        abonnement = Subscription(
            organizationId=tenant_id,
            planId=plan.id,
            status="active",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
            beneficiaryTenantId=tenant_id,
            payerId=payer_id,
            lifecycleStatus="active",
        )
        db.add(abonnement)
        await db.commit()
        return abonnement.id


async def _paiement_reussi(tenant_id: uuid.UUID, payer_id: uuid.UUID) -> uuid.UUID:
    """Tentative de paiement `succeeded` du tenant (devis, checkout, tentative) ; renvoie son identifiant."""
    maintenant = datetime.now(timezone.utc)
    snapshot_id, devis_id, checkout_id, tentative_id = (uuid.uuid4() for _ in range(4))
    async with AsyncSessionLocal() as db:
        db.add(PlanVersionSnapshot(
            id=snapshot_id,
            organizationId=tenant_id,
            planRef="be085",
            planVersion=1,
            sourceCatalogueRef=f"be085-{uuid.uuid4().hex}",
            snapshotJson={"offre": "be085"},
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
            idempotencyKey=f"be085-{uuid.uuid4().hex}",
            amountMinor=4990,
            currency="XAF",
            status="succeeded",
            requestedAt=maintenant,
        ))
        await db.commit()
    return tentative_id


async def _demander(tenant_id: uuid.UUID, abonnement_id: uuid.UUID) -> uuid.UUID:
    """Demande une synchronisation ; renvoie l'identifiant de la ligne créée."""
    async with AsyncSessionLocal() as db:
        sync = await synchronisation.demander_synchronisation(
            db, tenant_id=tenant_id, subscription_id=abonnement_id
        )
        return sync.id


async def _enregistrer(tenant_id: uuid.UUID, sync_id: uuid.UUID, issue: str, code: str | None = None) -> None:
    """Enregistre l'issue d'une synchronisation."""
    async with AsyncSessionLocal() as db:
        await synchronisation.enregistrer_resultat(
            db, tenant_id=tenant_id, synchronisation_id=sync_id, issue=issue, code=code
        )


async def _verifier(tenant_id: uuid.UUID, abonnement_id: uuid.UUID) -> None:
    """Lecture de la confirmation des droits (lève si non confirmés)."""
    async with AsyncSessionLocal() as db:
        await synchronisation.verifier_droits_confirmes(db, tenant_id=tenant_id, subscription_id=abonnement_id)


async def _code_erreur(appel) -> tuple[int, str]:
    """Attend une `AppError` ; renvoie (statut HTTP, code)."""
    try:
        await appel
    except AppError as erreur:
        return erreur.status_code, erreur.code
    raise AssertionError("une erreur métier était attendue")


async def _lire(sync_id: uuid.UUID) -> tuple[str, int, str | None]:
    """Relit (status, attempts, lastErrorCode) directement en base."""
    async with AsyncSessionLocal() as db:
        ligne = await db.get(EntitlementSync, sync_id)
        return ligne.status, ligne.attempts, ligne.lastErrorCode


async def _lire_abonnement(abonnement_id: uuid.UUID) -> tuple[str, str, str]:
    """Relit (lifecycleStatus, financialStatus, incidentStatus) directement en base."""
    async with AsyncSessionLocal() as db:
        abonnement = await db.get(Subscription, abonnement_id)
        return abonnement.lifecycleStatus, abonnement.financialStatus, abonnement.incidentStatus


async def _nombre_de_synchronisations(abonnement_id: uuid.UUID) -> int:
    """Nombre de lignes `entitlement_sync` de cet abonnement."""
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count()).select_from(EntitlementSync).where(EntitlementSync.subscriptionId == abonnement_id)
        )


async def _nombre_de_paiements() -> int:
    """Nombre total de tentatives de paiement en base."""
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(PaymentAttempt))


# CA-1 : failed ne repasse jamais à applied sans nouvelle demande.

async def test_ca1_echec_ne_repasse_pas_a_applied_sans_nouvelle_demande():
    tenant = await _organisation()
    abonnement = await _abonnement(tenant)
    premiere = await _demander(tenant, abonnement)
    await _enregistrer(tenant, premiere, "failed", "ENTITLEMENT_APPLY_FAILED")
    assert await _lire(premiere) == ("failed", 1, "ENTITLEMENT_APPLY_FAILED")

    assert await _code_erreur(_enregistrer(tenant, premiere, "applied")) == (409, "INVALID_TRANSITION")
    assert (await _lire(premiere))[0] == "failed", "un échec reste un échec"
    assert await _code_erreur(_verifier(tenant, abonnement)) == (409, "ENTITLEMENT_SYNC_PENDING")


async def test_ca1_nouvelle_demande_seule_ouvre_une_synchronisation_applicable():
    tenant = await _organisation()
    abonnement = await _abonnement(tenant)
    premiere = await _demander(tenant, abonnement)
    await _enregistrer(tenant, premiere, "failed", "ENTITLEMENT_APPLY_FAILED")

    nouvelle = await _demander(tenant, abonnement)
    assert await _lire(nouvelle) == ("requested", 0, None)
    assert await _code_erreur(_verifier(tenant, abonnement)) == (409, "ENTITLEMENT_SYNC_PENDING")

    await _enregistrer(tenant, nouvelle, "applied")
    assert await _lire(nouvelle) == ("applied", 1, None)
    assert await _verifier(tenant, abonnement) is None
    assert (await _lire(premiere))[0] == "failed", "la ligne en échec n'est pas réécrite"


async def test_ca1_retry_pending_reste_en_attente_puis_applique_par_le_meme_suivi():
    tenant = await _organisation()
    abonnement = await _abonnement(tenant)
    sync = await _demander(tenant, abonnement)
    await _enregistrer(tenant, sync, "retry_pending", "PROVIDER_UNAVAILABLE")
    assert await _lire(sync) == ("retry_pending", 1, "PROVIDER_UNAVAILABLE")
    assert await _code_erreur(_verifier(tenant, abonnement)) == (409, "ENTITLEMENT_SYNC_PENDING")

    await _enregistrer(tenant, sync, "applied")
    assert await _lire(sync) == ("applied", 2, None)
    assert await _verifier(tenant, abonnement) is None


# CA-2 : paiement réussi, droits non confirmés : pas de changement commercial ni de re-débit.

async def test_ca2_paiement_reussi_droits_non_confirmes_garde_active_sans_redebit():
    tenant = await _organisation()
    payeur = await _payeur()
    abonnement = await _abonnement(tenant, payeur)
    tentative = await _paiement_reussi(tenant, payeur)
    paiements_avant = await _nombre_de_paiements()

    sync = await _demander(tenant, abonnement)
    await _enregistrer(tenant, sync, "failed", "ENTITLEMENT_APPLY_FAILED")

    assert await _lire_abonnement(abonnement) == ("active", "none", "none"), "aucun axe n'est modifié"
    assert await _lire(sync) == ("failed", 1, "ENTITLEMENT_APPLY_FAILED"), "l'incident de cohérence reste ouvert"
    assert await _code_erreur(_verifier(tenant, abonnement)) == (409, "ENTITLEMENT_SYNC_PENDING")
    assert await _nombre_de_paiements() == paiements_avant, "aucune nouvelle tentative de paiement (pas de re-débit)"
    async with AsyncSessionLocal() as db:
        assert (await db.get(PaymentAttempt, tentative)).status == "succeeded"


# CA-3 : aucune route publique ne déclenche la synchronisation.

async def test_ca3_aucune_route_publique_ne_declenche_la_synchronisation():
    from app.main import app

    chemins = [getattr(route, "path", "") for route in app.routes]
    assert not [chemin for chemin in chemins if "sync" in chemin.lower()], "aucune route de synchronisation"
    module = importlib.import_module("app.billing.entitlement_sync")
    assert not hasattr(module, "router"), "le paquet n'expose aucun routeur HTTP"


# CA-4 : isolation tenant.

async def test_ca4_autre_tenant_traite_comme_abonnement_inexistant():
    tenant_a = await _organisation()
    tenant_b = await _organisation()
    abonnement = await _abonnement(tenant_a)

    reponse_autre_tenant = await _code_erreur(_demander(tenant_b, abonnement))
    reponse_inexistant = await _code_erreur(_demander(tenant_b, uuid.uuid4()))
    assert reponse_autre_tenant == reponse_inexistant == (404, "subscription_not_found")
    assert await _nombre_de_synchronisations(abonnement) == 0


async def test_ca4_autre_tenant_ne_peut_pas_enregistrer_le_resultat():
    tenant_a = await _organisation()
    tenant_b = await _organisation()
    abonnement = await _abonnement(tenant_a)
    sync = await _demander(tenant_a, abonnement)

    assert await _code_erreur(_enregistrer(tenant_b, sync, "applied")) == (404, "entitlement_sync_not_found")
    assert (await _lire(sync))[0] == "requested"


async def test_ca4_synchronisation_ne_touche_que_l_abonnement_du_tenant():
    tenant_a = await _organisation()
    tenant_b = await _organisation()
    abonnement_a = await _abonnement(tenant_a)
    abonnement_b = await _abonnement(tenant_b)

    await _demander(tenant_a, abonnement_a)

    assert await _nombre_de_synchronisations(abonnement_b) == 0
    assert await _lire_abonnement(abonnement_b) == ("active", "none", "none")
