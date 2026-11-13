"""BE-091 : échec de paiement, grâce et suspension (axe `incidentStatus`).

Intention : prouver les critères d'acceptation de BE-091
(implementation-backend/tasks-abonnements-facturation.md, section BE-091) :
- CA-1 : un échec `failed` fait passer `incidentStatus` à `past_due` et émet l'événement
  `Billing.PaymentAttemptFailed`, sans toucher à `lifecycleStatus` ni à `financialStatus` ;
- CA-2 : aucune suspension automatique : aucun appel aux fonctions de synchronisation des
  droits (BE-085) et `incidentStatus` reste `past_due`, `graceUntil` reste vide ;
- CA-3 : une suspension manuelle sans permission `billing.subscription.manage` renvoie
  `FORBIDDEN` et ne modifie rien ;
- CA-4 : l'incident d'un tenant n'affecte pas un autre tenant (réponse de l'inexistant).

Le fournisseur n'est pas appelé : les tentatives sont posées directement en base à `failed`.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.billing import service
from app.billing.incidents.service import appliquer_echec_paiement, suspendre_manuellement
from app.billing.models import Invoice, PaymentAttempt, Subscription
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.evenements.models import OutboxEvenement
from app.identity.models import Organization, OrganizationUser, User


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


async def _creer_organisation_isolee() -> uuid.UUID:
    """Organisation sans lien HTTP, pour les tests de service (tenant B)."""
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="be091", slug=f"be091-{uuid.uuid4().hex[:10]}", status="active")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _creer_abonnement(tenant_id: uuid.UUID) -> uuid.UUID:
    """Abonnement actif du tenant, axes `financial` et `incident` à `none`."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be091-{uuid.uuid4().hex[:8]}", "Plan BE-091", 1000, "XAF", 30
        )
        abonnement = Subscription(
            organizationId=tenant_id,
            planId=plan.id,
            status="active",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
            beneficiaryTenantId=tenant_id,
            lifecycleStatus="active",
            financialStatus="none",
            incidentStatus="none",
        )
        db.add(abonnement)
        await db.commit()
        return abonnement.id


async def _creer_tentative_echouee(abonnement_id: uuid.UUID, statut: str = "failed") -> uuid.UUID:
    """Facture de l'abonnement et tentative de paiement rattachée, à l'état `statut`."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        facture = Invoice(
            subscriptionId=abonnement_id, amountCents=1500, amountMinor=1500, currency="XAF",
            status="pending", issuedAt=maintenant, idempotencyKey=f"be091-{uuid.uuid4().hex}",
        )
        db.add(facture)
        await db.flush()
        tentative = PaymentAttempt(
            invoiceId=facture.id, provider="fictif", mode="test",
            idempotencyKey=f"be091-{uuid.uuid4().hex}", amountMinor=1500, currency="XAF",
            status=statut, requestedAt=maintenant, version=1,
        )
        db.add(tentative)
        await db.commit()
        return tentative.id


async def _lire_abonnement(abonnement_id: uuid.UUID) -> Subscription:
    """Relit l'abonnement directement en base (pas de cache de session)."""
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Subscription).where(Subscription.id == abonnement_id))


async def _evenements_echec(tenant_id: uuid.UUID, tentative_id: uuid.UUID) -> list[OutboxEvenement]:
    """Événements `Billing.PaymentAttemptFailed` du tenant concernant cette tentative."""
    async with AsyncSessionLocal() as db:
        lignes = (await db.scalars(
            select(OutboxEvenement).where(
                OutboxEvenement.tenantId == tenant_id,
                OutboxEvenement.eventType == "Billing.PaymentAttemptFailed",
            )
        )).all()
    # La colonne `payload` de l'outbox porte l'enveloppe complète ; le contenu métier est sous `payload.payload`.
    return [ligne for ligne in lignes if ligne.payload["payload"].get("paymentAttemptId") == str(tentative_id)]


async def _ajouter_membre_sans_droit(organization_id: str, email: str) -> uuid.UUID:
    """Rattache un utilisateur à l'organisation sans aucun rôle (aucune permission billing)."""
    async with AsyncSessionLocal() as db:
        utilisateur = await db.scalar(select(User).where(User.email == email))
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=utilisateur.id))
        await db.commit()
        return utilisateur.id


# CA-1 : échec `failed` -> incident `past_due`, événement émis, autres axes intacts.

async def test_ca1_echec_failed_passe_incident_a_past_due_sans_toucher_au_cycle_de_vie(registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id)
    tentative_id = await _creer_tentative_echouee(abonnement_id)

    async with AsyncSessionLocal() as db:
        await appliquer_echec_paiement(db, tenant_id=tenant_id, subscription_id=abonnement_id, tentative_id=tentative_id)

    abonnement = await _lire_abonnement(abonnement_id)
    assert abonnement.incidentStatus == "past_due"
    assert abonnement.lifecycleStatus == "active"
    assert abonnement.financialStatus == "none"
    evenements = await _evenements_echec(tenant_id, tentative_id)
    assert len(evenements) == 1
    assert evenements[0].payload["payload"]["subscriptionId"] == str(abonnement_id)


async def test_ca1_rejeu_du_meme_echec_ne_cree_ni_second_evenement_ni_erreur(registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id)
    tentative_id = await _creer_tentative_echouee(abonnement_id)

    async with AsyncSessionLocal() as db:
        await appliquer_echec_paiement(db, tenant_id=tenant_id, subscription_id=abonnement_id, tentative_id=tentative_id)
    async with AsyncSessionLocal() as db:
        await appliquer_echec_paiement(db, tenant_id=tenant_id, subscription_id=abonnement_id, tentative_id=tentative_id)

    assert (await _lire_abonnement(abonnement_id)).incidentStatus == "past_due"
    assert len(await _evenements_echec(tenant_id, tentative_id)) == 1


async def test_ca1_tentative_non_echouee_ne_pose_aucun_incident(registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id)
    tentative_id = await _creer_tentative_echouee(abonnement_id, statut="unknown")

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await appliquer_echec_paiement(db, tenant_id=tenant_id, subscription_id=abonnement_id, tentative_id=tentative_id)

    assert erreur.value.code == "INVALID_TRANSITION"
    assert (await _lire_abonnement(abonnement_id)).incidentStatus == "none"
    assert await _evenements_echec(tenant_id, tentative_id) == []


# CA-2 : aucune suspension automatique, aucun appel suspensif à la synchronisation des droits.

async def test_ca2_aucune_suspension_automatique_et_aucun_appel_droits(monkeypatch, registered_user, organization):
    from app.billing.entitlement_sync import service as synchronisation

    appels: list[str] = []

    async def _espion(nom):
        async def _appel(*args, **kwargs):
            appels.append(nom)
        return _appel

    monkeypatch.setattr(synchronisation, "demander_synchronisation", await _espion("demander_synchronisation"))
    monkeypatch.setattr(synchronisation, "enregistrer_resultat", await _espion("enregistrer_resultat"))

    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id)
    tentative_id = await _creer_tentative_echouee(abonnement_id)

    async with AsyncSessionLocal() as db:
        await appliquer_echec_paiement(db, tenant_id=tenant_id, subscription_id=abonnement_id, tentative_id=tentative_id)

    assert appels == []
    abonnement = await _lire_abonnement(abonnement_id)
    assert abonnement.incidentStatus == "past_due"
    assert abonnement.graceUntil is None


# CA-3 : suspension manuelle sans permission -> FORBIDDEN ; avec permission -> autorisée.

async def test_ca3_suspension_manuelle_sans_permission_renvoie_forbidden(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id)
    tentative_id = await _creer_tentative_echouee(abonnement_id)
    async with AsyncSessionLocal() as db:
        await appliquer_echec_paiement(db, tenant_id=tenant_id, subscription_id=abonnement_id, tentative_id=tentative_id)

    email = f"be091-membre-{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "TestPassword123!", "fullName": "Membre"})
    membre_id = await _ajouter_membre_sans_droit(organization["id"], email)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await suspendre_manuellement(db, actor_user_id=membre_id, tenant_id=tenant_id, subscription_id=abonnement_id)

    assert erreur.value.code == "FORBIDDEN"
    assert (await _lire_abonnement(abonnement_id)).incidentStatus == "past_due"


async def test_ca3_suspension_manuelle_avec_permission_passe_a_suspended(registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    proprietaire_id = await _id_utilisateur(registered_user["email"])
    abonnement_id = await _creer_abonnement(tenant_id)
    tentative_id = await _creer_tentative_echouee(abonnement_id)
    async with AsyncSessionLocal() as db:
        await appliquer_echec_paiement(db, tenant_id=tenant_id, subscription_id=abonnement_id, tentative_id=tentative_id)

    async with AsyncSessionLocal() as db:
        abonnement = await suspendre_manuellement(
            db, actor_user_id=proprietaire_id, tenant_id=tenant_id, subscription_id=abonnement_id
        )

    assert abonnement.incidentStatus == "suspended"
    assert abonnement.lifecycleStatus == "active"


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.scalar(select(User).where(User.email == email))).id


# CA-4 : isolation tenant : l'incident d'un tenant n'affecte pas un autre tenant.

async def test_ca4_incident_d_un_tenant_n_affecte_pas_un_autre_tenant(registered_user, organization):
    tenant_a = uuid.UUID(organization["id"])
    tenant_b = await _creer_organisation_isolee()
    abonnement_a = await _creer_abonnement(tenant_a)
    abonnement_b = await _creer_abonnement(tenant_b)
    tentative_a = await _creer_tentative_echouee(abonnement_a)

    # Un échec du tenant A, traité dans le scope du tenant B : réponse de l'inexistant, aucune écriture.
    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await appliquer_echec_paiement(db, tenant_id=tenant_b, subscription_id=abonnement_a, tentative_id=tentative_a)
    assert erreur.value.code == "subscription_not_found"
    assert erreur.value.status_code == 404

    assert (await _lire_abonnement(abonnement_a)).incidentStatus == "none"
    assert (await _lire_abonnement(abonnement_b)).incidentStatus == "none"
    assert await _evenements_echec(tenant_a, tentative_a) == []


async def test_ca4_suspension_d_un_autre_tenant_repond_comme_inexistant(client, registered_user, organization):
    """Propriétaire réel du tenant B (permission présente) : la suspension de A reste « introuvable »."""
    tenant_a = uuid.UUID(organization["id"])
    abonnement_a = await _creer_abonnement(tenant_a)
    tentative_a = await _creer_tentative_echouee(abonnement_a)
    async with AsyncSessionLocal() as db:
        await appliquer_echec_paiement(db, tenant_id=tenant_a, subscription_id=abonnement_a, tentative_id=tentative_a)

    # Second tenant, créé par un autre utilisateur qui en est le propriétaire.
    email_b = f"be091-tenant-b-{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email_b, "password": "TestPassword123!", "fullName": "Tenant B"})
    login = await client.post("/api/v1/auth/login", json={"email": email_b, "password": "TestPassword123!"})
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"be091-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {login.json()['accessToken']}"},
    )
    tenant_b = uuid.UUID(res.json()["id"])
    proprietaire_b_id = await _id_utilisateur(email_b)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await suspendre_manuellement(db, actor_user_id=proprietaire_b_id, tenant_id=tenant_b, subscription_id=abonnement_a)

    assert erreur.value.code == "subscription_not_found"
    assert erreur.value.status_code == 404
    assert (await _lire_abonnement(abonnement_a)).incidentStatus == "past_due"
