"""BE-166 : publication par outbox et consommation idempotente.

Tests écrits d'après la définition `### BE-166` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : l'événement n'est visible qu'après le commit de la transaction métier ;
  un échec injecté avant commit ne laisse aucune ligne d'outbox ;
- CA-2 : une livraison répétée au même consommateur ne produit qu'un effet, et le
  rejeu est consigné `REPLAY_DUPLICATE` ;
- CA-3 : publication sans identité émetteur refusée `403` `PERMISSION_DENIED`, rien écrit ;
- CA-4 : un consommateur du tenant A ne reçoit jamais un événement du tenant B ;
  un événement dont le tenant ne correspond pas à l'identité est refusé `TENANT_MISMATCH`.

Chaque test utilise des identifiants d'événement et de consommateur uniques.
"""

import logging
import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.evenements.models import ConsommationEvenement, OutboxEvenement
from app.evenements.outbox import consommer_evenement, distribuer_pour_consommateur, enregistrer_evenement, lire_evenements_pour_tenant
from app.identity.models import Organization


def _enveloppe(tenant: uuid.UUID, **surcharges) -> dict:
    """Enveloppe brute conforme à BE-150 ; `surcharges` remplace un champ."""
    brute = {
        "eventId": str(uuid.uuid4()),
        "eventType": f"Test.BE166.{uuid.uuid4().hex}",
        "schemaVersion": 1,
        "occurredAt": "2026-11-04T10:00:00+00:00",
        "tenantId": str(tenant),
        "scope": {"type": "organization", "id": str(tenant)},
        "actor": {"userId": str(uuid.uuid4())},
        "subject": {"type": "Test", "id": str(uuid.uuid4())},
        "dataClassification": "internal",
        "correlationId": None,
        "causationId": None,
        "payload": {"valeur": uuid.uuid4().hex},
    }
    brute.update(surcharges)
    return brute


async def _creer_organisation() -> uuid.UUID:
    """Crée une organisation distincte (tenant B) pour le test d'isolation."""
    async with AsyncSessionLocal() as db:
        organisation = Organization(name=f"Tenant BE166 {uuid.uuid4().hex[:8]}", slug=f"be166-{uuid.uuid4().hex}")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _nombre_outbox(event_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(func.count()).select_from(OutboxEvenement).where(OutboxEvenement.eventId == uuid.UUID(event_id)))
        ).scalar_one()


async def _nombre_consommations(event_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count()).select_from(ConsommationEvenement).where(ConsommationEvenement.eventId == uuid.UUID(event_id))
            )
        ).scalar_one()


async def test_be166_ca1_evenement_invisible_avant_commit(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)

    async with AsyncSessionLocal() as emetteur:
        await enregistrer_evenement(emetteur, donnees, emetteur_tenant=tenant)
        await emetteur.flush()
        # Une autre session ne voit pas l'événement tant que la transaction métier n'est pas committée.
        assert await _nombre_outbox(donnees["eventId"]) == 0
        await emetteur.commit()

    assert await _nombre_outbox(donnees["eventId"]) == 1


async def test_be166_ca1_echec_avant_commit_ne_publie_rien(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)

    with pytest.raises(RuntimeError):
        async with AsyncSessionLocal() as db:
            await enregistrer_evenement(db, donnees, emetteur_tenant=tenant)
            await db.flush()
            raise RuntimeError("échec injecté avant commit")

    assert await _nombre_outbox(donnees["eventId"]) == 0, "aucun événement publié si la transaction métier échoue"


async def test_be166_ca2_livraison_repetee_produit_un_seul_effet(organization: dict, caplog: pytest.LogCaptureFixture):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)
    consommateur = f"test.be166.{uuid.uuid4().hex[:8]}"
    effets: list[str] = []

    async def handler(evenement):
        effets.append(str(evenement.eventId))

    async with AsyncSessionLocal() as db:
        await enregistrer_evenement(db, donnees, emetteur_tenant=tenant)
        await db.commit()

    async with AsyncSessionLocal() as db:
        premiere = await distribuer_pour_consommateur(db, consommateur, tenant, handler)
        await db.commit()

    caplog.set_level(logging.INFO)
    async with AsyncSessionLocal() as db:
        seconde = await distribuer_pour_consommateur(db, consommateur, tenant, handler)
        await db.commit()

    assert premiere == 1
    assert seconde == 0, "un rejeu ne doit pas redistribuer l'événement"
    assert effets == [donnees["eventId"]], "un seul effet pour le consommateur"
    assert await _nombre_consommations(donnees["eventId"]) == 1, "une seule consommation consignée par couple"
    assert "REPLAY_DUPLICATE" in caplog.text, "le rejeu est consigné REPLAY_DUPLICATE"


async def test_be166_ca3_publication_sans_emetteur_refusee(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_evenement(db, donnees, emetteur_tenant=None)
        await db.rollback()

    assert erreur.value.code == "PERMISSION_DENIED"
    assert erreur.value.status_code == 403
    assert await _nombre_outbox(donnees["eventId"]) == 0


async def test_be166_ca4_consommateur_ne_recoit_jamais_le_tenant_d_un_autre(organization: dict):
    tenant_a = uuid.UUID(organization["id"])
    tenant_b = await _creer_organisation()
    donnees_b = _enveloppe(tenant_b)
    recus_par_a: list[str] = []

    async def handler_a(evenement):
        recus_par_a.append(str(evenement.eventId))

    async with AsyncSessionLocal() as db:
        await enregistrer_evenement(db, donnees_b, emetteur_tenant=tenant_b)
        await db.commit()

    async with AsyncSessionLocal() as db:
        livres = await distribuer_pour_consommateur(db, f"test.be166.a.{uuid.uuid4().hex[:8]}", tenant_a, handler_a)
        await db.commit()

    assert livres == 0
    assert recus_par_a == [], "le consommateur du tenant A ne reçoit pas l'événement du tenant B"


async def test_be166_ca4_tenant_de_l_enveloppe_different_de_l_identite_refuse(organization: dict):
    tenant_a = uuid.UUID(organization["id"])
    tenant_b = await _creer_organisation()
    donnees = _enveloppe(tenant_b)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_evenement(db, donnees, emetteur_tenant=tenant_a)
        await db.rollback()

    assert erreur.value.code == "TENANT_MISMATCH"
    assert await _nombre_outbox(donnees["eventId"]) == 0


async def test_be166_consommation_refusee_hors_tenant_sans_trace(organization: dict):
    """Un consommateur d'un autre tenant que l'événement ne consomme rien (CA-4, défense en profondeur)."""
    tenant_a = uuid.UUID(organization["id"])
    tenant_b = await _creer_organisation()
    donnees_b = _enveloppe(tenant_b)

    async with AsyncSessionLocal() as db:
        evenement = await enregistrer_evenement(db, donnees_b, emetteur_tenant=tenant_b)
        await db.commit()

    async with AsyncSessionLocal() as db:
        lus = await lire_evenements_pour_tenant(db, tenant_a)
        assert all(e.eventId != evenement.eventId for e in lus)
        appliquee = await consommer_evenement(db, f"test.be166.hors.{uuid.uuid4().hex[:8]}", evenement, tenant_a)
        await db.commit()

    assert appliquee is False
    assert await _nombre_consommations(donnees_b["eventId"]) == 0
