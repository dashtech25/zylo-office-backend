"""BE-024 : entitlements d'abonnement (modèle, migration et calcul).

Intention : prouver par des tests les critères d'acceptation de BE-024
(implementation-backend/tasks-socle-tenant-identite.md, section BE-024), qui
absorbe BE-261 (CA-5 à CA-10 de BE-024 = CA-1 à CA-6 de BE-261) :
- CA-1 : l'entitlement calculé provient de la version de plan active ;
- CA-2 : un entitlement expiré renvoie l'état `expired` ;
- CA-3 (refus) : un webhook seul ne crée aucun entitlement ;
- CA-4 (isolation) : l'entitlement de O1 n'est jamais calculé pour O2 ;
- CA-5 : la migration ajoute les colonnes absorbées et renomme la table ;
- CA-6 : `niveauApplication` et `sourceAttribution` n'acceptent que les valeurs listées ;
- CA-7 : chaque combinaison `sourceAttribution` x `niveauApplication` (5 x 2) est enregistrable ;
- CA-8 : un entitlement pointant vers une `capaciteId` inexistante est refusé ;
- CA-9 (refus) : une écriture sans `entitlement.manage` renvoie 403 et ne modifie rien ;
- CA-10 (isolation) : un entitlement de O1 n'apparaît pas dans la lecture de O2.

Les tables sont vérifiées sur la base de test migrée à la tête (tests/conftest.py).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.billing import entitlements, service
from app.billing.models import Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.identity.models import Organization


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


async def _colonnes(table: str) -> set[str]:
    async with engine.connect() as conn:
        resultat = await conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table}
        )
        return {ligne[0] for ligne in resultat.fetchall()}


async def _table_existe(table: str) -> bool:
    async with engine.connect() as conn:
        resultat = await conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"), {"t": table}
        )
        return resultat.first() is not None


async def _nombre_entitlements() -> int:
    async with AsyncSessionLocal() as db:
        return len((await db.scalars(select(SubscriptionEntitlement.id))).all())


async def _organisation(db, nom: str) -> Organization:
    organisation = Organization(name=nom, slug=f"be024-{uuid.uuid4().hex[:12]}", status="active")
    db.add(organisation)
    await db.flush()
    return organisation


async def _abonnement(db, organization_id: uuid.UUID, plan_version_id: uuid.UUID | None = None) -> Subscription:
    """Abonnement minimal rattaché à un plan réel du catalogue (module zylo_liquid)."""
    await db.execute(text(
        'INSERT INTO module (id, code, name, version, "createdAt", "updatedAt") '
        "VALUES (:id, 'zylo_liquid', 'Zylo Liquid', '0.1.0', now(), now()) ON CONFLICT (code) DO NOTHING"
    ), {"id": uuid.uuid4()})
    plan = await service.get_or_create_plan(
        db, "zylo_liquid", f"be024-{uuid.uuid4().hex[:10]}", "Plan BE-024", 0, "XAF", 30
    )
    version = await service.ensure_initial_plan_version(db, plan)
    now = datetime.now(timezone.utc)
    subscription = Subscription(
        organizationId=organization_id, planId=plan.id,
        planVersionId=plan_version_id or version.id, status="active",
        startDate=now, endDate=now + timedelta(days=30),
    )
    db.add(subscription)
    await db.flush()
    return subscription


def _entitlement(organization_id, subscription_id, code: str, **champs) -> SubscriptionEntitlement:
    valeurs = dict(
        organizationId=organization_id, subscriptionId=subscription_id, moduleCode="zylo_liquid",
        entitlementCode=code, status="active", startsAt=datetime.now(timezone.utc),
        endsAt=None, sourceAttribution="offre", niveauApplication="organisation",
    )
    valeurs.update(champs)
    return SubscriptionEntitlement(**valeurs)


# --- CA-1 : entitlement calculé depuis la version de plan active ----------------------


@pytest.mark.asyncio
async def test_ca1_entitlement_calcule_depuis_la_version_de_plan_active():
    """CA-1 : après deux publications, l'abonnement ouvert sur la version active
    reçoit les codes de cette version seule, et `offreId` pointe cette version."""
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            'INSERT INTO module (id, code, name, version, "createdAt", "updatedAt") '
            "VALUES (:id, 'zylo_liquid', 'Zylo Liquid', '0.1.0', now(), now()) ON CONFLICT (code) DO NOTHING"
        ), {"id": uuid.uuid4()})
        code_plan = f"be024-ca1-{uuid.uuid4().hex[:10]}"
        plan = await service.get_or_create_plan(db, "zylo_liquid", code_plan, "Plan CA1", 0, "XAF", 30)
        await service.publish_plan_version(db, code_plan, 1000, "XAF", 30, ["ent.v1"])
        version_active = await service.publish_plan_version(db, code_plan, 2000, "XAF", 30, ["ent.v2"])
        organisation = await _organisation(db, "Org CA1")
        subscription = Subscription(
            organizationId=organisation.id, planId=plan.id, planVersionId=version_active.id, status="active",
            startDate=datetime.now(timezone.utc), endDate=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(subscription)
        await db.flush()
        await entitlements.attribuer_entitlements_offre(db, subscription)
        await db.commit()

        calcules = await entitlements.calculer_entitlements(db, organisation.id)
        assert [c.entitlementCode for c in calcules] == ["ent.v2"]
        assert calcules[0].offreId == version_active.id
        assert calcules[0].etat == "active"


# --- CA-2 : état expired ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_ca2_entitlement_expire_renvoie_etat_expired():
    """CA-2 : un entitlement actif dont `endsAt` est dépassé est calculé `expired`."""
    async with AsyncSessionLocal() as db:
        organisation = await _organisation(db, "Org CA2")
        subscription = await _abonnement(db, organisation.id)
        maintenant = datetime.now(timezone.utc)
        db.add(_entitlement(
            organisation.id, subscription.id, "ent.expire",
            startsAt=maintenant - timedelta(days=60), endsAt=maintenant - timedelta(days=1),
        ))
        await db.commit()

        calcules = {c.entitlementCode: c for c in await entitlements.calculer_entitlements(db, organisation.id)}
        assert calcules["ent.expire"].etat == "expired"


# --- CA-3 : un webhook seul ne crée aucun entitlement ----------------------------------


@pytest.mark.asyncio
async def test_ca3_webhook_seul_ne_cree_aucun_entitlement(client, monkeypatch):
    """CA-3 : un événement de webhook authentifié est enregistré sans créer d'entitlement."""
    monkeypatch.setenv("FLUTTERWAVE_WEBHOOK_SECRET", "secret-be024-webhook")
    avant = await _nombre_entitlements()

    reponse = await client.post(
        "/api/v1/billing/webhooks/flutterwave",
        json={"id": f"evt-{uuid.uuid4().hex}", "event": "charge.completed",
              "data": {"id": 42, "status": "successful"}},
        headers={"verif-hash": "secret-be024-webhook"},
    )

    assert reponse.status_code < 300, reponse.text
    assert await _nombre_entitlements() == avant


# --- CA-4 : isolation du calcul entre organisations ------------------------------------


@pytest.mark.asyncio
async def test_ca4_entitlement_de_o1_jamais_calcule_pour_o2():
    """CA-4 : les entitlements de O1 ne sont jamais renvoyés au calcul de O2."""
    async with AsyncSessionLocal() as db:
        o1 = await _organisation(db, "Org O1")
        o2 = await _organisation(db, "Org O2")
        sub_o1 = await _abonnement(db, o1.id)
        db.add(_entitlement(o1.id, sub_o1.id, "ent.isole.o1"))
        await db.commit()

        assert [c.entitlementCode for c in await entitlements.calculer_entitlements(db, o1.id)] == ["ent.isole.o1"]
        assert await entitlements.calculer_entitlements(db, o2.id) == []


# --- CA-5 : migration, colonnes absorbées et table renommée ----------------------------


@pytest.mark.asyncio
async def test_ca5_migration_ajoute_les_colonnes_et_renomme_la_table():
    """CA-5 : la table est `subscription_entitlement` avec les colonnes absorbées de BE-261."""
    assert await _table_existe("subscription_entitlement")
    assert not await _table_existe("subscriptionEntitlement")
    colonnes = await _colonnes("subscription_entitlement")
    attendues = {
        "organizationId", "subscriptionId", "moduleCode", "entitlementCode", "status",
        "startsAt", "endsAt", "offreId", "capaciteId", "quotaLimite",
        "niveauApplication", "sourceAttribution",
    }
    assert attendues <= colonnes
    assert await _table_existe("capability")


# --- CA-6 : valeurs énumérées refusées hors liste --------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("champ, valeur", [("niveauApplication", "equipe"), ("sourceAttribution", "cadeau")])
async def test_ca6_valeur_hors_liste_refusee(champ: str, valeur: str):
    """CA-6 : `niveauApplication` et `sourceAttribution` n'acceptent que les valeurs listées."""
    async with AsyncSessionLocal() as db:
        organisation = await _organisation(db, "Org CA6")
        subscription = await _abonnement(db, organisation.id)
        db.add(_entitlement(organisation.id, subscription.id, f"ent.ca6.{champ}", **{champ: valeur}))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


# --- CA-7 : couverture 5 x 2 -----------------------------------------------------------


@pytest.mark.asyncio
async def test_ca7_chaque_combinaison_source_niveau_est_enregistrable():
    """CA-7 : les 5 sources x 2 niveaux sont tous enregistrables (10 lignes)."""
    async with AsyncSessionLocal() as db:
        organisation = await _organisation(db, "Org CA7")
        subscription = await _abonnement(db, organisation.id)
        combinaisons = [
            (source, niveau)
            for source in entitlements.SOURCES_ATTRIBUTION
            for niveau in entitlements.NIVEAUX_APPLICATION
        ]
        assert len(combinaisons) == 10
        for source, niveau in combinaisons:
            db.add(_entitlement(
                organisation.id, subscription.id, f"ent.ca7.{source}.{niveau}",
                sourceAttribution=source, niveauApplication=niveau,
            ))
        await db.commit()

        enregistres = (await db.scalars(select(SubscriptionEntitlement).where(
            SubscriptionEntitlement.subscriptionId == subscription.id
        ))).all()
        assert {(e.sourceAttribution, e.niveauApplication) for e in enregistres} == set(combinaisons)


# --- CA-8 : capaciteId inexistante refusée ---------------------------------------------


@pytest.mark.asyncio
async def test_ca8_capacite_inexistante_refusee():
    """CA-8 : un entitlement vers une `capaciteId` absente du registre est refusé."""
    async with AsyncSessionLocal() as db:
        organisation = await _organisation(db, "Org CA8")
        subscription = await _abonnement(db, organisation.id)
        db.add(_entitlement(organisation.id, subscription.id, "ent.ca8", capaciteId=uuid.uuid4()))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


# --- CA-9 : écriture sans entitlement.manage refusée -----------------------------------


@pytest.mark.asyncio
async def test_ca9_ecriture_sans_entitlement_manage_renvoie_403():
    """CA-9 : un acteur sans `entitlement.manage` reçoit 403 et aucune ligne n'est écrite."""
    async with AsyncSessionLocal() as db:
        organisation = await _organisation(db, "Org CA9")
        subscription = await _abonnement(db, organisation.id)
        await db.commit()
    avant = await _nombre_entitlements()

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await entitlements.enregistrer_entitlement(
                db, actor_user_id=uuid.uuid4(), organization_id=organisation.id,
                subscription_id=subscription.id, module_code="zylo_liquid",
                entitlement_code="ent.ca9", starts_at=datetime.now(timezone.utc),
            )
    assert erreur.value.status_code == 403
    assert await _nombre_entitlements() == avant


# --- CA-10 : isolation de la lecture ----------------------------------------------------


@pytest.mark.asyncio
async def test_ca10_entitlement_de_a_absent_de_la_lecture_de_b():
    """CA-10 : deux organisations ayant chacune un entitlement ne voient que le leur."""
    async with AsyncSessionLocal() as db:
        org_a = await _organisation(db, "Org A")
        org_b = await _organisation(db, "Org B")
        sub_a = await _abonnement(db, org_a.id)
        sub_b = await _abonnement(db, org_b.id)
        ligne_a = _entitlement(org_a.id, sub_a.id, "ent.lecture")
        ligne_b = _entitlement(org_b.id, sub_b.id, "ent.lecture")
        db.add_all([ligne_a, ligne_b])
        await db.commit()

        lecture_b = await entitlements.calculer_entitlements(db, org_b.id)
        assert [c.entitlementCode for c in lecture_b] == ["ent.lecture"]
        assert all(c.organizationId == org_b.id for c in lecture_b)
        assert ligne_a.id not in {c.id for c in lecture_b}
