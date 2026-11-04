"""BE-150 : enveloppe d'événement commune.

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-parametres-notifications-audit.md,
section BE-150) avant le code. Critères couverts :
- CA-1 : une enveloppe valide contient eventId, eventType, schemaVersion, occurredAt (UTC), tenantId,
  scope, actor, subject, dataClassification, correlationId, causationId, payload ;
- CA-2 : sans tenantId ou sans eventId, rejet avec SCHEMA_INVALID ;
- CA-3 : deux publications de même eventId produisent un seul événement logique ;
- CA-4 : tenantId dérivé de l'identité authentifiée ; un tenant différent (enveloppe ou payload)
  renvoie TENANT_MISMATCH et n'est ni distribué ni retenu pour la déduplication ;
- CA-5 : un payload contenant une clé secrète est rejeté avec SCHEMA_INVALID, et la valeur
  n'apparaît dans aucune trace ;
- recommandation QE-PAR-01 : émetteur non authentifié refusé avec PERMISSION_DENIED (403).

Chaque test utilise un eventType unique : les abonnements du registre `app.shared.events` sont
globaux au process et ne sont jamais retirés, donc un nom partagé ferait fuir les appels d'un test
dans l'autre.
"""

import logging
import uuid

import pytest

from app.core.errors import AppError
from app.evenements.enveloppe import EnveloppeEvenement, valider_enveloppe
from app.evenements.publication import publier_enveloppe
from app.shared import events as bus

ENVELOPPE_CHAMPS = (
    "eventId",
    "eventType",
    "schemaVersion",
    "occurredAt",
    "tenantId",
    "scope",
    "actor",
    "subject",
    "dataClassification",
    "correlationId",
    "causationId",
    "payload",
)
VALEUR_SECRETE = "valeur-secrete-de-test-7f3a9c"


def type_unique() -> str:
    return f"Test.BE150.{uuid.uuid4().hex}"


def enveloppe_valide(tenant: uuid.UUID, type_evenement: str | None = None, **surcharges) -> dict:
    """Enveloppe brute conforme à CA-1. `surcharges` remplace ou retire (valeur None) un champ."""
    brute = {
        "eventId": str(uuid.uuid4()),
        "eventType": type_evenement or type_unique(),
        "schemaVersion": 1,
        "occurredAt": "2026-11-04T10:00:00+00:00",
        "tenantId": str(tenant),
        "scope": {"type": "organization", "id": str(tenant)},
        "actor": {"userId": str(uuid.uuid4())},
        "subject": {"type": "alert", "id": str(uuid.uuid4())},
        "dataClassification": "internal",
        "correlationId": str(uuid.uuid4()),
        "causationId": None,
        "payload": {"alertId": str(uuid.uuid4()), "severity": "high"},
    }
    for cle, valeur in surcharges.items():
        if valeur is None:
            brute.pop(cle, None)
        else:
            brute[cle] = valeur
    return brute


def abonne_compteur(type_evenement: str) -> list[EnveloppeEvenement]:
    """Abonne un handler qui collecte les enveloppes reçues pour `type_evenement`."""
    recus: list[EnveloppeEvenement] = []

    async def handler(enveloppe: EnveloppeEvenement) -> None:
        recus.append(enveloppe)

    bus.subscribe(type_evenement, handler)
    return recus


# CA-1 : enveloppe valide complète


def test_ca1_enveloppe_valide_contient_tous_les_champs():
    tenant = uuid.uuid4()
    enveloppe = valider_enveloppe(enveloppe_valide(tenant), tenant_identite=tenant)

    donnees = enveloppe.model_dump()
    for champ in ENVELOPPE_CHAMPS:
        assert champ in donnees, f"champ d'enveloppe manquant : {champ}"
    assert enveloppe.tenantId == tenant
    assert enveloppe.schemaVersion == 1


def test_ca1_occurred_at_normalise_en_utc():
    tenant = uuid.uuid4()
    brute = enveloppe_valide(tenant, occurredAt="2026-11-04T12:00:00+02:00")

    enveloppe = valider_enveloppe(brute, tenant_identite=tenant)

    assert enveloppe.occurredAt.utcoffset().total_seconds() == 0
    assert enveloppe.occurredAt.hour == 10


def test_ca1_occurred_at_sans_fuseau_refuse():
    tenant = uuid.uuid4()
    brute = enveloppe_valide(tenant, occurredAt="2026-11-04T10:00:00")

    with pytest.raises(AppError) as erreur:
        valider_enveloppe(brute, tenant_identite=tenant)

    assert erreur.value.code == "SCHEMA_INVALID"


# CA-2 : champs obligatoires


def test_ca2_sans_tenant_id_schema_invalid():
    tenant = uuid.uuid4()
    brute = enveloppe_valide(tenant, tenantId=None)

    with pytest.raises(AppError) as erreur:
        valider_enveloppe(brute, tenant_identite=tenant)

    assert erreur.value.code == "SCHEMA_INVALID"


def test_ca2_sans_event_id_schema_invalid():
    tenant = uuid.uuid4()
    brute = enveloppe_valide(tenant, eventId=None)

    with pytest.raises(AppError) as erreur:
        valider_enveloppe(brute, tenant_identite=tenant)

    assert erreur.value.code == "SCHEMA_INVALID"


# CA-3 : déduplication


async def test_ca3_meme_event_id_produit_un_seul_evenement_logique():
    tenant = uuid.uuid4()
    type_evt = type_unique()
    recus = abonne_compteur(type_evt)
    brute = enveloppe_valide(tenant, type_evenement=type_evt)

    await publier_enveloppe(brute, tenant_identite=tenant)
    await publier_enveloppe(brute, tenant_identite=tenant)

    assert len(recus) == 1
    assert recus[0].eventId == uuid.UUID(brute["eventId"])


async def test_ca3_event_id_different_produit_deux_evenements():
    tenant = uuid.uuid4()
    type_evt = type_unique()
    recus = abonne_compteur(type_evt)

    await publier_enveloppe(enveloppe_valide(tenant, type_evenement=type_evt), tenant_identite=tenant)
    await publier_enveloppe(enveloppe_valide(tenant, type_evenement=type_evt), tenant_identite=tenant)

    assert len(recus) == 2


# CA-4 : isolation tenant


async def test_ca4_tenant_de_l_enveloppe_doit_etre_celui_de_l_identite():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    type_evt = type_unique()
    recus = abonne_compteur(type_evt)
    brute = enveloppe_valide(tenant_b, type_evenement=type_evt)

    with pytest.raises(AppError) as erreur:
        await publier_enveloppe(brute, tenant_identite=tenant_a)

    assert erreur.value.code == "TENANT_MISMATCH"
    assert recus == []


async def test_ca4_tenant_du_payload_different_renvoie_tenant_mismatch_et_rien_n_est_retenu():
    tenant = uuid.uuid4()
    autre_tenant = uuid.uuid4()
    type_evt = type_unique()
    recus = abonne_compteur(type_evt)
    eventId = str(uuid.uuid4())
    brute = enveloppe_valide(
        tenant,
        type_evenement=type_evt,
        eventId=eventId,
        payload={"tenantId": str(autre_tenant), "alertId": str(uuid.uuid4())},
    )

    with pytest.raises(AppError) as erreur:
        await publier_enveloppe(brute, tenant_identite=tenant)

    assert erreur.value.code == "TENANT_MISMATCH"
    assert recus == []

    # Un rejet n'est pas retenu pour la déduplication : la même enveloppe corrigée est distribuée.
    brute_corrigee = enveloppe_valide(tenant, type_evenement=type_evt, eventId=eventId)
    await publier_enveloppe(brute_corrigee, tenant_identite=tenant)
    assert len(recus) == 1


# CA-5 : secrets


async def test_ca5_payload_avec_cle_secrete_rejete_sans_trace(caplog):
    tenant = uuid.uuid4()
    type_evt = type_unique()
    recus = abonne_compteur(type_evt)
    brute = enveloppe_valide(tenant, type_evenement=type_evt, payload={"alertId": str(uuid.uuid4()), "password": VALEUR_SECRETE})

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AppError) as erreur:
            await publier_enveloppe(brute, tenant_identite=tenant)

    assert erreur.value.code == "SCHEMA_INVALID"
    assert recus == []
    assert VALEUR_SECRETE not in str(erreur.value.message)
    assert VALEUR_SECRETE not in caplog.text


async def test_ca5_cle_secrete_imbriquee_rejetee():
    tenant = uuid.uuid4()
    brute = enveloppe_valide(tenant, payload={"integration": {"apiToken": VALEUR_SECRETE}})

    with pytest.raises(AppError) as erreur:
        await publier_enveloppe(brute, tenant_identite=tenant)

    assert erreur.value.code == "SCHEMA_INVALID"
    assert VALEUR_SECRETE not in str(erreur.value.message)


# Recommandation QE-PAR-01 : seul un émetteur authentifié publie


async def test_emetteur_non_authentifie_refuse_permission_denied():
    tenant = uuid.uuid4()
    type_evt = type_unique()
    recus = abonne_compteur(type_evt)

    with pytest.raises(AppError) as erreur:
        await publier_enveloppe(enveloppe_valide(tenant, type_evenement=type_evt), tenant_identite=None)

    assert erreur.value.code == "PERMISSION_DENIED"
    assert erreur.value.status_code == 403
    assert recus == []
