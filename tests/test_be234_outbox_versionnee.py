"""BE-234 : outbox événementielle versionnée.

Tests écrits d'après la définition `### BE-234` de
implementation-backend/tasks-exploitation-architecture.md, avant le code.

Couverture :
- CA-1 : une mutation et son événement sont committés ensemble ; si la mutation échoue,
  aucun événement n'existe ;
- CA-2 : chaque événement persisté porte acteur, tenant, version de schéma et correlationId
  (test de contrat sur la ligne et sur l'enveloppe) ; un champ nullable absent est refusé ;
- CA-3 : un événement plateforme sans tenant est typé distinctement (`portee = plateforme`,
  `tenantId` nul, type préfixé par l'espace `Plateforme.`) et refusé par le chemin tenant ;
- CA-4 : un événement plateforme n'est lisible par aucun consommateur de tenant, et un
  événement de tenant n'est pas lu par un autre tenant (test d'isolation).

Chaque test utilise des identifiants uniques (événement, type, consommateur).
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.evenements.models import OutboxEvenement
from app.evenements.outbox import (
    distribuer_pour_consommateur,
    enregistrer_evenement,
    enregistrer_evenement_plateforme,
    lire_evenements_pour_tenant,
)
from app.identity.models import Organization


def _enveloppe(tenant: uuid.UUID, **surcharges) -> dict:
    """Enveloppe brute conforme à BE-150, avec un correlationId renseigné ; `surcharges` remplace un champ."""
    brute = {
        "eventId": str(uuid.uuid4()),
        "eventType": f"Test.BE234.{uuid.uuid4().hex}",
        "schemaVersion": 1,
        "occurredAt": "2026-11-04T10:00:00+00:00",
        "tenantId": str(tenant),
        "scope": {"type": "organization", "id": str(tenant)},
        "actor": {"userId": str(uuid.uuid4())},
        "subject": {"type": "Test", "id": str(uuid.uuid4())},
        "dataClassification": "internal",
        "correlationId": f"corr-{uuid.uuid4().hex}",
        "causationId": None,
        "payload": {"valeur": uuid.uuid4().hex},
    }
    brute.update(surcharges)
    return brute


def _enveloppe_plateforme(**surcharges) -> dict:
    """Enveloppe d'un événement plateforme : pas de tenant, type dans l'espace `Plateforme.`."""
    brute = {
        "eventId": str(uuid.uuid4()),
        "eventType": f"Plateforme.BE234.{uuid.uuid4().hex}",
        "schemaVersion": 1,
        "occurredAt": "2026-11-04T10:00:00+00:00",
        "tenantId": None,
        "scope": {"type": "plateforme"},
        "actor": {"systeme": "job-exploitation"},
        "subject": {"type": "Plateforme", "id": uuid.uuid4().hex},
        "dataClassification": "internal",
        "correlationId": None,
        "causationId": None,
        "payload": {"valeur": uuid.uuid4().hex},
    }
    brute.update(surcharges)
    return brute


async def _creer_organisation() -> uuid.UUID:
    """Crée une organisation distincte, utilisée comme second tenant."""
    async with AsyncSessionLocal() as db:
        organisation = Organization(name=f"Tenant BE234 {uuid.uuid4().hex[:8]}", slug=f"be234-{uuid.uuid4().hex}")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _ligne_outbox(event_id: str) -> OutboxEvenement | None:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(OutboxEvenement).where(OutboxEvenement.eventId == uuid.UUID(event_id)))).scalar_one_or_none()


async def _nombre_outbox(event_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(func.count()).select_from(OutboxEvenement).where(OutboxEvenement.eventId == uuid.UUID(event_id)))
        ).scalar_one()


async def _nombre_organisations(slug: str) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(func.count()).select_from(Organization).where(Organization.slug == slug))).scalar_one()


# CA-1 : mutation et événement dans la même transaction


async def test_be234_ca1_mutation_et_evenement_committes_ensemble(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)
    slug = f"be234-ca1-{uuid.uuid4().hex}"

    async with AsyncSessionLocal() as db:
        db.add(Organization(name="Mutation BE234", slug=slug))
        await enregistrer_evenement(db, donnees, emetteur_tenant=tenant)
        await db.commit()

    assert await _nombre_organisations(slug) == 1, "la mutation est committée"
    assert await _nombre_outbox(donnees["eventId"]) == 1, "l'événement est committé avec la mutation"


async def test_be234_ca1_echec_de_mutation_ne_laisse_aucun_evenement(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)
    slug = f"be234-ca1-rb-{uuid.uuid4().hex}"

    with pytest.raises(RuntimeError):
        async with AsyncSessionLocal() as db:
            db.add(Organization(name="Mutation BE234 annulée", slug=slug))
            await enregistrer_evenement(db, donnees, emetteur_tenant=tenant)
            await db.flush()
            raise RuntimeError("échec de la mutation avant commit")

    assert await _nombre_organisations(slug) == 0, "la mutation est annulée"
    assert await _nombre_outbox(donnees["eventId"]) == 0, "aucun événement si la mutation échoue"


# CA-2 : contrat de l'événement persisté


async def test_be234_ca2_ligne_porte_acteur_tenant_version_et_correlation(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant, schemaVersion=3)

    async with AsyncSessionLocal() as db:
        enveloppe = await enregistrer_evenement(db, donnees, emetteur_tenant=tenant)
        await db.commit()

    ligne = await _ligne_outbox(donnees["eventId"])
    assert ligne is not None
    assert ligne.tenantId == tenant, "tenant explicite"
    assert ligne.schemaVersion == 3, "version de schéma persistée"
    assert ligne.acteur == donnees["actor"], "acteur persisté"
    assert ligne.correlationId == donnees["correlationId"], "correlationId persisté"
    assert ligne.portee == "tenant", "un événement de tenant est typé tenant"
    assert ligne.tentatives == 0, "aucune tentative de livraison à la publication"
    assert enveloppe.correlationId == donnees["correlationId"], "l'enveloppe renvoyée porte le même correlationId"


async def test_be234_ca2_correlation_nulle_acceptee_mais_champ_absent_refuse(organization: dict):
    tenant = uuid.UUID(organization["id"])
    sans_correlation = _enveloppe(tenant, correlationId=None)
    champ_absent = _enveloppe(tenant)
    del champ_absent["correlationId"]

    async with AsyncSessionLocal() as db:
        await enregistrer_evenement(db, sans_correlation, emetteur_tenant=tenant)
        await db.commit()
    assert (await _ligne_outbox(sans_correlation["eventId"])).correlationId is None

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_evenement(db, champ_absent, emetteur_tenant=tenant)
        await db.rollback()
    assert erreur.value.code == "SCHEMA_INVALID"
    assert await _nombre_outbox(champ_absent["eventId"]) == 0


async def test_be234_ca2_version_de_schema_absente_refusee(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)
    del donnees["schemaVersion"]

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_evenement(db, donnees, emetteur_tenant=tenant)
        await db.rollback()

    assert erreur.value.code == "SCHEMA_INVALID"
    assert await _nombre_outbox(donnees["eventId"]) == 0


# CA-3 : événement plateforme typé distinctement


async def test_be234_ca3_evenement_plateforme_sans_tenant_est_typé_distinctement(organization: dict):
    donnees = _enveloppe_plateforme()

    async with AsyncSessionLocal() as db:
        await enregistrer_evenement_plateforme(db, donnees, emetteur_plateforme=True)
        await db.commit()

    ligne = await _ligne_outbox(donnees["eventId"])
    assert ligne is not None
    assert ligne.tenantId is None, "aucun tenant sur un événement plateforme"
    assert ligne.portee == "plateforme", "typé distinctement des événements de tenant"
    assert ligne.eventType.startswith("Plateforme."), "type dans l'espace plateforme"


async def test_be234_ca3_chemin_tenant_refuse_un_evenement_plateforme(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe_plateforme()

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_evenement(db, donnees, emetteur_tenant=tenant)
        await db.rollback()

    assert erreur.value.code == "SCHEMA_INVALID", "un événement sans tenant ne passe pas le chemin tenant"
    assert await _nombre_outbox(donnees["eventId"]) == 0


async def test_be234_ca3_type_plateforme_hors_espace_refuse(organization: dict):
    donnees = _enveloppe_plateforme(eventType=f"Test.BE234.{uuid.uuid4().hex}")

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_evenement_plateforme(db, donnees, emetteur_plateforme=True)
        await db.rollback()

    assert erreur.value.code == "SCHEMA_INVALID"
    assert await _nombre_outbox(donnees["eventId"]) == 0


async def test_be234_ca3_plateforme_avec_tenant_renseigne_refuse(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe_plateforme(tenantId=str(tenant))

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_evenement_plateforme(db, donnees, emetteur_plateforme=True)
        await db.rollback()

    assert erreur.value.code == "SCHEMA_INVALID"
    assert await _nombre_outbox(donnees["eventId"]) == 0


async def test_be234_ca3_publication_plateforme_sans_emetteur_interne_refusee(organization: dict):
    donnees = _enveloppe_plateforme()

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_evenement_plateforme(db, donnees, emetteur_plateforme=False)
        await db.rollback()

    assert erreur.value.code == "PERMISSION_DENIED"
    assert erreur.value.status_code == 403
    assert await _nombre_outbox(donnees["eventId"]) == 0


async def test_be234_ca3_base_refuse_un_evenement_de_tenant_sans_tenant(organization: dict):
    """La base elle-même refuse une incohérence `portee` / `tenantId` (défense en profondeur)."""
    async with AsyncSessionLocal() as db:
        db.add(
            OutboxEvenement(
                eventId=uuid.uuid4(),
                eventType=f"Test.BE234.{uuid.uuid4().hex}",
                schemaVersion=1,
                tenantId=None,
                portee="tenant",
                acteur={},
                correlationId=None,
                payload={},
                statut="publie",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


# CA-4 : isolation des consommateurs


async def test_be234_ca4_evenement_plateforme_jamais_lu_par_un_consommateur_de_tenant(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe_plateforme()
    recus: list[str] = []

    async def handler(evenement):
        recus.append(str(evenement.eventId))

    async with AsyncSessionLocal() as db:
        await enregistrer_evenement_plateforme(db, donnees, emetteur_plateforme=True)
        await db.commit()

    async with AsyncSessionLocal() as db:
        lus = await lire_evenements_pour_tenant(db, tenant)
        await distribuer_pour_consommateur(db, f"test.be234.{uuid.uuid4().hex[:8]}", tenant, handler)
        await db.commit()

    assert all(e.eventId != uuid.UUID(donnees["eventId"]) for e in lus), "lecture par tenant : pas d'événement plateforme"
    assert donnees["eventId"] not in recus, "la distribution d'un tenant ne livre pas l'événement plateforme"


async def test_be234_ca4_evenement_d_un_tenant_non_lu_par_un_autre_tenant(organization: dict):
    tenant_a = uuid.UUID(organization["id"])
    tenant_b = await _creer_organisation()
    donnees_b = _enveloppe(tenant_b)

    async with AsyncSessionLocal() as db:
        await enregistrer_evenement(db, donnees_b, emetteur_tenant=tenant_b)
        await db.commit()

    async with AsyncSessionLocal() as db:
        lus_par_a = await lire_evenements_pour_tenant(db, tenant_a)

    assert all(e.eventId != uuid.UUID(donnees_b["eventId"]) for e in lus_par_a)
