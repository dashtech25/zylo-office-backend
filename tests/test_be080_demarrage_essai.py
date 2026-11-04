"""BE-080 : démarrage d'essai (POST /api/v1/billing/subscriptions/trials).

Intention : prouver les critères d'acceptation de BE-080
(implementation-backend/tasks-abonnements-facturation.md, section BE-080), écrits d'après
la définition avant le code :
- CA-1 : sans consentement enregistré, la requête renvoie `CONSENT_REQUIRED` et ne crée
  aucun abonnement en essai (l'abonnement reste `pending`) ;
- CA-2 : avec consentement, l'abonnement passe à `trialing` et `TrialStarted` est publié ;
- CA-3 : un membre sans permission d'abonnement reçoit `FORBIDDEN` et rien n'est écrit ;
- CA-4 : un abonnement d'un autre tenant est répondu comme un abonnement inexistant ;
- CA-5 : le démarrage d'un essai ne modifie pas les droits d'accès.

Hors périmètre de ce fichier : la base de consentement elle-même (BE-076) et la table
d'outbox (BE-234) ; voir le module app/billing/trials pour l'état de la publication.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.billing import service
from app.billing.models import BillingPayer, ConsentRecord, Subscription
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.rbac.service import list_effective_permission_codes
from app.shared import events as bus

MOT_DE_PASSE = "TestPassword123!"
VERSION_TEXTE = "CGV-2026-11"
TYPE_EVENEMENT_ESSAI = "TrialStarted"
URL_ESSAI = "/api/v1/billing/subscriptions/trials"


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _fin_essai() -> str:
    """Date de fin d'essai demandée : 14 jours, fuseau explicite (QE-FAC-05, UTC stocké)."""
    return (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()


async def _abonnement_en_attente(tenant_id: uuid.UUID, lifecycle: str = "pending") -> tuple[uuid.UUID, uuid.UUID]:
    """Payeur rattaché au tenant par un abonnement dans l'axe lifecycle donné.

    Renvoie (identifiant de l'abonnement, identifiant du payeur).
    """
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        payeur = BillingPayer(payerKind="organisation", accountRef=f"be080-{uuid.uuid4().hex[:10]}")
        db.add(payeur)
        await db.flush()
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be080-{uuid.uuid4().hex[:10]}", "Plan BE-080", 1000, "XAF", 30
        )
        abonnement = Subscription(
            organizationId=tenant_id,
            planId=plan.id,
            status="trial",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
            payerId=payeur.id,
            beneficiaryTenantId=tenant_id,
            lifecycleStatus=lifecycle,
        )
        db.add(abonnement)
        await db.commit()
        return abonnement.id, payeur.id


async def _enregistrer_consentement_direct(payeur_id: uuid.UUID, personne_email: str) -> None:
    """Pose un consentement déjà enregistré (ligne BE-076) pour le compte."""
    async with AsyncSessionLocal() as db:
        personne = await db.scalar(select(User.id).where(User.email == personne_email))
        db.add(ConsentRecord(
            personId=personne, accountId=payeur_id, consentTextVersion=VERSION_TEXTE, scope="payeur",
        ))
        await db.commit()


async def _nombre_consentements(payeur_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count()).select_from(ConsentRecord).where(ConsentRecord.accountId == payeur_id)
        )


async def _lire_abonnement(subscription_id: uuid.UUID) -> Subscription:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Subscription).where(Subscription.id == subscription_id))


async def _membre_sans_droit(client: AsyncClient, organization_id: uuid.UUID) -> tuple[str, str]:
    """Membre rattaché à l'organisation, sans rôle ; renvoie (jeton, courriel)."""
    email = f"be080-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    cree = await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Membre BE-080"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=uuid.UUID(cree.json()["id"])))
        await db.commit()
    return login.json()["accessToken"], email


async def _organisation_d_un_autre_tenant(client: AsyncClient) -> tuple[str, str]:
    """Organisation B créée par un autre utilisateur ; renvoie (identifiant, jeton du propriétaire)."""
    email = f"be080-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Tenant B"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jeton = login.json()["accessToken"]
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"be080-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {jeton}"},
    )
    return res.json()["id"], jeton


async def _droits(tenant_id: uuid.UUID, email: str) -> list[str]:
    async with AsyncSessionLocal() as db:
        utilisateur = await db.scalar(select(User).where(User.email == email))
        return await list_effective_permission_codes(db, tenant_id, utilisateur.id)


@pytest.fixture
def evenements_essai(monkeypatch):
    """Capte les enveloppes `TrialStarted` distribuées par le bus pendant le test."""
    recus: list = []

    async def capter(enveloppe):
        recus.append(enveloppe)

    bus.subscribe(TYPE_EVENEMENT_ESSAI, capter)
    yield recus
    bus._handlers[TYPE_EVENEMENT_ESSAI].remove(capter)


# CA-1 : sans consentement enregistré, CONSENT_REQUIRED et aucun abonnement créé.

async def test_ca1_sans_consentement_renvoie_consent_required(
    client: AsyncClient, registered_user: dict, organization: dict, evenements_essai
):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id, payeur_id = await _abonnement_en_attente(tenant_id)
    avant = await _lire_abonnement(abonnement_id)

    reponse = await client.post(
        URL_ESSAI,
        json={"subscriptionId": str(abonnement_id), "trialEnd": _fin_essai()},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 422
    assert reponse.json()["error"]["code"] == "CONSENT_REQUIRED"
    apres = await _lire_abonnement(abonnement_id)
    assert apres.lifecycleStatus == "pending"
    assert apres.version == avant.version
    assert apres.endDate == avant.endDate
    assert evenements_essai == []


# CA-2 : avec consentement, trialing et TrialStarted publié.

async def test_ca2_avec_consentement_enregistre_l_essai_demarre(
    client: AsyncClient, registered_user: dict, organization: dict, evenements_essai
):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id, payeur_id = await _abonnement_en_attente(tenant_id)
    await _enregistrer_consentement_direct(payeur_id, registered_user["email"])
    fin = _fin_essai()
    avant = await _lire_abonnement(abonnement_id)

    reponse = await client.post(
        URL_ESSAI,
        json={"subscriptionId": str(abonnement_id), "trialEnd": fin},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["lifecycleStatus"] == "trialing"
    apres = await _lire_abonnement(abonnement_id)
    assert apres.lifecycleStatus == "trialing"
    assert apres.version == avant.version + 1
    assert apres.endDate == datetime.fromisoformat(fin).astimezone(timezone.utc)
    evenements = [e for e in evenements_essai if e.payload.get("subscriptionId") == str(abonnement_id)]
    assert len(evenements) == 1
    assert evenements[0].tenantId == tenant_id


async def test_ca2_consentement_fourni_dans_la_requete_est_enregistre_puis_l_essai_demarre(
    client: AsyncClient, registered_user: dict, organization: dict, evenements_essai
):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id, payeur_id = await _abonnement_en_attente(tenant_id)
    assert await _nombre_consentements(payeur_id) == 0

    reponse = await client.post(
        URL_ESSAI,
        json={
            "subscriptionId": str(abonnement_id),
            "trialEnd": _fin_essai(),
            "consent": {"consentTextVersion": VERSION_TEXTE, "scope": "payeur"},
        },
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 200, reponse.text
    assert await _nombre_consentements(payeur_id) == 1
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "trialing"


# CA-3 : un membre sans permission d'abonnement reçoit FORBIDDEN, rien n'est écrit.

async def test_ca3_membre_sans_permission_recoit_forbidden(
    client: AsyncClient, registered_user: dict, organization: dict, evenements_essai
):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id, payeur_id = await _abonnement_en_attente(tenant_id)
    await _enregistrer_consentement_direct(payeur_id, registered_user["email"])
    jeton, _ = await _membre_sans_droit(client, tenant_id)

    reponse = await client.post(
        URL_ESSAI,
        json={"subscriptionId": str(abonnement_id), "trialEnd": _fin_essai()},
        headers=_entete(jeton, organization["id"]),
    )

    assert reponse.status_code == 403
    assert reponse.json()["error"]["code"] == "FORBIDDEN"
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "pending"
    assert evenements_essai == []


# CA-4 : un abonnement du tenant A est répondu comme inexistant au scope B.

async def test_ca4_abonnement_d_un_autre_tenant_repond_comme_inexistant(
    client: AsyncClient, registered_user: dict, organization: dict, evenements_essai
):
    tenant_a = uuid.UUID(organization["id"])
    abonnement_id, payeur_id = await _abonnement_en_attente(tenant_a)
    await _enregistrer_consentement_direct(payeur_id, registered_user["email"])
    tenant_b, jeton_b = await _organisation_d_un_autre_tenant(client)
    corps = {"subscriptionId": str(abonnement_id), "trialEnd": _fin_essai()}

    hors_perimetre = await client.post(URL_ESSAI, json=corps, headers=_entete(jeton_b, tenant_b))
    inexistant = await client.post(
        URL_ESSAI, json={**corps, "subscriptionId": str(uuid.uuid4())}, headers=_entete(jeton_b, tenant_b)
    )

    assert hors_perimetre.status_code == inexistant.status_code == 404
    assert hors_perimetre.json()["error"]["code"] == inexistant.json()["error"]["code"]
    assert hors_perimetre.json()["error"]["message"] == inexistant.json()["error"]["message"]
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "pending"
    assert evenements_essai == []


# CA-5 : le démarrage d'un essai ne crée aucun droit d'accès.

async def test_ca5_demarrage_d_essai_ne_modifie_pas_les_droits(
    client: AsyncClient, registered_user: dict, organization: dict, evenements_essai
):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id, payeur_id = await _abonnement_en_attente(tenant_id)
    await _enregistrer_consentement_direct(payeur_id, registered_user["email"])
    droits_avant = await _droits(tenant_id, registered_user["email"])

    reponse = await client.post(
        URL_ESSAI,
        json={"subscriptionId": str(abonnement_id), "trialEnd": _fin_essai()},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 200, reponse.text
    assert await _droits(tenant_id, registered_user["email"]) == droits_avant


# Transition absente de la machine : un abonnement déjà en essai ne redémarre pas.

async def test_essai_deja_demarre_renvoie_invalid_transition_sans_consentement_nouveau(
    client: AsyncClient, registered_user: dict, organization: dict, evenements_essai
):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id, payeur_id = await _abonnement_en_attente(tenant_id, lifecycle="trialing")
    avant = await _nombre_consentements(payeur_id)

    reponse = await client.post(
        URL_ESSAI,
        json={
            "subscriptionId": str(abonnement_id),
            "trialEnd": _fin_essai(),
            "consent": {"consentTextVersion": VERSION_TEXTE, "scope": "payeur"},
        },
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 409
    assert reponse.json()["error"]["code"] == "INVALID_TRANSITION"
    assert await _nombre_consentements(payeur_id) == avant
    assert evenements_essai == []
