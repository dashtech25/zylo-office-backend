"""BE-193 : inbox consommateur et dispatcher.

Tests écrits d'après la définition `### BE-193` de
implementation-backend/tasks-donnees-api-contrats.md, avant le code.

Écarts consignés (recommandation appliquée, QE-API-02 et QE-API-16 / QE-API-22) :
- l'attente d'un hors-ordre utilise le statut `retry` (la table n'a que processed, retry, quarantine) ;
- « tenant connu » signifie : une organisation existe pour ce `tenantId` (aucune table de scope
  consommateur par tenant n'existe, voir outbox.md) ;
- `event_inbox.eventId` n'a pas de clé étrangère vers l'outbox : l'inbox reçoit aussi des événements
  qui ne sont pas passés par cette outbox, et une quarantaine de tenant inconnu doit rester possible.

Couverture :
- CA-1 : un couple (`subscriber`, `eventId`) n'est traité qu'une fois, et la contrainte d'unicité existe ;
- CA-2 : un événement d'un tenant inconnu est mis en quarantaine, sans appel du handler ;
- CA-3 : un événement hors ordre pour un agrégat ordonné est mis en attente (`retry`) ;
- CA-4 : après MAX_TENTATIVES échecs, l'événement passe en quarantaine ; il n'est plus retenté ;
- CA-5 : un événement de schéma incompatible est mis en quarantaine ;
- CA-6 : après un crash suivant la distribution, le dispatcher republie l'événement (au moins une fois),
  et l'inbox n'enregistre qu'un seul traitement.

Chaque test crée ses propres identifiants (événement, agrégat, organisation).
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.evenements.dispatcher import distribuer_lot
from app.evenements.inbox import (
    ISSUE_DOUBLON,
    MAX_TENTATIVES,
    STATUT_PROCESSED,
    STATUT_QUARANTINE,
    STATUT_RETRY,
    EvenementRecu,
    recevoir_evenement,
)
from app.evenements.models import EventInbox
from app.evenements.outbox import enregistrer_evenement_producteur

VERSIONS_ACCEPTEES = frozenset({1})
ABONNE = "abonne-be193"


def _evenement(tenant: uuid.UUID, *, aggregate_version: int | None = None, aggregate_id: str | None = None, schema: int = 1) -> EvenementRecu:
    """Événement reçu, construit directement (l'inbox ne relit pas l'outbox pour ces tests)."""
    return EvenementRecu(
        eventId=uuid.uuid4(),
        eventType="Test.BE193",
        schemaVersion=schema,
        tenantId=tenant,
        aggregateType="Test.Agregat",
        aggregateId=aggregate_id or f"agregat-{uuid.uuid4().hex}",
        aggregateVersion=aggregate_version,
        payload={"valeur": uuid.uuid4().hex},
    )


def _enregistreur(appels: list, echec: bool = False):
    """Handler de test : note chaque appel ; lève une erreur si `echec` est vrai."""

    async def handler(evenement: EvenementRecu) -> None:
        appels.append(evenement.eventId)
        if echec:
            raise RuntimeError("échec de test")

    return handler


async def _recevoir(
    evenement: EvenementRecu,
    *,
    abonne: str = ABONNE,
    ordonne: bool = False,
    handler=None,
    versions: frozenset[int] = VERSIONS_ACCEPTEES,
) -> str:
    """Reçoit un événement dans une transaction committée ; renvoie l'issue."""
    async with AsyncSessionLocal() as db:
        issue = await recevoir_evenement(
            db,
            abonne=abonne,
            evenement=evenement,
            versions_acceptees=versions,
            ordonne=ordonne,
            handler=handler or _enregistreur([]),
        )
        await db.commit()
        return issue


async def _ligne(abonne: str, event_id: uuid.UUID) -> EventInbox | None:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(EventInbox).where(EventInbox.subscriber == abonne, EventInbox.eventId == event_id))
        ).scalar_one_or_none()


async def _nombre_lignes(abonne: str, event_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count()).select_from(EventInbox).where(EventInbox.subscriber == abonne, EventInbox.eventId == event_id)
            )
        ).scalar_one()


def _donnees_producteur(tenant: uuid.UUID, *, aggregate_id: str, aggregate_version: int) -> dict:
    """Enveloppe brute d'un producteur (BE-192) pour écrire une ligne d'outbox."""
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": f"Test.BE193.{uuid.uuid4().hex}",
        "schemaVersion": 1,
        "occurredAt": "2026-11-05T10:00:00+00:00",
        "tenantId": str(tenant),
        "scope": {"type": "organization", "id": str(tenant)},
        "actor": {"userId": str(uuid.uuid4())},
        "subject": {"type": "Test", "id": str(uuid.uuid4())},
        "dataClassification": "internal",
        "correlationId": f"corr-{uuid.uuid4().hex}",
        "causationId": None,
        "payload": {"valeur": uuid.uuid4().hex},
        "aggregateType": "Test.Agregat",
        "aggregateId": aggregate_id,
        "aggregateVersion": aggregate_version,
        "producer": "test.be193",
    }


async def _publier_producteur(tenant: uuid.UUID, *, aggregate_id: str, aggregate_version: int) -> str:
    """Écrit et committe un événement dans l'outbox du tenant ; renvoie son eventId."""
    donnees = _donnees_producteur(tenant, aggregate_id=aggregate_id, aggregate_version=aggregate_version)
    async with AsyncSessionLocal() as db:
        await enregistrer_evenement_producteur(db, donnees, emetteur_tenant=tenant, tenant_agregat=tenant)
        await db.commit()
    return donnees["eventId"]


# ---------------------------------------------------------------------------
# CA-1 : un couple (subscriber, eventId) n'est traité qu'une fois
# ---------------------------------------------------------------------------


async def test_be193_ca1_couple_traite_une_seule_fois(organization: dict):
    tenant = uuid.UUID(organization["id"])
    evenement = _evenement(tenant)
    appels: list = []

    premier = await _recevoir(evenement, handler=_enregistreur(appels))
    second = await _recevoir(evenement, handler=_enregistreur(appels))

    assert premier == STATUT_PROCESSED
    assert second == ISSUE_DOUBLON
    assert len(appels) == 1

    # Un autre consommateur reçoit le même événement : le couple est différent.
    autre = await _recevoir(evenement, abonne="autre-be193", handler=_enregistreur(appels))
    assert autre == STATUT_PROCESSED
    assert len(appels) == 2


async def test_be193_ca1_contrainte_unicite_subscriber_eventid(organization: dict):
    tenant = uuid.UUID(organization["id"])
    evenement = _evenement(tenant)
    async with AsyncSessionLocal() as db:
        db.add(EventInbox(subscriber=ABONNE, eventId=evenement.eventId, tenantId=tenant, eventType="Test.BE193", schemaVersion=1, status=STATUT_PROCESSED, attempts=0))
        await db.commit()
    async with AsyncSessionLocal() as db:
        db.add(EventInbox(subscriber=ABONNE, eventId=evenement.eventId, tenantId=tenant, eventType="Test.BE193", schemaVersion=1, status=STATUT_PROCESSED, attempts=0))
        with pytest.raises(IntegrityError):
            await db.commit()


# ---------------------------------------------------------------------------
# CA-2 : tenant inconnu du consommateur, mise en quarantaine
# ---------------------------------------------------------------------------


async def test_be193_ca2_tenant_inconnu_en_quarantaine(organization: dict):
    connu = uuid.UUID(organization["id"])
    inconnu = uuid.uuid4()
    appels: list = []

    issue_inconnu = await _recevoir(_evenement(inconnu), handler=_enregistreur(appels))
    issue_connu = await _recevoir(_evenement(connu), handler=_enregistreur(appels))

    assert issue_inconnu == STATUT_QUARANTINE
    assert issue_connu == STATUT_PROCESSED
    assert len(appels) == 1, "le handler ne doit jamais être appelé pour un tenant inconnu"


# ---------------------------------------------------------------------------
# CA-3 : hors ordre pour un agrégat ordonné, mis en attente
# ---------------------------------------------------------------------------


async def test_be193_ca3_hors_ordre_mis_en_attente(organization: dict):
    tenant = uuid.UUID(organization["id"])
    agregat = f"agregat-{uuid.uuid4().hex}"
    v1 = _evenement(tenant, aggregate_version=1, aggregate_id=agregat)
    v2 = _evenement(tenant, aggregate_version=2, aggregate_id=agregat)
    appels: list = []

    assert await _recevoir(v2, ordonne=True, handler=_enregistreur(appels)) == STATUT_RETRY
    assert appels == [], "un événement hors ordre ne doit pas être appliqué"

    assert await _recevoir(v1, ordonne=True, handler=_enregistreur(appels)) == STATUT_PROCESSED
    assert await _recevoir(v2, ordonne=True, handler=_enregistreur(appels)) == STATUT_PROCESSED
    assert appels == [v1.eventId, v2.eventId]


# ---------------------------------------------------------------------------
# CA-4 : reprise bornée, puis quarantaine
# ---------------------------------------------------------------------------


async def test_be193_ca4_reprise_bornee_puis_quarantaine(organization: dict):
    tenant = uuid.UUID(organization["id"])
    evenement = _evenement(tenant)
    appels: list = []

    issues = [await _recevoir(evenement, handler=_enregistreur(appels, echec=True)) for _ in range(MAX_TENTATIVES)]

    assert MAX_TENTATIVES == 5, "valeur de QE-API-16 (5 tentatives)"
    assert issues[:-1] == [STATUT_RETRY] * (MAX_TENTATIVES - 1)
    assert issues[-1] == STATUT_QUARANTINE
    assert len(appels) == MAX_TENTATIVES

    # Une fois en quarantaine, l'événement n'est plus retenté.
    assert await _recevoir(evenement, handler=_enregistreur(appels)) == ISSUE_DOUBLON
    assert len(appels) == MAX_TENTATIVES

    ligne = await _ligne(ABONNE, evenement.eventId)
    assert ligne is not None
    assert ligne.status == STATUT_QUARANTINE
    assert ligne.attempts == MAX_TENTATIVES


# ---------------------------------------------------------------------------
# CA-5 : schéma incompatible, mise en quarantaine
# ---------------------------------------------------------------------------


async def test_be193_ca5_schema_incompatible_en_quarantaine(organization: dict):
    tenant = uuid.UUID(organization["id"])
    appels: list = []

    issue = await _recevoir(_evenement(tenant, schema=2), versions=VERSIONS_ACCEPTEES, handler=_enregistreur(appels))

    assert issue == STATUT_QUARANTINE
    assert appels == []


# ---------------------------------------------------------------------------
# CA-6 : crash après distribution, le dispatcher republie
# ---------------------------------------------------------------------------


async def test_be193_ca6_crash_apres_distribution_republie(organization: dict):
    tenant = uuid.UUID(organization["id"])
    event_id = uuid.UUID(await _publier_producteur(tenant, aggregate_id=f"agregat-{uuid.uuid4().hex}", aggregate_version=1))
    livraisons: list = []

    # Premier passage : l'événement est distribué (effet hors base, par ex. un envoi), puis le
    # processus tombe avant le commit : la session est annulée.
    async with AsyncSessionLocal() as db:
        await distribuer_lot(
            db, abonne=ABONNE, tenant_id=tenant, versions_acceptees=VERSIONS_ACCEPTEES, ordonne=False,
            handler=_enregistreur(livraisons),
        )
        await db.rollback()
    assert len(livraisons) == 1
    assert await _nombre_lignes(ABONNE, event_id) == 0

    # Second passage : le dispatcher republie, puis committe.
    async with AsyncSessionLocal() as db:
        bilan = await distribuer_lot(
            db, abonne=ABONNE, tenant_id=tenant, versions_acceptees=VERSIONS_ACCEPTEES, ordonne=False,
            handler=_enregistreur(livraisons),
        )
        await db.commit()

    assert len(livraisons) >= 2, "au moins une fois : l'événement est republié après le crash"
    assert bilan.traites == 1
    ligne = await _ligne(ABONNE, event_id)
    assert ligne is not None and ligne.status == STATUT_PROCESSED
    assert await _nombre_lignes(ABONNE, event_id) == 1


async def test_be193_dispatcher_reprend_les_hors_ordre(organization: dict):
    """Le dispatcher remet en attente un hors ordre, puis le traite quand son prédécesseur est passé."""
    tenant = uuid.UUID(organization["id"])
    agregat = f"agregat-{uuid.uuid4().hex}"
    # Écriture dans l'ordre inverse : la version 2 est committée avant la version 1.
    id_v2 = uuid.UUID(await _publier_producteur(tenant, aggregate_id=agregat, aggregate_version=2))
    id_v1 = uuid.UUID(await _publier_producteur(tenant, aggregate_id=agregat, aggregate_version=1))
    livraisons: list = []

    async with AsyncSessionLocal() as db:
        premier = await distribuer_lot(
            db, abonne=ABONNE, tenant_id=tenant, versions_acceptees=VERSIONS_ACCEPTEES, ordonne=True,
            handler=_enregistreur(livraisons),
        )
        await db.commit()
    assert premier.traites == 1 and premier.en_attente == 1
    assert (await _ligne(ABONNE, id_v2)).status == STATUT_RETRY
    assert (await _ligne(ABONNE, id_v1)).status == STATUT_PROCESSED

    async with AsyncSessionLocal() as db:
        second = await distribuer_lot(
            db, abonne=ABONNE, tenant_id=tenant, versions_acceptees=VERSIONS_ACCEPTEES, ordonne=True,
            handler=_enregistreur(livraisons),
        )
        await db.commit()
    assert second.traites == 1
    assert (await _ligne(ABONNE, id_v2)).status == STATUT_PROCESSED
    assert livraisons == [id_v1, id_v2]
