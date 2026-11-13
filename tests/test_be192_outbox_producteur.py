"""BE-192 : outbox producteur et enveloppe d'événement.

Tests écrits d'après la définition `### BE-192` de
implementation-backend/tasks-donnees-api-contrats.md, avant le code.

Écart consigné : la table `outbox_evenement` (BE-166, BE-234) tient déjà le rôle de
`event_outbox` ; elle est étendue de quatre colonnes au lieu de créer une seconde table.

Couverture :
- CA-1 : le changement métier et sa ligne outbox sont committés ensemble ; une panne injectée
  avant commit ne laisse aucune ligne ;
- CA-2 : l'enveloppe producteur porte tous les champs listés, et la ligne persistée porte
  les champs d'agrégat et de producteur ; un champ requis absent est refusé ;
- CA-3 : un payload contenant une clé secrète est refusé, rien n'est écrit ;
- CA-4 : `eventId` est unique en base, et une seconde écriture du même événement ne crée pas de ligne ;
- CA-5 : une ligne dont le `tenantId` diffère de celui de l'agrégat est rejetée (isolation).

Chaque test utilise des identifiants uniques (événement, agrégat, organisation).
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.evenements.enveloppe import EnveloppeProducteur
from app.evenements.models import OutboxEvenement
from app.evenements.outbox import enregistrer_evenement_producteur
from app.identity.models import Organization

CHAMPS_ENVELOPPE_PRODUCTEUR = {
    "eventId",
    "eventType",
    "schemaVersion",
    "occurredAt",
    "recordedAt",
    "tenantId",
    "aggregateType",
    "aggregateId",
    "aggregateVersion",
    "producer",
    "correlationId",
    "causationId",
    "payload",
    "publishedAt",
}


def _enveloppe(tenant: uuid.UUID, **surcharges) -> dict:
    """Enveloppe brute d'un producteur (BE-192) ; `surcharges` remplace ou retire un champ (valeur `None` = absent)."""
    brute = {
        "eventId": str(uuid.uuid4()),
        "eventType": f"Test.BE192.{uuid.uuid4().hex}",
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
        "aggregateId": f"agregat-{uuid.uuid4().hex}",
        "aggregateVersion": 3,
        "producer": "test.be192",
    }
    for cle, valeur in surcharges.items():
        if valeur is None and cle in brute:
            del brute[cle]
        else:
            brute[cle] = valeur
    return brute


async def _creer_organisation() -> uuid.UUID:
    """Crée une organisation distincte, utilisée comme second tenant."""
    async with AsyncSessionLocal() as db:
        organisation = Organization(name=f"Tenant BE192 {uuid.uuid4().hex[:8]}", slug=f"be192-{uuid.uuid4().hex}")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _nombre_outbox(event_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(func.count()).select_from(OutboxEvenement).where(OutboxEvenement.eventId == uuid.UUID(event_id)))
        ).scalar_one()


async def _ligne_outbox(event_id: str) -> OutboxEvenement:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(OutboxEvenement).where(OutboxEvenement.eventId == uuid.UUID(event_id)))).scalar_one()


async def test_be192_ca1_mutation_et_ligne_outbox_committees_ensemble(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)
    slug = f"be192-mutation-{uuid.uuid4().hex}"

    async with AsyncSessionLocal() as db:
        db.add(Organization(name="Mutation BE192", slug=slug))
        await enregistrer_evenement_producteur(db, donnees, emetteur_tenant=tenant, tenant_agregat=tenant)
        await db.commit()

    assert await _nombre_outbox(donnees["eventId"]) == 1
    async with AsyncSessionLocal() as db:
        assert (await db.execute(select(func.count()).select_from(Organization).where(Organization.slug == slug))).scalar_one() == 1


async def test_be192_ca1_panne_avant_commit_n_ecrit_ni_mutation_ni_ligne(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)
    slug = f"be192-panne-{uuid.uuid4().hex}"

    with pytest.raises(RuntimeError):
        async with AsyncSessionLocal() as db:
            db.add(Organization(name="Panne BE192", slug=slug))
            await enregistrer_evenement_producteur(db, donnees, emetteur_tenant=tenant, tenant_agregat=tenant)
            await db.flush()
            raise RuntimeError("panne injectée avant commit")

    assert await _nombre_outbox(donnees["eventId"]) == 0, "aucune ligne outbox si la mutation n'est pas committée"
    async with AsyncSessionLocal() as db:
        assert (await db.execute(select(func.count()).select_from(Organization).where(Organization.slug == slug))).scalar_one() == 0


async def test_be192_ca2_enveloppe_et_ligne_portent_tous_les_champs(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)

    assert CHAMPS_ENVELOPPE_PRODUCTEUR <= set(EnveloppeProducteur.model_fields), "le modèle déclare tous les champs listés"

    async with AsyncSessionLocal() as db:
        enveloppe = await enregistrer_evenement_producteur(db, donnees, emetteur_tenant=tenant, tenant_agregat=tenant)
        await db.commit()

    assert CHAMPS_ENVELOPPE_PRODUCTEUR <= set(enveloppe.model_dump()), "l'enveloppe renvoyée porte tous les champs"
    assert enveloppe.recordedAt is not None and enveloppe.recordedAt.tzinfo is not None, "recordedAt est fixé en UTC à l'écriture"
    assert enveloppe.publishedAt is None, "un événement non encore publié n'a pas de publishedAt"

    ligne = await _ligne_outbox(donnees["eventId"])
    assert ligne.aggregateType == donnees["aggregateType"]
    assert ligne.aggregateId == donnees["aggregateId"]
    assert ligne.aggregateVersion == donnees["aggregateVersion"]
    assert ligne.producer == donnees["producer"]
    assert ligne.createdAt is not None
    assert ligne.publieAt is not None


async def test_be192_ca2_champ_requis_absent_refuse(organization: dict):
    tenant = uuid.UUID(organization["id"])

    for champ in ("aggregateType", "aggregateId", "aggregateVersion", "producer"):
        donnees = _enveloppe(tenant, **{champ: None})
        async with AsyncSessionLocal() as db:
            with pytest.raises(AppError) as erreur:
                await enregistrer_evenement_producteur(db, donnees, emetteur_tenant=tenant, tenant_agregat=tenant)
            await db.rollback()
        assert erreur.value.code == "SCHEMA_INVALID", f"champ absent refusé : {champ}"
        assert await _nombre_outbox(donnees["eventId"]) == 0


async def test_be192_ca3_payload_avec_secret_refuse_sans_ecriture(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant, payload={"apiToken": uuid.uuid4().hex})

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_evenement_producteur(db, donnees, emetteur_tenant=tenant, tenant_agregat=tenant)
        await db.rollback()

    assert erreur.value.code == "SCHEMA_INVALID"
    assert donnees["payload"]["apiToken"] not in str(erreur.value.message), "la valeur secrète n'apparaît pas dans l'erreur"
    assert await _nombre_outbox(donnees["eventId"]) == 0


async def test_be192_ca3_payload_stocke_sans_champs_producteur(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)

    async with AsyncSessionLocal() as db:
        await enregistrer_evenement_producteur(db, donnees, emetteur_tenant=tenant, tenant_agregat=tenant)
        await db.commit()

    ligne = await _ligne_outbox(donnees["eventId"])
    assert "aggregateId" not in ligne.payload, "les champs d'agrégat vivent dans leurs colonnes, pas dans le payload"
    assert "aggregateType" not in ligne.payload, "les champs d'agrégat vivent dans leurs colonnes, pas dans le payload"
    assert ligne.payload["payload"]["valeur"] == donnees["payload"]["valeur"], "le payload métier est conservé tel quel"


async def test_be192_ca4_event_id_unique_en_base(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)

    async with AsyncSessionLocal() as db:
        await enregistrer_evenement_producteur(db, donnees, emetteur_tenant=tenant, tenant_agregat=tenant)
        await db.commit()

    async with AsyncSessionLocal() as db:
        await enregistrer_evenement_producteur(db, donnees, emetteur_tenant=tenant, tenant_agregat=tenant)
        await db.commit()
    assert await _nombre_outbox(donnees["eventId"]) == 1, "une seconde écriture du même eventId ne crée pas de ligne"

    async with AsyncSessionLocal() as db:
        db.add(
            OutboxEvenement(
                eventId=uuid.UUID(donnees["eventId"]),
                eventType="Test.BE192.doublon",
                schemaVersion=1,
                portee="tenant",
                tenantId=tenant,
                payload={"valeur": "doublon"},
                statut="publie",
                tentatives=0,
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


async def test_be192_ca5_tenant_de_ligne_different_de_l_agregat_refuse(organization: dict):
    tenant_identite = uuid.UUID(organization["id"])
    tenant_agregat = await _creer_organisation()
    donnees = _enveloppe(tenant_identite)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_evenement_producteur(db, donnees, emetteur_tenant=tenant_identite, tenant_agregat=tenant_agregat)
        await db.rollback()

    assert erreur.value.code == "TENANT_MISMATCH"
    assert erreur.value.status_code == 403
    assert await _nombre_outbox(donnees["eventId"]) == 0


async def test_be192_ca5_tenant_de_ligne_egal_a_l_agregat_accepte(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant, occurredAt=datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc).isoformat())

    async with AsyncSessionLocal() as db:
        await enregistrer_evenement_producteur(db, donnees, emetteur_tenant=tenant, tenant_agregat=tenant)
        await db.commit()

    assert await _nombre_outbox(donnees["eventId"]) == 1
