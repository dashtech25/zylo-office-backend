"""BE-059 : périodes, expiration et effet d'accès des entitlements.

Intention : prouver les critères d'acceptation de BE-059
(implementation-backend/tasks-modules-droits.md, section BE-059) :
- CA-1 : un entitlement `active` dont `endsAt` est dépassé passe à `expired` à l'exécution
  de la tâche ; une seconde exécution ne change rien (idempotence) ;
- CA-2 : un entitlement `expired` donne `deny / ENTITLEMENT_REQUIRED` au moteur (BE-053) ;
- CA-3 : un entitlement sans fin (`endsAt` absent) n'expire pas et n'reçoit pas de date inventée ;
- CA-4 : un entitlement en réconciliation ou bloqué n'est jamais passé à un état d'accès
  par la tâche.

Écart connu avec la définition (voir QE-BE059 dans le rapport de tâche) : la colonne
d'état existante est `subscription_entitlement.status` (valeurs `active`, `inactive`,
`expired`, `blocked`), pas `state`, et `reconciliation_required` n'existe pas encore dans
les contraintes. Les tests utilisent la colonne existante et ne créent aucun doublon.

Les tables sont vérifiées sur la base de test migrée à la tête (tests/conftest.py).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.billing import service
from app.billing.entitlements import expirer_entitlements_echus
from app.billing.models import Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import Organization
from app.modules_registry.service import get_module_entitlement_access
from app.rbac.acces_effectif import ENTITLEMENT_REQUIS, FaitsAcces, evaluer_acces


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


MAINTENANT = datetime.now(timezone.utc)
DEBUT = MAINTENANT - timedelta(days=60)
FIN_DEPASSEE = MAINTENANT - timedelta(days=1)
FIN_FUTURE = MAINTENANT + timedelta(days=1)


async def _organisation(db, nom: str) -> Organization:
    organisation = Organization(name=nom, slug=f"be059-{uuid.uuid4().hex[:12]}", status="active")
    db.add(organisation)
    await db.flush()
    return organisation


async def _abonnement(db, organization_id: uuid.UUID) -> Subscription:
    """Abonnement minimal rattaché à un plan réel du catalogue (module zylo_liquid)."""
    await db.execute(text(
        'INSERT INTO module (id, code, name, version, "createdAt", "updatedAt") '
        "VALUES (:id, 'zylo_liquid', 'Zylo Liquid', '0.1.0', now(), now()) ON CONFLICT (code) DO NOTHING"
    ), {"id": uuid.uuid4()})
    plan = await service.get_or_create_plan(
        db, "zylo_liquid", f"be059-{uuid.uuid4().hex[:10]}", "Plan BE-059", 0, "XAF", 30
    )
    version = await service.ensure_initial_plan_version(db, plan)
    subscription = Subscription(
        organizationId=organization_id, planId=plan.id, planVersionId=version.id, status="active",
        startDate=DEBUT, endDate=FIN_FUTURE,
    )
    db.add(subscription)
    await db.flush()
    return subscription


def _entitlement(organization_id, subscription_id, code: str, **champs) -> SubscriptionEntitlement:
    valeurs = dict(
        organizationId=organization_id, subscriptionId=subscription_id, moduleCode="zylo_liquid",
        entitlementCode=code, status="active", startsAt=DEBUT, endsAt=FIN_FUTURE,
        sourceAttribution="offre", niveauApplication="organisation", stateVersion=1,
    )
    valeurs.update(champs)
    return SubscriptionEntitlement(**valeurs)


async def _etat(entitlement_id: uuid.UUID) -> tuple[str, int, datetime | None]:
    """Relit `status`, `stateVersion` et `endsAt` directement en base."""
    async with AsyncSessionLocal() as db:
        ligne = await db.get(SubscriptionEntitlement, entitlement_id)
        await db.refresh(ligne)
        return ligne.status, ligne.stateVersion, ligne.endsAt


# --- CA-1 : expiration à l'échéance, idempotence -----------------------------------------


@pytest.mark.asyncio
async def test_ca1_entitlement_echu_passe_a_expired_et_version_incrementee():
    """CA-1 : un `active` dont `endsAt` est dépassé devient `expired` et `stateVersion` avance
    de 1 ; un `active` dont `endsAt` est futur reste inchangé."""
    async with AsyncSessionLocal() as db:
        organisation = await _organisation(db, "BE-059 CA-1")
        abonnement = await _abonnement(db, organisation.id)
        echu = _entitlement(organisation.id, abonnement.id, "be059.echu", endsAt=FIN_DEPASSEE, stateVersion=3)
        futur = _entitlement(organisation.id, abonnement.id, "be059.futur", endsAt=FIN_FUTURE)
        db.add_all([echu, futur])
        await db.commit()
        id_echu, id_futur = echu.id, futur.id
        organisation_id = organisation.id

    async with AsyncSessionLocal() as db:
        nombre = await expirer_entitlements_echus(db, now=MAINTENANT, organization_id=organisation_id)
        await db.commit()

    assert nombre == 1
    assert await _etat(id_echu) == ("expired", 4, FIN_DEPASSEE)
    assert await _etat(id_futur) == ("active", 1, FIN_FUTURE)


@pytest.mark.asyncio
async def test_ca1_seconde_execution_ne_change_rien():
    """CA-1 (idempotence) : une seconde exécution ne modifie aucune ligne et ne touche pas
    `stateVersion`."""
    async with AsyncSessionLocal() as db:
        organisation = await _organisation(db, "BE-059 CA-1 idempotence")
        abonnement = await _abonnement(db, organisation.id)
        echu = _entitlement(organisation.id, abonnement.id, "be059.rejeu", endsAt=FIN_DEPASSEE)
        db.add(echu)
        await db.commit()
        id_echu, organisation_id = echu.id, organisation.id

    async with AsyncSessionLocal() as db:
        await expirer_entitlements_echus(db, now=MAINTENANT, organization_id=organisation_id)
        await db.commit()
    apres_premiere = await _etat(id_echu)

    async with AsyncSessionLocal() as db:
        nombre = await expirer_entitlements_echus(db, now=MAINTENANT, organization_id=organisation_id)
        await db.commit()

    assert nombre == 0
    assert await _etat(id_echu) == apres_premiere
    assert apres_premiere[0] == "expired"


# --- CA-2 : effet d'accès ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_ca2_entitlement_expire_donne_entitlement_required_au_moteur():
    """CA-2 : après expiration, la projection d'accès du module vaut `expired` (refus), et le
    moteur `evaluer_acces` refuse avec `ENTITLEMENT_REQUIRED` quand l'entitlement n'est pas valide."""
    async with AsyncSessionLocal() as db:
        organisation = await _organisation(db, "BE-059 CA-2")
        abonnement = await _abonnement(db, organisation.id)
        db.add(_entitlement(organisation.id, abonnement.id, "be059.acces", endsAt=FIN_DEPASSEE))
        await db.commit()
        organisation_id = organisation.id

    async with AsyncSessionLocal() as db:
        await expirer_entitlements_echus(db, now=MAINTENANT, organization_id=organisation_id)
        await db.commit()

    async with AsyncSessionLocal() as db:
        etat, valide = await get_module_entitlement_access(db, organisation_id, "zylo_liquid")

    assert (etat, valide) == ("expired", False)
    evaluation = evaluer_acces(FaitsAcces(
        membre_actif=True, permission_accordee=True, module_actif=True, reconciliation_pendante=False,
        capacite_exige_entitlement=True, entitlement_valide=valide, quota_conforme=None,
        action_mutante=False, politique_declaree=True,
    ))
    assert evaluation.decision == "deny"
    assert evaluation.motif == ENTITLEMENT_REQUIS


# --- CA-3 : pas de fin, pas de date inventée ---------------------------------------------


@pytest.mark.asyncio
async def test_ca3_entitlement_sans_fin_n_expire_pas_et_reste_sans_date():
    """CA-3 : `endsAt` absent reste absent, `status` reste `active`, `stateVersion` ne bouge pas."""
    async with AsyncSessionLocal() as db:
        organisation = await _organisation(db, "BE-059 CA-3")
        abonnement = await _abonnement(db, organisation.id)
        sans_fin = _entitlement(organisation.id, abonnement.id, "be059.sans.fin", endsAt=None)
        db.add(sans_fin)
        await db.commit()
        id_sans_fin, organisation_id = sans_fin.id, organisation.id

    async with AsyncSessionLocal() as db:
        nombre = await expirer_entitlements_echus(db, now=MAINTENANT, organization_id=organisation_id)
        await db.commit()

    assert nombre == 0
    assert await _etat(id_sans_fin) == ("active", 1, None)


# --- CA-4 : la tâche ne fait jamais passer un état de réconciliation ou bloqué à l'accès ----


@pytest.mark.asyncio
async def test_ca4_etats_non_actifs_ne_sont_jamais_modifies_par_la_tache():
    """CA-4 : un entitlement `blocked` ou `inactive` dont la date est dépassée n'est ni passé à
    `active` ni à `expired` par la tâche : son état stocké prime (voir calculer_entitlements)."""
    async with AsyncSessionLocal() as db:
        organisation = await _organisation(db, "BE-059 CA-4")
        abonnement = await _abonnement(db, organisation.id)
        bloque = _entitlement(organisation.id, abonnement.id, "be059.bloque", status="blocked", endsAt=FIN_DEPASSEE)
        inactif = _entitlement(organisation.id, abonnement.id, "be059.inactif", status="inactive", endsAt=FIN_DEPASSEE)
        db.add_all([bloque, inactif])
        await db.commit()
        id_bloque, id_inactif, organisation_id = bloque.id, inactif.id, organisation.id

    async with AsyncSessionLocal() as db:
        nombre = await expirer_entitlements_echus(db, now=MAINTENANT, organization_id=organisation_id)
        await db.commit()

    assert nombre == 0
    assert await _etat(id_bloque) == ("blocked", 1, FIN_DEPASSEE)
    assert await _etat(id_inactif) == ("inactive", 1, FIN_DEPASSEE)


@pytest.mark.asyncio
async def test_ca4_la_tache_n_ecrit_jamais_un_statut_d_acces_autre_que_expired():
    """CA-4 : sur l'ensemble des lignes d'une organisation, seule la valeur `expired` peut
    apparaître après exécution ; aucune ligne `active` n'est créée ni réactivée."""
    async with AsyncSessionLocal() as db:
        organisation = await _organisation(db, "BE-059 CA-4 ensemble")
        abonnement = await _abonnement(db, organisation.id)
        db.add_all([
            _entitlement(organisation.id, abonnement.id, "be059.ens.echu", endsAt=FIN_DEPASSEE),
            _entitlement(organisation.id, abonnement.id, "be059.ens.bloque", status="blocked", endsAt=FIN_DEPASSEE),
        ])
        await db.commit()
        organisation_id = organisation.id

    async with AsyncSessionLocal() as db:
        await expirer_entitlements_echus(db, now=MAINTENANT, organization_id=organisation_id)
        await db.commit()

    async with AsyncSessionLocal() as db:
        statuts = dict((await db.execute(
            select(SubscriptionEntitlement.entitlementCode, SubscriptionEntitlement.status)
            .where(SubscriptionEntitlement.organizationId == organisation_id)
        )).all())

    assert statuts == {"be059.ens.echu": "expired", "be059.ens.bloque": "blocked"}
