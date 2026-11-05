"""BE-074 : enveloppe d'événement de facturation, outbox et inbox.

Tests écrits d'après la définition `### BE-074` de
implementation-backend/tasks-abonnements-facturation.md, avant le code.

Frontières de la tâche (QE-FAC-28) : la table d'outbox appartient à BE-234 (`outbox_evenement`) ;
BE-074 ne crée que `inbox_event` et fournit l'émission facturation qui s'appuie sur BE-234.

Couverture :
- CA-1 : une commande et son événement sont committés ensemble ; un échec d'écriture de
  l'événement annule la commande ;
- CA-2 : un événement reçu deux fois (même `providerEventId`, même fournisseur) n'a d'effet
  qu'une fois ; un même identifiant chez un autre fournisseur n'est pas un doublon ;
- CA-3 : un événement hors ordre (version inférieure ou égale à la version confirmée) ne fait
  pas régresser l'état confirmé, et il est consigné comme tel ;
- CA-4 : un payload contenant un PAN ou un CVV est refusé avant toute persistance, à la
  réception comme à l'émission ; une donnée numérique ordinaire n'est pas refusée à tort.

Chaque test utilise des identifiants uniques (fournisseur, événement, type) pour rester
indépendant des autres tests.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.billing.events.emission import emettre_evenement_facturation
from app.billing.events.garde import valider_sans_donnee_carte
from app.billing.events.inbox import (
    RESULTAT_APPLIQUE,
    RESULTAT_DOUBLON,
    RESULTAT_HORS_ORDRE,
    recevoir_evenement_entrant,
)
from app.billing.events.models import InboxEvent
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.evenements.models import OutboxEvenement
from app.identity.models import Organization

PAN_TEST = "4111111111111111"  # numéro de test standard, valide au sens de Luhn


def _enveloppe(tenant: uuid.UUID, **surcharges) -> dict:
    """Enveloppe facturation brute conforme à BE-150, avec un payload sans donnée de carte."""
    brute = {
        "eventId": str(uuid.uuid4()),
        "eventType": f"Billing.BE074.{uuid.uuid4().hex}",
        "schemaVersion": 1,
        "occurredAt": "2026-11-04T10:00:00+00:00",
        "tenantId": str(tenant),
        "scope": {"type": "organization", "id": str(tenant)},
        "actor": {"userId": str(uuid.uuid4())},
        "subject": {"type": "Subscription", "id": str(uuid.uuid4())},
        "dataClassification": "internal",
        "correlationId": f"corr-{uuid.uuid4().hex}",
        "causationId": None,
        "payload": {"reference": "FAC-2026-0001234", "montantCentimes": 4990},
    }
    brute.update(surcharges)
    return brute


async def _nombre_outbox(event_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count()).select_from(OutboxEvenement).where(OutboxEvenement.eventId == uuid.UUID(event_id))
            )
        ).scalar_one()


async def _nombre_organisations(slug: str) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(func.count()).select_from(Organization).where(Organization.slug == slug))).scalar_one()


async def _lignes_inbox(provider: str, provider_event_id: str) -> list[InboxEvent]:
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(
            select(InboxEvent).where(InboxEvent.provider == provider, InboxEvent.providerEventId == provider_event_id)
        )
        return list(resultat.scalars())


async def _recevoir(provider: str, provider_event_id: str, *, version_recue: int, version_confirmee, appliquer, payload=None):
    """Exécute une réception dans une transaction et la committe (comme le ferait un webhook)."""
    async with AsyncSessionLocal() as db:
        resultat = await recevoir_evenement_entrant(
            db,
            provider=provider,
            providerEventId=provider_event_id,
            payload=payload if payload is not None else {"reference": "FAC-2026-0001234"},
            version_recue=version_recue,
            version_confirmee=version_confirmee,
            appliquer=appliquer,
        )
        await db.commit()
        return resultat


# CA-1 : commande et événement dans la même transaction locale


async def test_be074_ca1_commande_et_evenement_committes_ensemble(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant)
    slug = f"be074-ca1-{uuid.uuid4().hex}"

    async with AsyncSessionLocal() as db:
        db.add(Organization(name="Commande BE074", slug=slug))
        await emettre_evenement_facturation(db, donnees, emetteur_tenant=tenant)
        await db.commit()

    assert await _nombre_organisations(slug) == 1, "la commande est committée"
    assert await _nombre_outbox(donnees["eventId"]) == 1, "l'événement est committé avec la commande"


async def test_be074_ca1_echec_de_l_evenement_annule_la_commande(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant, eventType="")  # type vide : enveloppe invalide, écriture refusée
    slug = f"be074-ca1-rb-{uuid.uuid4().hex}"

    with pytest.raises(AppError):
        async with AsyncSessionLocal() as db:
            db.add(Organization(name="Commande BE074 annulée", slug=slug))
            await emettre_evenement_facturation(db, donnees, emetteur_tenant=tenant)
            await db.commit()

    assert await _nombre_organisations(slug) == 0, "la commande est annulée si l'événement échoue"
    assert await _nombre_outbox(donnees["eventId"]) == 0, "aucun événement n'est écrit"


# CA-2 : déduplication à la réception


async def test_be074_ca2_second_recu_meme_providerEventId_est_ignore():
    provider = f"prestataire-{uuid.uuid4().hex[:8]}"
    provider_event_id = f"evt_{uuid.uuid4().hex}"
    effets: list[str] = []

    async def appliquer():
        effets.append("effet")

    premier = await _recevoir(provider, provider_event_id, version_recue=1, version_confirmee=None, appliquer=appliquer)
    second = await _recevoir(provider, provider_event_id, version_recue=1, version_confirmee=None, appliquer=appliquer)

    assert premier == RESULTAT_APPLIQUE
    assert second == RESULTAT_DOUBLON, "la seconde réception est ignorée"
    assert effets == ["effet"], "l'effet n'est produit qu'une seule fois"
    assert len(await _lignes_inbox(provider, provider_event_id)) == 1


async def test_be074_ca2_meme_identifiant_chez_un_autre_fournisseur_n_est_pas_un_doublon():
    provider_a = f"prestataire-a-{uuid.uuid4().hex[:8]}"
    provider_b = f"prestataire-b-{uuid.uuid4().hex[:8]}"
    provider_event_id = f"evt_{uuid.uuid4().hex}"

    async def appliquer():
        return None

    resultat_a = await _recevoir(provider_a, provider_event_id, version_recue=1, version_confirmee=None, appliquer=appliquer)
    resultat_b = await _recevoir(provider_b, provider_event_id, version_recue=1, version_confirmee=None, appliquer=appliquer)

    assert resultat_a == RESULTAT_APPLIQUE
    assert resultat_b == RESULTAT_APPLIQUE, "la clé de déduplication est le couple (fournisseur, identifiant)"


# CA-3 : un événement hors ordre ne fait pas régresser un état confirmé


async def test_be074_ca3_evenement_hors_ordre_ne_regresse_pas_l_etat_confirme():
    provider = f"prestataire-{uuid.uuid4().hex[:8]}"
    provider_event_id = f"evt_{uuid.uuid4().hex}"
    # État confirmé : abonnement actif à la version 5, posé par un événement précédent.
    etat = {"statut": "active", "version": 5}

    async def passer_en_essai():
        etat["statut"] = "trial"
        etat["version"] = 3

    resultat = await _recevoir(
        provider, provider_event_id, version_recue=3, version_confirmee=etat["version"], appliquer=passer_en_essai
    )

    assert resultat == RESULTAT_HORS_ORDRE
    assert etat == {"statut": "active", "version": 5}, "l'état confirmé n'est pas régressé"
    lignes = await _lignes_inbox(provider, provider_event_id)
    assert [ligne.status for ligne in lignes] == [RESULTAT_HORS_ORDRE], "l'événement reste consigné"


async def test_be074_ca3_evenement_plus_recent_est_applique():
    provider = f"prestataire-{uuid.uuid4().hex[:8]}"
    provider_event_id = f"evt_{uuid.uuid4().hex}"
    etat = {"statut": "active", "version": 5}

    async def passer_en_resiliation():
        etat["statut"] = "cancelled"
        etat["version"] = 6

    resultat = await _recevoir(
        provider, provider_event_id, version_recue=6, version_confirmee=etat["version"], appliquer=passer_en_resiliation
    )

    assert resultat == RESULTAT_APPLIQUE
    assert etat == {"statut": "cancelled", "version": 6}


# CA-4 : aucun PAN ni CVV n'est persisté


@pytest.mark.parametrize(
    "payload",
    [
        {"pan": PAN_TEST},
        {"cvv": "123"},
        {"carte": {"numeroCarte": PAN_TEST}},
        {"reference": PAN_TEST},  # numéro de carte sous une clé anodine : détecté par sa valeur
        {"lignes": [{"description": "abonnement", "securityCode": "456"}]},
    ],
)
async def test_be074_ca4_reception_refuse_pan_ou_cvv_avant_persistance(payload: dict):
    provider = f"prestataire-{uuid.uuid4().hex[:8]}"
    provider_event_id = f"evt_{uuid.uuid4().hex}"
    effets: list[str] = []

    async def appliquer():
        effets.append("effet")

    with pytest.raises(AppError):
        await _recevoir(provider, provider_event_id, version_recue=1, version_confirmee=None, appliquer=appliquer, payload=payload)

    assert effets == [], "aucun effet n'est produit"
    assert await _lignes_inbox(provider, provider_event_id) == [], "rien n'est persisté"


async def test_be074_ca4_emission_refuse_pan_avant_ecriture(organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = _enveloppe(tenant, payload={"numeroCarte": PAN_TEST})

    with pytest.raises(AppError):
        async with AsyncSessionLocal() as db:
            await emettre_evenement_facturation(db, donnees, emetteur_tenant=tenant)
            await db.commit()

    assert await _nombre_outbox(donnees["eventId"]) == 0


def test_be074_ca4_donnee_numerique_ordinaire_n_est_pas_refusee():
    # Un numéro de facture de 16 chiffres qui n'est pas valide au sens de Luhn n'est pas un PAN.
    valider_sans_donnee_carte({"reference": "2026110412345678", "montantCentimes": 4990})
    valider_sans_donnee_carte({"company": "Zylo", "motif": "renouvellement"})
