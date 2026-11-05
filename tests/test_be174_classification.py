"""BE-174 : classification et minimisation des données sensibles.

Tests écrits d'après la définition `### BE-174` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : tout champ de payload sans classification déclarée fait échouer la validation
  (`SCHEMA_INVALID`) ; la classification déclarée est persistée sur la ligne d'outbox ;
- CA-2 : un numéro de carte (valeur factice valide au sens de Luhn) est refusé du payload,
  et n'apparaît dans aucune erreur ni trace ;
- CA-3 : un consommateur sans droit sur un champ classé ne reçoit pas le champ (expurgé) ;
  un champ sans consommateur déclaré n'est jamais exposé ;
- CA-4 : la classification n'autorise pas la sortie d'un champ du tenant A vers le tenant B.

Chaque test utilise un type d'événement unique pour ne pas dépendre des autres tests.
"""

import logging
import uuid

import pytest

from app.core.database import AsyncSessionLocal, engine
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.evenements.enveloppe import EnveloppeEvenement
from app.evenements.models import OutboxEvenement
from app.evenements.outbox import enregistrer_evenement
from app.identity.models import Organization
from app.securite.classification import filtrer_payload_pour_consommateur, verifier_classification_payload
from app.securite.models import ClassificationChamp
from sqlalchemy import select


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Repart d'un pool lié à la boucle courante, comme le fait le fixture `client` de conftest."""
    await engine.dispose()
    yield


def _type_unique() -> str:
    return f"Test.BE174.{uuid.uuid4().hex}"


async def _declarer(type_evenement: str, champs: dict[str, tuple[str, list[str] | None]]) -> None:
    """Déclare la classification de chaque champ : `champs[nom] = (classification, consommablePar)`."""
    async with AsyncSessionLocal() as db:
        for nom, (classification, consommable_par) in champs.items():
            db.add(
                ClassificationChamp(
                    typeEvenement=type_evenement,
                    champ=nom,
                    classification=classification,
                    consommablePar=consommable_par,
                )
            )
        await db.commit()


async def _creer_organisation() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name=f"Tenant BE174 {uuid.uuid4().hex[:8]}", slug=f"be174-{uuid.uuid4().hex}")
        db.add(organisation)
        await db.commit()
        return organisation.id


def _enveloppe(tenant: uuid.UUID, type_evenement: str, payload: dict, classification: str = "internal") -> dict:
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": type_evenement,
        "schemaVersion": 1,
        "occurredAt": "2026-11-04T10:00:00+00:00",
        "tenantId": str(tenant),
        "scope": {"type": "organization", "id": str(tenant)},
        "actor": {"userId": str(uuid.uuid4())},
        "subject": {"type": "Test", "id": str(uuid.uuid4())},
        "dataClassification": classification,
        "correlationId": None,
        "causationId": None,
        "payload": payload,
    }


async def test_be174_ca1_champ_non_declare_refuse():
    type_evenement = _type_unique()
    await _declarer(type_evenement, {"montant": ("internal", None)})

    async with AsyncSessionLocal() as db:
        with pytest.raises(ErreurCatalogue) as erreur:
            await verifier_classification_payload(db, type_evenement, {"montant": 12, "commentaireLibre": "x"})

    assert erreur.value.code == CodeErreur.SCHEMA_INVALID.value


async def test_be174_ca1_champs_tous_declares_acceptes():
    type_evenement = _type_unique()
    await _declarer(type_evenement, {"montant": ("internal", None), "libelle": ("public", None)})

    async with AsyncSessionLocal() as db:
        await verifier_classification_payload(db, type_evenement, {"montant": 12, "libelle": "Plein"})


async def test_be174_ca1_classification_persistee_dans_l_outbox():
    tenant = await _creer_organisation()
    type_evenement = _type_unique()
    await _declarer(type_evenement, {"montant": ("confidential", None)})
    donnees = _enveloppe(tenant, type_evenement, {"montant": 12}, classification="confidential")

    async with AsyncSessionLocal() as db:
        await enregistrer_evenement(db, donnees, emetteur_tenant=tenant)
        await db.commit()

    async with AsyncSessionLocal() as db:
        ligne = (
            await db.execute(select(OutboxEvenement).where(OutboxEvenement.eventId == uuid.UUID(donnees["eventId"])))
        ).scalar_one()
    assert ligne.dataClassification == "confidential"


async def test_be174_ca2_numero_de_carte_refuse_sans_fuite():
    type_evenement = _type_unique()
    numero_factice = "4111 1111 1111 1111"  # valeur de test, valide au sens de Luhn
    await _declarer(type_evenement, {"libelle": ("internal", None)})

    async with AsyncSessionLocal() as db:
        with pytest.raises(ErreurCatalogue) as erreur:
            await verifier_classification_payload(db, type_evenement, {"libelle": f"paiement {numero_factice}"})

    assert erreur.value.code == CodeErreur.SCHEMA_INVALID.value
    chiffres = numero_factice.replace(" ", "")
    assert chiffres not in repr(erreur.value.__dict__)
    assert numero_factice not in repr(erreur.value.__dict__)


async def test_be174_ca2_suite_de_chiffres_non_luhn_acceptee():
    type_evenement = _type_unique()
    await _declarer(type_evenement, {"reference": ("internal", None)})

    async with AsyncSessionLocal() as db:
        # Seize chiffres qui ne passent pas Luhn : ce n'est pas un numéro de carte.
        await verifier_classification_payload(db, type_evenement, {"reference": "1234567890123456"})


async def test_be174_ca3_consommateur_sans_droit_ne_recoit_pas_le_champ():
    tenant = await _creer_organisation()
    type_evenement = _type_unique()
    await _declarer(
        type_evenement,
        {
            "montant": ("internal", ["settings.read"]),
            "libelle": ("public", None),
        },
    )
    payload = {"montant": 12, "libelle": "Plein"}

    async with AsyncSessionLocal() as db:
        sans_droit = await filtrer_payload_pour_consommateur(
            db,
            type_evenement,
            payload,
            tenant_evenement=tenant,
            tenant_consommateur=tenant,
            permissions={"notifications.read"},
        )
        avec_droit = await filtrer_payload_pour_consommateur(
            db,
            type_evenement,
            payload,
            tenant_evenement=tenant,
            tenant_consommateur=tenant,
            permissions={"settings.read"},
        )

    assert "montant" not in sans_droit
    assert sans_droit["libelle"] == "Plein"
    assert avec_droit == payload


async def test_be174_ca3_champ_sans_consommateur_declare_jamais_expose():
    tenant = await _creer_organisation()
    type_evenement = _type_unique()
    await _declarer(type_evenement, {"secretMetier": ("confidential", None)})

    async with AsyncSessionLocal() as db:
        filtre = await filtrer_payload_pour_consommateur(
            db,
            type_evenement,
            {"secretMetier": "valeur"},
            tenant_evenement=tenant,
            tenant_consommateur=tenant,
            permissions={"settings.read", "notifications.read", "evenements.read"},
        )

    assert "secretMetier" not in filtre


async def test_be174_ca4_sortie_inter_tenant_refusee():
    tenant_a = await _creer_organisation()
    tenant_b = await _creer_organisation()
    type_evenement = _type_unique()
    await _declarer(type_evenement, {"libelle": ("public", ["evenements.read"])})

    async with AsyncSessionLocal() as db:
        with pytest.raises(ErreurCatalogue) as erreur:
            await filtrer_payload_pour_consommateur(
                db,
                type_evenement,
                {"libelle": "Plein"},
                tenant_evenement=tenant_a,
                tenant_consommateur=tenant_b,
                permissions={"evenements.read"},
            )

    assert erreur.value.code == CodeErreur.TENANT_MISMATCH.value


def test_be174_enveloppe_expose_la_classification_du_contrat():
    # Garde-fou de contrat : BE-150 fournit le champ que BE-174 classe.
    assert "dataClassification" in EnveloppeEvenement.model_fields
