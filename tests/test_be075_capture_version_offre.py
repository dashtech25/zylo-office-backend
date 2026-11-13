"""BE-075 : capture de la version d'offre au devis et au contrat.

Intention : prouver par des tests les critères d'acceptation de BE-075
(implementation-backend/tasks-abonnements-facturation.md, section BE-075) :
- CA-1 : une capture fige la version publiée ; une modification ultérieure du
  catalogue (nouvelle version, prix changé) n'altère pas `snapshotJson` ;
- CA-2 : une offre `withdrawn` ne peut plus être capturée (`INVALID_TRANSITION`),
  et un abonnement existant conserve sa version ;
- CA-3 : un appelant sans droit de lecture catalogue ne lit pas `snapshotJson`
  (`FORBIDDEN`) ;
- CA-4 : un snapshot du tenant A n'est pas visible depuis le tenant B.

Table `plan_version_snapshot` : colonnes id, planRef, planVersion, capturedAt,
sourceCatalogueRef, snapshotJson (définition), plus organizationId (ajout
nécessaire à CA-4, voir la docstring de app/billing/models.py::PlanVersionSnapshot).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.billing import catalog_snapshot, service
from app.billing.errors import BillingErrorCode
from app.billing.models import PlanVersion, PlanVersionSnapshot, Subscription
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.identity.models import Organization, User


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
    organisation = Organization(name=nom, slug=f"be075-{uuid.uuid4().hex[:10]}", status="active")
    db.add(organisation)
    await db.flush()
    return organisation


async def _creer_utilisateur(db, nom: str) -> User:
    utilisateur = User(
        email=f"be075-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        hashedPassword="non-utilisable-be075",
        fullName=nom,
    )
    db.add(utilisateur)
    await db.flush()
    return utilisateur


async def _creer_plan(db, prix: int = 1000) -> str:
    """Plan du catalogue (version 1 à `prix`) ; renvoie son code."""
    code = f"be075-{uuid.uuid4().hex[:8]}"
    await service.get_or_create_plan(db, "zylo_liquid", code, "Plan BE-075", prix, "XAF", 30)
    return code


# --- CA-1 : figement de la version publiée -----------------------------------------


@pytest.mark.asyncio
async def test_ca1_capture_fige_la_version_publiee_et_ne_change_pas_apres_publication():
    """CA-1 : après une nouvelle version publiée et un changement de prix, le snapshot capturé reste identique."""
    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA1")
        auteur = await _creer_utilisateur(db, "Auteur CA1")
        code = await _creer_plan(db, prix=1000)
        capture = await catalog_snapshot.capturer_version_offre(
            db, organization_id=tenant.id, plan_code=code, actor_user_id=auteur.id
        )
        capture_id = capture.id
        contenu_initial = dict(capture.snapshotJson)
        assert capture.planRef == code
        assert capture.planVersion == 1
        assert contenu_initial["version"]["amountMinor"] == 1000

    async with AsyncSessionLocal() as db:
        # Le catalogue évolue : nouvelle version publiée à 2500, le prix du plan est réécrit.
        await service.publish_plan_version(db, code, 2500, "XAF", 30, ["zylo_liquid.base"])

    async with AsyncSessionLocal() as db:
        relu = await db.get(PlanVersionSnapshot, capture_id)
        assert relu.snapshotJson == contenu_initial
        assert relu.planVersion == 1


# --- CA-2 : offre retirée ----------------------------------------------------------


@pytest.mark.asyncio
async def test_ca2_offre_withdrawn_refuse_une_nouvelle_capture_sans_effet_sur_abonnement_existant():
    """CA-2 : statut `withdrawn` -> INVALID_TRANSITION ; l'abonnement existant garde sa version."""
    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA2")
        auteur = await _creer_utilisateur(db, "Auteur CA2")
        code = await _creer_plan(db)
        version = await service.ensure_initial_plan_version(db, await _plan_par_code(db, code))
        maintenant = datetime.now(timezone.utc)
        abonnement = Subscription(
            organizationId=tenant.id,
            planId=version.planId,
            planVersionId=version.id,
            status="active",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
        )
        db.add(abonnement)
        await db.commit()
        abonnement_id, version_id = abonnement.id, version.id
        # Retrait de l'offre (statut withdrawn sur la version publiée).
        version.status = "withdrawn"
        await db.commit()

    async with AsyncSessionLocal() as db:
        auteur = await _creer_utilisateur(db, "Auteur CA2 bis")
        await db.commit()
        with pytest.raises(AppError) as erreur:
            await catalog_snapshot.capturer_version_offre(
                db, organization_id=tenant.id, plan_code=code, actor_user_id=auteur.id
            )
        assert erreur.value.code == BillingErrorCode.INVALID_TRANSITION.value
        assert erreur.value.status_code == 409

    async with AsyncSessionLocal() as db:
        abonnement_relu = await db.get(Subscription, abonnement_id)
        assert abonnement_relu.planVersionId == version_id
        assert abonnement_relu.status == "active"
        nb = await db.scalar(select(text("count(*)")).select_from(PlanVersionSnapshot.__table__).where(
            PlanVersionSnapshot.__table__.c.planRef == code
        ))
        assert nb == 0


# --- CA-3 : lecture de snapshotJson refusée sans droit ----------------------------


@pytest.mark.asyncio
async def test_ca3_lecture_du_snapshot_refusee_sans_droit_de_lecture_catalogue():
    """CA-3 : un appelant du tenant sans permission de lecture catalogue reçoit FORBIDDEN."""
    async with AsyncSessionLocal() as db:
        tenant = await _creer_organisation(db, "Tenant CA3")
        auteur = await _creer_utilisateur(db, "Auteur CA3")
        code = await _creer_plan(db)
        capture = await catalog_snapshot.capturer_version_offre(
            db, organization_id=tenant.id, plan_code=code, actor_user_id=auteur.id
        )
        snapshot_id, tenant_id = capture.id, tenant.id
        sans_droit = await _creer_utilisateur(db, "Sans droit CA3")
        await db.commit()

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await catalog_snapshot.lire_snapshot(
                db, organization_id=tenant_id, actor_user_id=sans_droit.id, snapshot_id=snapshot_id
            )
        assert erreur.value.code == BillingErrorCode.FORBIDDEN.value
        assert erreur.value.status_code == 403


# --- CA-4 : isolation tenant -------------------------------------------------------


@pytest.mark.asyncio
async def test_ca4_snapshot_du_tenant_a_invisible_depuis_le_tenant_b():
    """CA-4 : depuis le tenant B, le snapshot du tenant A est traité comme inexistant (404)."""
    async with AsyncSessionLocal() as db:
        tenant_a = await _creer_organisation(db, "Tenant A CA4")
        tenant_b = await _creer_organisation(db, "Tenant B CA4")
        auteur = await _creer_utilisateur(db, "Auteur CA4")
        code = await _creer_plan(db)
        capture = await catalog_snapshot.capturer_version_offre(
            db, organization_id=tenant_a.id, plan_code=code, actor_user_id=auteur.id
        )
        snapshot_id, tenant_b_id, auteur_id = capture.id, tenant_b.id, auteur.id

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await catalog_snapshot.lire_snapshot(
                db, organization_id=tenant_b_id, actor_user_id=auteur_id, snapshot_id=snapshot_id
            )
        assert erreur.value.status_code == 404


# --- Structure de la table ---------------------------------------------------------


@pytest.mark.asyncio
async def test_table_plan_version_snapshot_a_les_colonnes_definies():
    """Définition : id, planRef, planVersion, capturedAt, sourceCatalogueRef, snapshotJson ; organizationId ajouté (CA-4)."""
    async with engine.connect() as conn:
        resultat = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'plan_version_snapshot'"
        ))
        colonnes = {ligne[0] for ligne in resultat}
    assert colonnes == {"id", "planRef", "planVersion", "capturedAt", "sourceCatalogueRef", "snapshotJson", "organizationId"}


async def _plan_par_code(db, code: str):
    from app.billing.models import Plan

    return await db.scalar(select(Plan).where(Plan.code == code))
