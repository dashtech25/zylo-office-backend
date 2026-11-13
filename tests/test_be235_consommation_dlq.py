"""BE-235 : consommation d'événements, déduplication, retry borné, DLQ et replay.

Tests écrits d'après la définition `### BE-235` de
implementation-backend/tasks-exploitation-architecture.md, avant le code.

Couverture :
- CA-1 : un message répété produit un seul effet (déduplication à la consommation) ;
- CA-2 : le retry s'arrête au nombre maximal lu de la configuration, puis l'événement va
  en DLQ (la valeur est lue de `settings`, QE-EXP-08 : aucune constante dans le test) ;
- CA-3 : un replay sans droit d'administration donne 403 ;
- CA-4 : un replay ne touche pas un tenant hors de la portée de l'opérateur (404), et la
  liste DLQ ne montre que le tenant de la portée ;
- CA-5 : un message empoisonné n'arrête pas la file.

Données : chaque test crée ses propres identifiants (événement, consommateur, tenant).
Les événements sont écrits par `enregistrer_evenement` (BE-166/BE-234), jamais par insertion
directe, sauf la ligne d'organisation d'un second tenant (CA-4).
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.evenements.consumer import CONSOMMATEURS, consommer_lot
from app.evenements.dlq import lister_dead_letters, rejouer_dead_letter
from app.evenements.models import ConsommationEvenement, DeadLetter
from app.evenements.outbox import enregistrer_evenement, lire_evenements_pour_tenant
from app.identity.models import Organization
from app.rbac.role_assignments import AdminRoleAssignment

CHEMIN_DLQ = "/api/v1/internal/dead-letters"


@pytest.fixture(autouse=True)
def configuration_consommation(monkeypatch):
    """Renseigne le nombre maximal de tentatives (QE-EXP-08 : aucune valeur par défaut codée).

    Chaque test peut surcharger cette valeur ; sans elle, la consommation refuse de tourner.
    """
    monkeypatch.setattr(settings, "EVENTS_CONSUMER_MAX_TENTATIVES", 3)


def _enveloppe(tenant: uuid.UUID, **surcharges) -> dict:
    """Enveloppe brute conforme à BE-150, identique à la forme de test de BE-234."""
    brute = {
        "eventId": str(uuid.uuid4()),
        "eventType": f"Test.BE235.{uuid.uuid4().hex}",
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


async def _publier(tenant: uuid.UUID) -> dict:
    """Écrit un événement committé dans l'outbox du tenant ; renvoie l'enveloppe brute."""
    donnees = _enveloppe(tenant)
    async with AsyncSessionLocal() as db:
        await enregistrer_evenement(db, donnees, emetteur_tenant=tenant)
        await db.commit()
    return donnees


async def _nouvelle_organisation() -> uuid.UUID:
    """Second tenant, créé directement : le test a besoin d'un tenant que l'opérateur ne voit pas."""
    async with AsyncSessionLocal() as db:
        org = Organization(name="Tenant hors portée BE235", slug=f"be235-{uuid.uuid4().hex}")
        db.add(org)
        await db.commit()
        return org.id


async def _dead_letter_en_base(tenant: uuid.UUID, event_id: str) -> str:
    """Insère une entrée DLQ pour un événement déjà committé ; renvoie son identifiant."""
    async with AsyncSessionLocal() as db:
        ligne = DeadLetter(
            eventId=uuid.UUID(event_id),
            consommateur="consommateur-be235",
            motif="echec de test",
            tentatives=3,
            tenantId=tenant,
        )
        db.add(ligne)
        await db.commit()
        return str(ligne.id)


async def _compter_dead_letters(event_id: str) -> int:
    async with AsyncSessionLocal() as db:
        lignes = await db.execute(select(DeadLetter.id).where(DeadLetter.eventId == uuid.UUID(event_id)))
        return len(lignes.all())


def _entetes(utilisateur: dict, portee: str) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['accessToken']}"}
    if portee:
        entetes["X-Admin-Scope"] = portee
    return entetes


async def _identifiant(client: AsyncClient, utilisateur: dict) -> str:
    """Identifiant du compte connecté, lu par `/auth/me` (la fixture `registered_user` ne le porte pas)."""
    res = await client.get("/api/v1/auth/me", headers=_entetes(utilisateur, ""))
    return res.json()["id"]


async def _donner_autorite_plateforme(user_id: str) -> None:
    """Affectation active d'opérateur plateforme (BE-121), sans échéance ni révocation."""
    async with AsyncSessionLocal() as db:
        db.add(AdminRoleAssignment(
            actorId=uuid.UUID(user_id),
            roleCode="operateur_plateforme",
            scope="platform",
            grantedBy=uuid.UUID(user_id),
            grantedAt=datetime.now(timezone.utc),
        ))
        await db.commit()


# ---------------------------------------------------------------------------
# CA-1 : un message répété produit un seul effet
# ---------------------------------------------------------------------------


async def test_be235_ca1_message_repete_ne_produit_qu_un_effet(organization: dict, monkeypatch):
    tenant = uuid.UUID(organization["id"])
    donnees = await _publier(tenant)
    effets: list[str] = []

    async def handler(evenement):
        effets.append(str(evenement.eventId))

    consommateur = f"be235-ca1-{uuid.uuid4().hex}"
    async with AsyncSessionLocal() as db:
        await consommer_lot(db, consommateur, tenant, handler)
        await db.commit()
    async with AsyncSessionLocal() as db:
        # Seconde livraison du même message : la trace de consommation l'empêche de réagir.
        await consommer_lot(db, consommateur, tenant, handler)
        await db.commit()

    assert effets == [donnees["eventId"]], "un seul effet pour deux livraisons"


# ---------------------------------------------------------------------------
# CA-2 : retry borné par la configuration, puis DLQ
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("maximum", [2, 4])
async def test_be235_ca2_retry_s_arrete_au_maximum_configure_puis_dlq(organization: dict, monkeypatch, maximum: int):
    tenant = uuid.UUID(organization["id"])
    donnees = await _publier(tenant)
    monkeypatch.setattr(settings, "EVENTS_CONSUMER_MAX_TENTATIVES", maximum)
    appels = 0

    async def handler_en_echec(evenement):
        nonlocal appels
        appels += 1
        raise RuntimeError("panne simulée")

    async with AsyncSessionLocal() as db:
        resultat = await consommer_lot(db, f"be235-ca2-{uuid.uuid4().hex}", tenant, handler_en_echec)
        await db.commit()

    assert appels == maximum, "le handler est rappelé jusqu'au maximum configuré, pas au-delà"
    assert resultat.dlq == 1
    assert await _compter_dead_letters(donnees["eventId"]) == 1
    async with AsyncSessionLocal() as db:
        ligne = (await db.execute(select(DeadLetter).where(DeadLetter.eventId == uuid.UUID(donnees["eventId"])))).scalar_one()
    assert ligne.tentatives == maximum
    assert ligne.tenantId == tenant


# ---------------------------------------------------------------------------
# CA-3 : replay sans droit donne 403
# ---------------------------------------------------------------------------


async def test_be235_ca3_replay_sans_droit_donne_403(client: AsyncClient, registered_user: dict, organization: dict):
    tenant = uuid.UUID(organization["id"])
    donnees = await _publier(tenant)
    dead_letter_id = await _dead_letter_en_base(tenant, donnees["eventId"])

    res = await client.post(
        f"{CHEMIN_DLQ}/{dead_letter_id}/replay",
        headers=_entetes(registered_user, f"tenant:{tenant}"),
    )

    assert res.status_code == 403


# ---------------------------------------------------------------------------
# CA-4 : isolation de tenant au replay et à la liste
# ---------------------------------------------------------------------------


async def test_be235_ca4_replay_hors_portee_donne_404(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    tenant_portee = uuid.UUID(organization["id"])
    tenant_autre = await _nouvelle_organisation()
    donnees = await _publier(tenant_autre)
    dead_letter_id = await _dead_letter_en_base(tenant_autre, donnees["eventId"])
    await _donner_autorite_plateforme(await _identifiant(client, registered_user))
    monkeypatch.setitem(CONSOMMATEURS, "consommateur-be235", lambda evenement: None)

    res = await client.post(
        f"{CHEMIN_DLQ}/{dead_letter_id}/replay",
        headers=_entetes(registered_user, f"tenant:{tenant_portee}"),
    )

    assert res.status_code == 404, "le 404 ne révèle pas l'existence d'un tenant hors portée"


async def test_be235_ca4_liste_ne_montre_que_le_tenant_de_la_portee(client: AsyncClient, registered_user: dict, organization: dict):
    tenant_portee = uuid.UUID(organization["id"])
    tenant_autre = await _nouvelle_organisation()
    donnees_autre = await _publier(tenant_autre)
    await _dead_letter_en_base(tenant_autre, donnees_autre["eventId"])
    await _donner_autorite_plateforme(await _identifiant(client, registered_user))

    res = await client.get(CHEMIN_DLQ, headers=_entetes(registered_user, f"tenant:{tenant_portee}"))

    assert res.status_code == 200
    ids_tenants = {item["tenantId"] for item in res.json()["items"]}
    assert str(tenant_autre) not in ids_tenants


# ---------------------------------------------------------------------------
# CA-5 : un message empoisonné n'arrête pas la file
# ---------------------------------------------------------------------------


async def test_be235_ca5_message_empoisonne_n_arrete_pas_la_file(organization: dict, monkeypatch):
    tenant = uuid.UUID(organization["id"])
    empoisonne = await _publier(tenant)
    sain = await _publier(tenant)
    monkeypatch.setattr(settings, "EVENTS_CONSUMER_MAX_TENTATIVES", 2)
    traites: list[str] = []

    async def handler(evenement):
        if str(evenement.eventId) == empoisonne["eventId"]:
            raise ValueError("message invalide pour ce consommateur")
        traites.append(str(evenement.eventId))

    async with AsyncSessionLocal() as db:
        resultat = await consommer_lot(db, f"be235-ca5-{uuid.uuid4().hex}", tenant, handler)
        await db.commit()

    assert sain["eventId"] in traites, "le message sain est traité malgré le message empoisonné"
    assert resultat.dlq == 1
    assert await _compter_dead_letters(empoisonne["eventId"]) == 1
