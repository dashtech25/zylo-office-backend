"""BE-097 : clôture d'abonnement (close operation).

Intention : prouver les critères d'acceptation de BE-097
(implementation-backend/tasks-abonnements-facturation.md, section BE-097) :
- CA-1 : `subscription_closed` n'est écrit qu'après vérification de chaque prérequis requis
  (finance, droits, données) ; un prérequis manquant bloque la clôture et laisse
  `close_pending_*` ;
- CA-2 : un cas support ouvert n'empêche pas la clôture (non bloquant) ;
- CA-3 : sans permission, `FORBIDDEN` et l'abonnement reste inchangé ;
- CA-4 : un abonnement d'un autre tenant est répondu comme un abonnement inexistant.

La clôture ne se déclenche que depuis `cancelled` ou `expired` (app/billing/subscriptions/etats.py) ;
un abonnement actif ou résilié à échéance n'est pas clôturable (INVALID_TRANSITION).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.billing import service
from app.billing.models import (
    BillingPayer,
    DataExportRequest,
    EntitlementSync,
    Invoice,
    PaymentAttempt,
    Subscription,
)
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import Organization, OrganizationUser, User
from app.rbac.service import list_effective_permission_codes

ACTION_AUDIT_CLOTURE = "billing.subscription.close"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


async def _creer_abonnement(
    tenant_id: uuid.UUID,
    lifecycle: str = "cancelled",
    financial: str = "settled",
    incident: str = "none",
    payer_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Abonnement du tenant, période de 30 jours, axes posés explicitement."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be097-{uuid.uuid4().hex[:8]}", "Plan BE-097", 1000, "XAF", 30
        )
        abonnement = Subscription(
            organizationId=tenant_id,
            planId=plan.id,
            status="active",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
            beneficiaryTenantId=tenant_id,
            payerId=payer_id,
            lifecycleStatus=lifecycle,
            financialStatus=financial,
            incidentStatus=incident,
        )
        db.add(abonnement)
        await db.commit()
        return abonnement.id


async def _lire_abonnement(subscription_id: uuid.UUID) -> Subscription:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Subscription).where(Subscription.id == subscription_id))


async def _lire_clotures(subscription_id: uuid.UUID) -> list:
    from app.billing.models import CloseOperation

    async with AsyncSessionLocal() as db:
        resultat = await db.scalars(select(CloseOperation).where(CloseOperation.subscriptionId == subscription_id))
        return list(resultat)


async def _entrees_audit_cloture(subscription_id: uuid.UUID) -> list[AuditEvent]:
    async with AsyncSessionLocal() as db:
        resultat = await db.scalars(
            select(AuditEvent).where(
                AuditEvent.entityId == subscription_id,
                AuditEvent.action == ACTION_AUDIT_CLOTURE,
            )
        )
        return list(resultat)


async def _ajouter_synchronisation(subscription_id: uuid.UUID, statut: str) -> None:
    """Demande de synchronisation des droits déjà au statut donné (BE-085)."""
    async with AsyncSessionLocal() as db:
        db.add(
            EntitlementSync(
                subscriptionId=subscription_id,
                status=statut,
                attempts=1,
                lastErrorCode=None,
                requestedAt=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def _ajouter_tentative_inconnue(subscription_id: uuid.UUID) -> None:
    """Facture de l'abonnement dont la tentative de paiement est restée `unknown` (BE-082)."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        facture = Invoice(subscriptionId=subscription_id, amountCents=1000, issuedAt=maintenant)
        db.add(facture)
        await db.flush()
        db.add(
            PaymentAttempt(
                invoiceId=facture.id,
                provider="test",
                idempotencyKey=uuid.uuid4().hex,
                amountMinor=1000,
                currency="XAF",
                status="unknown",
                requestedAt=maintenant,
            )
        )
        await db.commit()


async def _creer_payeur() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        payeur = BillingPayer(payerKind="organisation", accountRef=f"be097-{uuid.uuid4().hex[:10]}")
        db.add(payeur)
        await db.commit()
        return payeur.id


async def _ajouter_demande_export(tenant_id: uuid.UUID, payeur_id: uuid.UUID, demandeur_id: uuid.UUID, statut: str) -> None:
    """Demande d'export du payeur, au statut donné (BE-098 ne produit que `ready`)."""
    async with AsyncSessionLocal() as db:
        db.add(
            DataExportRequest(
                organizationId=tenant_id,
                accountId=payeur_id,
                scope="payeur",
                requestedBy=demandeur_id,
                status=statut,
            )
        )
        await db.commit()


async def _inscrire_et_connecter(client, email: str) -> str:
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Membre"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return login.json()["accessToken"]


async def _ajouter_membre_sans_droit(organization_id: str, email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        utilisateur = await db.scalar(select(User).where(User.email == email))
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=utilisateur.id))
        await db.commit()
        return utilisateur.id


async def _identifiant_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.scalar(select(User).where(User.email == email))).id


async def _droits(tenant_id: uuid.UUID, registered_user) -> list[str]:
    async with AsyncSessionLocal() as db:
        utilisateur = await db.scalar(select(User).where(User.email == registered_user["email"]))
        return await list_effective_permission_codes(db, tenant_id, utilisateur.id)


def _entete(token: str, organization_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _url(subscription_id: uuid.UUID) -> str:
    return f"/api/v1/billing/subscriptions/{subscription_id}/close"


# CA-1 : `subscription_closed` seulement après vérification de chaque prérequis requis.

async def test_ca1_cloture_bloquee_par_etat_financier_en_attente(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, financial="pending")
    await _ajouter_synchronisation(abonnement_id, "applied")

    reponse = await client.post(_url(abonnement_id), headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["status"] == "close_pending_finance"
    assert corps["lifecycleStatus"] == "close_pending"
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "close_pending"
    assert await _entrees_audit_cloture(abonnement_id) == []


async def test_ca1_cloture_bloquee_par_paiement_inconnu(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, financial="settled")
    await _ajouter_synchronisation(abonnement_id, "applied")
    await _ajouter_tentative_inconnue(abonnement_id)

    reponse = await client.post(_url(abonnement_id), headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["status"] == "close_pending_finance"
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "close_pending"


async def test_ca1_cloture_bloquee_par_droits_non_confirmes_et_demande_la_synchronisation(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, financial="settled")
    entete = _entete(registered_user["accessToken"], organization["id"])

    premiere = await client.post(_url(abonnement_id), headers=entete)
    seconde = await client.post(_url(abonnement_id), headers=entete)

    assert premiere.status_code == 200, premiere.text
    assert premiere.json()["status"] == "close_pending_entitlement"
    assert seconde.json()["status"] == "close_pending_entitlement"
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "close_pending"
    async with AsyncSessionLocal() as db:
        synchronisations = list(await db.scalars(select(EntitlementSync).where(EntitlementSync.subscriptionId == abonnement_id)))
    # Une seule demande PH-09 : la reprise ne crée pas de doublon tant qu'une demande est en cours.
    assert len(synchronisations) == 1
    assert synchronisations[0].status == "requested"


async def test_ca1_cloture_bloquee_par_demande_d_export_non_produite(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    payeur_id = await _creer_payeur()
    abonnement_id = await _creer_abonnement(tenant_id, financial="settled", payer_id=payeur_id)
    await _ajouter_synchronisation(abonnement_id, "applied")
    demandeur_id = await _identifiant_utilisateur(registered_user["email"])
    await _ajouter_demande_export(tenant_id, payeur_id, demandeur_id, "requested")

    reponse = await client.post(_url(abonnement_id), headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["status"] == "close_pending_data"
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "close_pending"


async def test_ca1_cloture_complete_quand_tous_les_prerequis_sont_verifies(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, financial="settled")
    await _ajouter_synchronisation(abonnement_id, "applied")
    avant = await _lire_abonnement(abonnement_id)

    reponse = await client.post(_url(abonnement_id), headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["status"] == "completed"
    assert corps["lifecycleStatus"] == "subscription_closed"
    assert set(corps["prerequisitesJson"]) == {"finance", "entitlement", "data"}
    apres = await _lire_abonnement(abonnement_id)
    assert apres.lifecycleStatus == "subscription_closed"
    assert apres.version > avant.version
    entrees = await _entrees_audit_cloture(abonnement_id)
    assert len(entrees) == 1


async def test_ca1_cloture_rejouee_renvoie_la_meme_operation_sans_nouvelle_ecriture(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, financial="settled")
    await _ajouter_synchronisation(abonnement_id, "applied")
    entete = _entete(registered_user["accessToken"], organization["id"])

    premiere = await client.post(_url(abonnement_id), headers=entete)
    rejeu = await client.post(_url(abonnement_id), headers=entete)

    assert premiere.json()["id"] == rejeu.json()["id"]
    assert rejeu.json()["status"] == "completed"
    assert len(await _lire_clotures(abonnement_id)) == 1
    assert len(await _entrees_audit_cloture(abonnement_id)) == 1


async def test_ca1_abonnement_non_resilie_n_est_pas_clôturable(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="active")

    reponse = await client.post(_url(abonnement_id), headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["error"]["code"] == "INVALID_TRANSITION"
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "active"
    assert await _lire_clotures(abonnement_id) == []


# CA-2 : un cas support ouvert ne bloque jamais la clôture.

async def test_ca2_cas_support_ouvert_ne_bloque_pas_la_cloture(client, registered_user, organization):
    """Aucun cas de facturation (BE-096) n'est modélisé : la clôture ne lit aucun cas et n'a donc
    aucun prérequis « cas ». Le test vérifie que les prérequis enregistrés sont uniquement
    finance, droits et données, et que la clôture aboutit sans cas."""
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, financial="settled")
    await _ajouter_synchronisation(abonnement_id, "applied")

    reponse = await client.post(_url(abonnement_id), headers=_entete(registered_user["accessToken"], organization["id"]))

    assert reponse.json()["status"] == "completed"
    assert "case" not in reponse.json()["prerequisitesJson"]
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "subscription_closed"


# CA-3 : refus FORBIDDEN sans permission, abonnement inchangé.

async def test_ca3_cloture_sans_permission_renvoie_forbidden(client, registered_user, organization):
    email_membre = f"be097-membre-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token_membre = await _inscrire_et_connecter(client, email_membre)
    await _ajouter_membre_sans_droit(organization["id"], email_membre)
    abonnement_id = await _creer_abonnement(uuid.UUID(organization["id"]), financial="settled")
    await _ajouter_synchronisation(abonnement_id, "applied")
    avant = await _lire_abonnement(abonnement_id)

    reponse = await client.post(_url(abonnement_id), headers=_entete(token_membre, organization["id"]))

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"
    apres = await _lire_abonnement(abonnement_id)
    assert apres.lifecycleStatus == "cancelled"
    assert apres.version == avant.version
    assert await _lire_clotures(abonnement_id) == []


# CA-4 : abonnement d'un autre tenant répondu comme un abonnement inexistant.

async def test_ca4_cloture_hors_tenant_repond_comme_inexistant(client, registered_user, organization):
    headers_a = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    reponse_b = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"be097-b-{uuid.uuid4().hex[:8]}"},
        headers=headers_a,
    )
    tenant_b = reponse_b.json()["id"]
    abonnement_a = await _creer_abonnement(uuid.UUID(organization["id"]), financial="settled")
    await _ajouter_synchronisation(abonnement_a, "applied")

    reponse_hors_scope = await client.post(_url(abonnement_a), headers=_entete(registered_user["accessToken"], tenant_b))
    reponse_inexistante = await client.post(_url(uuid.uuid4()), headers=_entete(registered_user["accessToken"], tenant_b))

    assert reponse_hors_scope.status_code == 404, reponse_hors_scope.text
    assert reponse_hors_scope.status_code == reponse_inexistante.status_code
    assert reponse_hors_scope.json()["error"] == reponse_inexistante.json()["error"]
    assert (await _lire_abonnement(abonnement_a)).lifecycleStatus == "cancelled"
    assert await _lire_clotures(abonnement_a) == []
