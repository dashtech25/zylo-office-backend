"""BE-078 : résolution de prix, devise et taxe (blocage si non configurés).

Intention : prouver par des tests les critères d'acceptation de BE-078
(implementation-backend/tasks-abonnements-facturation.md, section BE-078) :
- CA-1 : sans règle configurée, la résolution échoue avec PRICE_NOT_CONFIGURED,
  TAX_NOT_CONFIGURED ou CURRENCY_NOT_CONFIGURED selon le cas ; aucun montant
  par défaut n'est retourné (le prix du catalogue n'est pas un repli) ;
- CA-2 : une règle configurée fixe devise et taxe, et le snapshot les capture ;
- CA-3 : une règle modifiée après capture ne change pas le snapshot figé ;
- CA-4 : une règle d'un tenant n'est jamais appliquée à un autre tenant.

Valeurs non définies (décision finance, QE-FAC-06 / QE-FAC-26) : les tests
n'utilisent aucun montant, devise ou taux de référence ; chaque valeur est
saisie dans le test lui-même et sert uniquement à vérifier le contrat.
"""

import uuid

import pytest

from app.billing.errors import BillingErrorCode
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.billing import service
from app.billing.pricing import resolution
from app.identity.models import Organization


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après,
    et les modules connus sont semés (clé étrangère de plan.moduleCode)."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


async def _creer_organisation(db, nom: str) -> Organization:
    organisation = Organization(name=nom, slug=f"be078-{uuid.uuid4().hex[:10]}", status="active")
    db.add(organisation)
    await db.flush()
    return organisation


async def _creer_objet(db) -> str:
    """Offre du catalogue (objet tarifé) ; son prix de catalogue n'est jamais utilisé comme repli."""
    code = f"be078-{uuid.uuid4().hex[:8]}"
    await service.get_or_create_plan(db, "zylo_liquid", code, "Offre BE-078", 1000, "XAF", 30)
    return code


# --- CA-1 : blocage sans configuration -----------------------------------------------


@pytest.mark.asyncio
async def test_ca1_sans_regle_la_resolution_bloque_avec_price_not_configured_sans_montant_par_defaut():
    """CA-1 : aucune règle -> PRICE_NOT_CONFIGURED (422) ; le prix de catalogue (1000) n'est pas retourné."""
    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA1 sans regle")
        objet = await _creer_objet(db)
        await db.commit()
        with pytest.raises(AppError) as erreur:
            await resolution.resoudre_prix(
                db, organization_id=tenant.id, object_code=objet, scenario="achat"
            )
        assert erreur.value.code == BillingErrorCode.PRICE_NOT_CONFIGURED.value
        assert erreur.value.status_code == 422


@pytest.mark.asyncio
async def test_ca1_regle_sans_montant_bloque_avec_price_not_configured():
    """CA-1 : une règle dont le montant n'est pas saisi reste bloquée en PRICE_NOT_CONFIGURED."""
    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA1 montant vide")
        objet = await _creer_objet(db)
        await resolution.definir_regle_prix(
            db, organization_id=tenant.id, object_code=objet, scenario="achat",
            amount_minor=None, currency="XAF", tax_rate_bps=1000,
        )
        with pytest.raises(AppError) as erreur:
            await resolution.resoudre_prix(
                db, organization_id=tenant.id, object_code=objet, scenario="achat"
            )
        assert erreur.value.code == BillingErrorCode.PRICE_NOT_CONFIGURED.value


@pytest.mark.asyncio
async def test_ca1_regle_sans_devise_bloque_avec_currency_not_configured():
    """CA-1 : montant saisi mais devise absente -> CURRENCY_NOT_CONFIGURED."""
    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA1 devise vide")
        objet = await _creer_objet(db)
        await resolution.definir_regle_prix(
            db, organization_id=tenant.id, object_code=objet, scenario="achat",
            amount_minor=5000, currency=None, tax_rate_bps=1000,
        )
        with pytest.raises(AppError) as erreur:
            await resolution.resoudre_prix(
                db, organization_id=tenant.id, object_code=objet, scenario="achat"
            )
        assert erreur.value.code == BillingErrorCode.CURRENCY_NOT_CONFIGURED.value
        assert erreur.value.status_code == 422


@pytest.mark.asyncio
async def test_ca1_regle_sans_taxe_bloque_avec_tax_not_configured():
    """CA-1 : montant et devise saisis, taxe absente -> TAX_NOT_CONFIGURED."""
    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA1 taxe vide")
        objet = await _creer_objet(db)
        await resolution.definir_regle_prix(
            db, organization_id=tenant.id, object_code=objet, scenario="achat",
            amount_minor=5000, currency="XAF", tax_rate_bps=None,
        )
        with pytest.raises(AppError) as erreur:
            await resolution.resoudre_prix(
                db, organization_id=tenant.id, object_code=objet, scenario="achat"
            )
        assert erreur.value.code == BillingErrorCode.TAX_NOT_CONFIGURED.value
        assert erreur.value.status_code == 422


# --- CA-2 : règle configurée et snapshot ----------------------------------------------


@pytest.mark.asyncio
async def test_ca2_regle_configuree_fixe_devise_et_taxe_et_le_snapshot_les_capture():
    """CA-2 : la résolution renvoie montant, devise et taxe de la règle ; le snapshot les contient."""
    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA2")
        objet = await _creer_objet(db)
        await resolution.definir_regle_prix(
            db, organization_id=tenant.id, object_code=objet, scenario="achat",
            amount_minor=4200, currency="EUR", tax_rate_bps=2000,
        )
        prix = await resolution.resoudre_prix(
            db, organization_id=tenant.id, object_code=objet, scenario="achat"
        )
        assert prix.amount_minor == 4200
        assert prix.currency == "EUR"
        assert prix.tax_rate_bps == 2000
        snapshot = prix.as_snapshot()
        assert snapshot["amountMinor"] == 4200
        assert snapshot["currency"] == "EUR"
        assert snapshot["taxRateBps"] == 2000
        assert snapshot["objectCode"] == objet
        assert snapshot["scenario"] == "achat"


# --- CA-3 : figement après capture ----------------------------------------------------


@pytest.mark.asyncio
async def test_ca3_regle_modifiee_apres_capture_ne_change_pas_le_montant_accepte():
    """CA-3 : le snapshot capturé reste identique après modification de la règle ; une nouvelle résolution suit la règle."""
    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA3")
        objet = await _creer_objet(db)
        await resolution.definir_regle_prix(
            db, organization_id=tenant.id, object_code=objet, scenario="achat",
            amount_minor=4200, currency="EUR", tax_rate_bps=2000,
        )
        capture = (await resolution.resoudre_prix(
            db, organization_id=tenant.id, object_code=objet, scenario="achat"
        )).as_snapshot()
        contenu_capture = dict(capture)

    async with AsyncSessionLocal() as db:
        await resolution.definir_regle_prix(
            db, organization_id=tenant.id, object_code=objet, scenario="achat",
            amount_minor=9900, currency="USD", tax_rate_bps=500,
        )

    assert capture == contenu_capture
    assert capture["amountMinor"] == 4200

    async with AsyncSessionLocal() as db:
        nouveau = await resolution.resoudre_prix(
            db, organization_id=tenant.id, object_code=objet, scenario="achat"
        )
        assert nouveau.amount_minor == 9900
        assert nouveau.currency == "USD"


# --- CA-4 : isolation tenant ---------------------------------------------------------


@pytest.mark.asyncio
async def test_ca4_regle_d_un_tenant_jamais_appliquee_a_un_autre_tenant():
    """CA-4 : une règle du tenant A ne sert pas au tenant B, qui reçoit PRICE_NOT_CONFIGURED."""
    async with AsyncSessionLocal() as db:
        tenant_a = await _creer_organisation(db, "Tenant CA4 A")
        tenant_b = await _creer_organisation(db, "Tenant CA4 B")
        objet = await _creer_objet(db)
        await resolution.definir_regle_prix(
            db, organization_id=tenant_a.id, object_code=objet, scenario="achat",
            amount_minor=4200, currency="EUR", tax_rate_bps=2000,
        )
        prix_a = await resolution.resoudre_prix(
            db, organization_id=tenant_a.id, object_code=objet, scenario="achat"
        )
        assert prix_a.amount_minor == 4200
        with pytest.raises(AppError) as erreur:
            await resolution.resoudre_prix(
                db, organization_id=tenant_b.id, object_code=objet, scenario="achat"
            )
        assert erreur.value.code == BillingErrorCode.PRICE_NOT_CONFIGURED.value
