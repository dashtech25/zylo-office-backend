"""BE-029 : évènements webhook de paiement (idempotence, refus, quarantaine).

Intention : prouver les critères d'acceptation de BE-029
(implementation-backend/tasks-socle-tenant-identite.md, section BE-029) :
- CA-1 : le même évènement reçu deux fois ne produit qu'un seul effet ;
- CA-2 (refus) : un évènement dont la référence est inconnue n'écrit rien ;
- CA-3 (refus) : un évènement sans effet de paiement reconnu n'accorde aucun entitlement ;
- CA-4 (isolation) : un évènement référençant une tentative de O2 n'est jamais appliqué sous O1 ;
- CA-5 (refus) : un évènement contradictoire avec le même identifiant fournisseur est mis en
  quarantaine, pas appliqué.

Les tests appellent le service `app/billing/webhooks.py` directement : la route d'entrée
(signature `verif-hash`, appartenant à BE-083) n'est pas testée ici. Aucun appel réseau.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app.billing import service
from app.billing.models import Invoice, PaymentAttempt, PaymentWebhookEvent, Subscription, SubscriptionEntitlement
from app.billing.webhooks import traiter_evenement_webhook
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import Organization


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Chaque test a sa propre boucle d'événements ; le pool de `engine` ne doit pas
    garder de connexion d'une boucle fermée (même garde que la fixture `client`)."""
    from app.core.database import engine

    await engine.dispose()
    yield
    await engine.dispose()


async def _organisation(db, nom: str) -> Organization:
    organisation = Organization(name=nom, slug=f"be029-{uuid.uuid4().hex[:12]}", status="active")
    db.add(organisation)
    await db.flush()
    return organisation


async def _tentative(db, organization_id: uuid.UUID) -> PaymentAttempt:
    """Organisation réelle : abonnement, facture et tentative de paiement en statut `pending`."""
    await db.execute(text(
        'INSERT INTO module (id, code, name, version, "createdAt", "updatedAt") '
        "VALUES (:id, 'zylo_liquid', 'Zylo Liquid', '0.1.0', now(), now()) ON CONFLICT (code) DO NOTHING"
    ), {"id": uuid.uuid4()})
    plan = await service.get_or_create_plan(
        db, "zylo_liquid", f"be029-{uuid.uuid4().hex[:10]}", "Plan BE-029", 0, "XAF", 30
    )
    version = await service.ensure_initial_plan_version(db, plan)
    now = datetime.now(timezone.utc)
    subscription = Subscription(
        organizationId=organization_id, planId=plan.id, planVersionId=version.id, status="active",
        startDate=now, endDate=now + timedelta(days=30),
    )
    db.add(subscription)
    await db.flush()
    invoice = Invoice(
        subscriptionId=subscription.id, amountCents=1000, currency="XAF", status="pending", issuedAt=now,
    )
    db.add(invoice)
    await db.flush()
    attempt = PaymentAttempt(
        invoiceId=invoice.id, provider="flutterwave", mode="test", idempotencyKey=uuid.uuid4().hex,
        amountMinor=1000, currency="XAF", status="pending", requestedAt=now,
    )
    db.add(attempt)
    await db.commit()
    return attempt


def _corps(event_id: str, tx_ref: str, *, statut: str = "successful", type_evt: str = "charge.completed", data_id: int = 42) -> bytes:
    payload = {"id": event_id, "event": type_evt, "data": {"id": data_id, "tx_ref": tx_ref, "status": statut}}
    return json.dumps(payload).encode("utf-8")


async def _statut_tentative(attempt_id: uuid.UUID) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.scalar(select(PaymentAttempt.status).where(PaymentAttempt.id == attempt_id)))


async def _nombre_evenements(event_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return len((await db.scalars(
            select(PaymentWebhookEvent.id).where(PaymentWebhookEvent.eventId == event_id)
        )).all())


async def _nombre_entitlements(organization_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count()).select_from(SubscriptionEntitlement)
            .where(SubscriptionEntitlement.organizationId == organization_id)
        )


async def _remettre_en_attente(attempt_id: uuid.UUID) -> None:
    """Simule une tentative revenue à `pending` : un second effet serait alors visible."""
    async with AsyncSessionLocal() as db:
        attempt = await db.get(PaymentAttempt, attempt_id)
        attempt.status = "pending"
        await db.commit()


# --- CA-1 : idempotence -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ca1_evenement_recu_deux_fois_ne_produit_qu_un_effet():
    """CA-1 : le second envoi d'un même évènement est un doublon ; l'effet n'est pas rejoué."""
    async with AsyncSessionLocal() as db:
        org = await _organisation(db, "Org BE-029 CA-1")
        tentative = await _tentative(db, org.id)
    event_id = f"evt-{uuid.uuid4().hex}"
    corps = _corps(event_id, str(tentative.id))

    async with AsyncSessionLocal() as db:
        premier = await traiter_evenement_webhook(db, corps=corps, signature_verifiee=True)
    assert premier.duplicate is False
    assert await _statut_tentative(tentative.id) == "reported_successful"

    await _remettre_en_attente(tentative.id)
    async with AsyncSessionLocal() as db:
        second = await traiter_evenement_webhook(db, corps=corps, signature_verifiee=True)

    assert second.duplicate is True
    assert await _nombre_evenements(event_id) == 1
    assert await _statut_tentative(tentative.id) == "pending"


# --- CA-2 : référence inconnue (refus) ----------------------------------------------------


@pytest.mark.asyncio
async def test_ca2_reference_inconnue_refusee_sans_ecriture():
    """CA-2 : référence inconnue -> 404 `webhook_reference_unknown`, aucune ligne écrite."""
    event_id = f"evt-{uuid.uuid4().hex}"
    avant = await _nombre_total_evenements()

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await traiter_evenement_webhook(db, corps=_corps(event_id, str(uuid.uuid4())), signature_verifiee=True)

    assert erreur.value.code == "webhook_reference_unknown"
    assert erreur.value.status_code == 404
    assert await _nombre_evenements(event_id) == 0
    assert await _nombre_total_evenements() == avant


async def _nombre_total_evenements() -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(PaymentWebhookEvent))


# --- CA-3 : évènement sans effet reconnu (refus d'entitlement) -----------------------------


@pytest.mark.asyncio
async def test_ca3_evenement_sans_effet_reconnu_n_accorde_aucun_entitlement():
    """CA-3 : un type d'évènement non reconnu est enregistré sans effet ni entitlement."""
    async with AsyncSessionLocal() as db:
        org = await _organisation(db, "Org BE-029 CA-3")
        tentative = await _tentative(db, org.id)
    avant = await _nombre_entitlements(org.id)
    event_id = f"evt-{uuid.uuid4().hex}"

    async with AsyncSessionLocal() as db:
        resultat = await traiter_evenement_webhook(
            db, corps=_corps(event_id, str(tentative.id), type_evt="customer.created"), signature_verifiee=True,
        )

    assert resultat.outcome == "ignored"
    assert await _nombre_entitlements(org.id) == avant
    assert await _statut_tentative(tentative.id) == "pending"


# --- CA-4 : isolation entre organisations --------------------------------------------------


@pytest.mark.asyncio
async def test_ca4_evenement_de_o2_jamais_applique_sous_o1():
    """CA-4 : sous le périmètre de O1, un évènement visant une tentative de O2 est refusé
    comme référence inconnue ; la tentative de O2 et O1 restent intactes."""
    async with AsyncSessionLocal() as db:
        o1 = await _organisation(db, "Org BE-029 O1")
        o2 = await _organisation(db, "Org BE-029 O2")
        tentative_o1 = await _tentative(db, o1.id)
        tentative_o2 = await _tentative(db, o2.id)
    event_id = f"evt-{uuid.uuid4().hex}"

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await traiter_evenement_webhook(
                db, corps=_corps(event_id, str(tentative_o2.id)), signature_verifiee=True,
                organisation_id=o1.id,
            )

    assert erreur.value.code == "webhook_reference_unknown"
    assert await _statut_tentative(tentative_o2.id) == "pending"
    assert await _statut_tentative(tentative_o1.id) == "pending"
    assert await _nombre_evenements(event_id) == 0


@pytest.mark.asyncio
async def test_ca4_sans_perimetre_l_effet_reste_sur_la_tentative_de_o2():
    """CA-4 (complément) : sans périmètre, l'effet ne touche que la tentative référencée (O2)."""
    async with AsyncSessionLocal() as db:
        o1 = await _organisation(db, "Org BE-029 O1 bis")
        o2 = await _organisation(db, "Org BE-029 O2 bis")
        tentative_o1 = await _tentative(db, o1.id)
        tentative_o2 = await _tentative(db, o2.id)

    async with AsyncSessionLocal() as db:
        await traiter_evenement_webhook(
            db, corps=_corps(f"evt-{uuid.uuid4().hex}", str(tentative_o2.id)), signature_verifiee=True,
        )

    assert await _statut_tentative(tentative_o2.id) == "reported_successful"
    assert await _statut_tentative(tentative_o1.id) == "pending"
    assert await _nombre_entitlements(o2.id) == 0


# --- CA-5 : quarantaine d'un évènement contradictoire --------------------------------------


@pytest.mark.asyncio
async def test_ca5_evenement_contradictoire_mis_en_quarantaine_et_non_applique():
    """CA-5 : même identifiant fournisseur, contenu différent -> 409 `webhook_event_conflict`,
    évènement marqué `quarantined`, et aucun effet du second contenu."""
    async with AsyncSessionLocal() as db:
        org = await _organisation(db, "Org BE-029 CA-5")
        tentative = await _tentative(db, org.id)
    event_id = f"evt-{uuid.uuid4().hex}"

    async with AsyncSessionLocal() as db:
        await traiter_evenement_webhook(
            db, corps=_corps(event_id, str(tentative.id), statut="successful"), signature_verifiee=True,
        )
    assert await _statut_tentative(tentative.id) == "reported_successful"

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await traiter_evenement_webhook(
                db, corps=_corps(event_id, str(tentative.id), statut="failed"), signature_verifiee=True,
            )

    assert erreur.value.code == "webhook_event_conflict"
    assert erreur.value.status_code == 409
    async with AsyncSessionLocal() as db:
        ligne = await db.scalar(select(PaymentWebhookEvent).where(PaymentWebhookEvent.eventId == event_id))
    assert ligne.outcome == "quarantined"
    assert ligne.quarantinedAt is not None
    assert ligne.quarantineDigest is not None
    assert ligne.quarantineDigest != ligne.payloadDigest
    assert await _statut_tentative(tentative.id) == "reported_successful"


# --- Refus transversal : évènement non vérifié ----------------------------------------------


@pytest.mark.asyncio
async def test_evenement_non_verifie_jamais_traite():
    """BE-029 ne traite que des évènements vérifiés : signature non vérifiée -> refus, rien d'écrit."""
    async with AsyncSessionLocal() as db:
        org = await _organisation(db, "Org BE-029 non verifie")
        tentative = await _tentative(db, org.id)
    event_id = f"evt-{uuid.uuid4().hex}"

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await traiter_evenement_webhook(
                db, corps=_corps(event_id, str(tentative.id)), signature_verifiee=False,
            )

    assert erreur.value.code == "webhook_signature_invalid"
    assert await _nombre_evenements(event_id) == 0
    assert await _statut_tentative(tentative.id) == "pending"


async def creer_tentative_de_test(nom: str = "Org BE-029 partage") -> uuid.UUID:
    """Identifiant d'une tentative `pending` réelle, pour les autres suites de webhook."""
    async with AsyncSessionLocal() as db:
        org = await _organisation(db, nom)
        tentative = await _tentative(db, org.id)
    return tentative.id
