"""BE-258 CA-2 : le replay de la file de lettres mortes ne produit pas de doublon.

Tests écrits d'après la définition `### BE-258` de implementation-backend/tasks-exploitation-architecture.md,
avant le code. Le replay est celui de BE-235 (`app.evenements.dlq.rejouer_dead_letter`) : il repasse par la
trace de consommation (couple consommateur, eventId) et par la tentative bornée.

Couverture :
- un événement passé en lettre morte puis rejoué une fois produit un seul effet ; un second replay de la même
  entrée est refusé, et une relance du lot ne produit aucun effet ni aucune nouvelle entrée DLQ ;
- un replay d'une entrée dont l'événement a déjà été consommé normalement ne rappelle pas le handler.

Données : chaque test crée son tenant, son événement et son consommateur (identifiants uniques).
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.evenements.consumer import CONSOMMATEURS, consommer_lot
from app.evenements.dlq import lister_dead_letters, rejouer_dead_letter
from app.evenements.models import DeadLetter
from app.evenements.outbox import enregistrer_evenement
from app.identity.models import Organization


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Le pool asyncpg est vidé avant et après chaque test (chaque test a sa boucle asyncio)."""
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def maximum_tentatives_be258(monkeypatch):
    """Deux tentatives par consommation (QE-EXP-08 : valeur explicite, jamais codée dans le module)."""
    monkeypatch.setattr(settings, "EVENTS_CONSUMER_MAX_TENTATIVES", 2)


def _enveloppe(tenant: uuid.UUID) -> dict:
    """Enveloppe brute conforme à BE-150, au même format que les tests de BE-235."""
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": f"Test.BE258.{uuid.uuid4().hex}",
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
    }


async def _organisation() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        org = Organization(name="Tenant BE258", slug=f"be258-{uuid.uuid4().hex}")
        db.add(org)
        await db.commit()
        return org.id


async def _publier(tenant: uuid.UUID) -> str:
    """Écrit un événement committé dans l'outbox du tenant ; renvoie son eventId."""
    donnees = _enveloppe(tenant)
    async with AsyncSessionLocal() as db:
        await enregistrer_evenement(db, donnees, emetteur_tenant=tenant)
        await db.commit()
    return donnees["eventId"]


async def _compter_dead_letters(event_id: str, consommateur: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count(DeadLetter.id)).where(
                    DeadLetter.eventId == uuid.UUID(event_id), DeadLetter.consommateur == consommateur
                )
            )
        ).scalar_one()


async def test_be258_ca2_replay_unique_ne_produit_pas_de_second_effet(monkeypatch):
    """CA-2 : après un échec définitif puis un replay réussi, le replay refait ne produit aucun effet."""
    tenant = await _organisation()
    event_id = await _publier(tenant)
    consommateur = f"be258-replay-{uuid.uuid4().hex}"
    etat = {"panne": True}
    effets: list[str] = []

    async def handler(evenement) -> None:
        if etat["panne"]:
            raise RuntimeError("panne simulée de la dépendance")
        effets.append(str(evenement.eventId))

    monkeypatch.setitem(CONSOMMATEURS, consommateur, handler)

    async with AsyncSessionLocal() as db:
        bilan = await consommer_lot(db, consommateur, tenant, handler)
        await db.commit()
    assert (bilan.traites, bilan.dlq) == (0, 1)
    assert effets == []

    async with AsyncSessionLocal() as db:
        entree_id = (await lister_dead_letters(db, tenant))[0].id

    etat["panne"] = False
    async with AsyncSessionLocal() as db:
        ligne = await rejouer_dead_letter(db, entree_id, tenant)
        await db.commit()
    assert ligne.statut == "rejoue"
    assert effets == [event_id]

    # Second replay de la même entrée : refusé sans appel du handler.
    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await rejouer_dead_letter(db, entree_id, tenant)
    assert erreur.value.code == "dead_letter_deja_rejouee"

    # Relance du lot : l'événement n'est ni retraité, ni renvoyé en lettre morte une seconde fois.
    async with AsyncSessionLocal() as db:
        bilan = await consommer_lot(db, consommateur, tenant, handler)
        await db.commit()
    assert (bilan.traites, bilan.doublons, bilan.dlq) == (0, 0, 0)
    assert effets == [event_id]
    assert await _compter_dead_letters(event_id, consommateur) == 1


async def test_be258_ca2_replay_apres_consommation_normale_ne_rappelle_pas_le_handler(monkeypatch):
    """CA-2 : une entrée DLQ dont l'événement a déjà été consommé est rejouée sans second effet."""
    tenant = await _organisation()
    event_id = await _publier(tenant)
    consommateur = f"be258-doublon-{uuid.uuid4().hex}"
    effets: list[str] = []

    async def handler(evenement) -> None:
        effets.append(str(evenement.eventId))

    monkeypatch.setitem(CONSOMMATEURS, consommateur, handler)

    async with AsyncSessionLocal() as db:
        await consommer_lot(db, consommateur, tenant, handler)
        await db.commit()
    assert effets == [event_id]

    # Entrée de lettre morte ajoutée après coup pour le même couple (consommateur, événement).
    async with AsyncSessionLocal() as db:
        db.add(
            DeadLetter(
                eventId=uuid.UUID(event_id),
                consommateur=consommateur,
                motif="echec de test BE-258",
                tentatives=2,
                tenantId=tenant,
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        entree_id = (await lister_dead_letters(db, tenant))[0].id

    async with AsyncSessionLocal() as db:
        ligne = await rejouer_dead_letter(db, entree_id, tenant)
        await db.commit()
    assert ligne.statut == "rejoue"
    assert ligne.rejoueAt is not None
    assert effets == [event_id], "le handler n'est pas rappelé : la trace de consommation fait foi"
