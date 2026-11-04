"""BE-076 : consentements versionnés (POST /api/v1/billing/consents).

Intention : prouver par des tests les critères d'acceptation de BE-076
(implementation-backend/tasks-abonnements-facturation.md, section BE-076), écrits
d'après la définition avant le code :
- CA-1 : un consentement enregistré porte la version du texte, la personne, le
  compte, l'heure et le scope ;
- CA-2 : une correction crée une nouvelle entrée liée (`correctionOfId`) ; l'entrée
  d'origine reste inchangée (et la base refuse toute modification directe) ;
- CA-3 : un acteur sans permission d'acheteur reçoit `FORBIDDEN` ;
- CA-4 : un consentement pour un compte d'un autre tenant reçoit `SCOPE_MISMATCH`.

Le compte (`accountId`) est un `billing_payer` rattaché au tenant bénéficiaire par un
abonnement. Ce rattachement est la recommandation retenue faute de décision sur la
frontière compte payeur / tenant (QE-FAC-22).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from httpx import AsyncClient

from app.billing import service
from app.billing.models import BillingPayer, ConsentRecord, Subscription
from app.billing.permissions import BILLING_CONSENT_RECORD
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.rbac.service import create_grant

MOT_DE_PASSE = "TestPassword123!"
VERSION_TEXTE = "CGV-2026-11"


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(User.id).where(User.email == email))


async def _membre_sans_droit(client: AsyncClient, organization_id: uuid.UUID) -> str:
    """Utilisateur rattaché à l'organisation, sans rôle ni permission ; retourne son jeton."""
    cree = await client.post("/api/v1/auth/register", json={
        "email": f"be076-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-076",
    })
    login = await client.post("/api/v1/auth/login", json={"email": cree.json()["email"], "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=uuid.UUID(cree.json()["id"])))
        await db.commit()
    return login.json()["accessToken"]


async def _compte_payeur(tenant_id: uuid.UUID) -> uuid.UUID:
    """Compte payeur (`billing_payer`) rattaché au tenant par un abonnement actif."""
    async with AsyncSessionLocal() as db:
        payeur = BillingPayer(payerKind="organisation", accountRef=f"be076-{uuid.uuid4().hex[:10]}")
        db.add(payeur)
        await db.flush()
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be076-{uuid.uuid4().hex[:10]}", "Plan BE-076", 0, "XAF", 30
        )
        maintenant = datetime.now(timezone.utc)
        db.add(Subscription(
            organizationId=tenant_id, planId=plan.id, status="active",
            startDate=maintenant, endDate=maintenant + timedelta(days=30),
            payerId=payeur.id, beneficiaryTenantId=tenant_id,
        ))
        await db.commit()
        return payeur.id


async def _nombre_consentements() -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(ConsentRecord))


async def _ligne(consent_id: uuid.UUID) -> dict:
    async with AsyncSessionLocal() as db:
        ligne = await db.get(ConsentRecord, consent_id)
        return {
            "personId": ligne.personId, "accountId": ligne.accountId,
            "consentTextVersion": ligne.consentTextVersion, "scope": ligne.scope,
            "recordedAt": ligne.recordedAt, "correctionOfId": ligne.correctionOfId,
        }


async def test_ca1_consentement_porte_version_personne_compte_heure_et_scope(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : la réponse et la ligne persistée portent version du texte, personne, compte, heure, scope."""
    org_id = organization["id"]
    compte = await _compte_payeur(uuid.UUID(org_id))
    proprietaire = await _id_utilisateur(registered_user["email"])

    reponse = await client.post(
        "/api/v1/billing/consents",
        json={"accountId": str(compte), "consentTextVersion": VERSION_TEXTE, "scope": "payeur"},
        headers=_entete(registered_user["accessToken"], org_id),
    )

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert corps["consentTextVersion"] == VERSION_TEXTE
    assert corps["personId"] == str(proprietaire)
    assert corps["accountId"] == str(compte)
    assert corps["scope"] == "payeur"
    assert corps["recordedAt"] is not None
    assert corps["correctionOfId"] is None
    ligne = await _ligne(uuid.UUID(corps["id"]))
    assert ligne["personId"] == proprietaire
    assert ligne["accountId"] == compte
    assert ligne["consentTextVersion"] == VERSION_TEXTE
    assert ligne["scope"] == "payeur"


async def test_ca2_correction_cree_entree_liee_et_origine_inchangee(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : la correction est une nouvelle ligne liée ; l'origine est identique avant et après."""
    org_id = organization["id"]
    entete = _entete(registered_user["accessToken"], org_id)
    compte = await _compte_payeur(uuid.UUID(org_id))
    origine = await client.post(
        "/api/v1/billing/consents",
        json={"accountId": str(compte), "consentTextVersion": VERSION_TEXTE, "scope": "payeur"},
        headers=entete,
    )
    assert origine.status_code == 201, origine.text
    origine_id = uuid.UUID(origine.json()["id"])
    avant = await _ligne(origine_id)

    correction = await client.post(
        "/api/v1/billing/consents",
        json={
            "accountId": str(compte), "consentTextVersion": "CGV-2026-12", "scope": "payeur",
            "correctionOfId": str(origine_id),
        },
        headers=entete,
    )

    assert correction.status_code == 201, correction.text
    correction_id = uuid.UUID(correction.json()["id"])
    assert correction_id != origine_id
    assert (await _ligne(correction_id))["correctionOfId"] == origine_id
    assert await _ligne(origine_id) == avant


async def test_ca2_base_refuse_modification_directe_d_un_consentement(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 (append-only) : un UPDATE ou DELETE direct sur consent_record est refusé par la base."""
    org_id = organization["id"]
    compte = await _compte_payeur(uuid.UUID(org_id))
    reponse = await client.post(
        "/api/v1/billing/consents",
        json={"accountId": str(compte), "consentTextVersion": VERSION_TEXTE, "scope": "payeur"},
        headers=_entete(registered_user["accessToken"], org_id),
    )
    consent_id = reponse.json()["id"]

    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError, match="immuable"):
            await db.execute(text("UPDATE consent_record SET \"consentTextVersion\" = 'X' WHERE id = :id"), {"id": consent_id})
        await db.rollback()
    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError, match="immuable"):
            await db.execute(text("DELETE FROM consent_record WHERE id = :id"), {"id": consent_id})
        await db.rollback()
    assert (await _ligne(uuid.UUID(consent_id)))["consentTextVersion"] == VERSION_TEXTE


async def test_ca3_acteur_sans_permission_d_acheteur_recoit_forbidden(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 : un membre sans la permission d'acheteur reçoit 403 FORBIDDEN ; rien n'est écrit."""
    org_id = uuid.UUID(organization["id"])
    compte = await _compte_payeur(org_id)
    jeton_sans_droit = await _membre_sans_droit(client, org_id)
    avant = await _nombre_consentements()

    reponse = await client.post(
        "/api/v1/billing/consents",
        json={"accountId": str(compte), "consentTextVersion": VERSION_TEXTE, "scope": "payeur"},
        headers=_entete(jeton_sans_droit, str(org_id)),
    )

    assert reponse.status_code == 403
    assert reponse.json()["error"]["code"] == "FORBIDDEN"
    assert await _nombre_consentements() == avant


async def test_ca3_permission_accordee_explicitement_permet_le_consentement(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 (complément) : la permission `billing.consent.record` accordée à un membre suffit."""
    org_id = uuid.UUID(organization["id"])
    compte = await _compte_payeur(org_id)
    jeton = await _membre_sans_droit(client, org_id)
    async with AsyncSessionLocal() as db:
        membre = await db.scalar(select(User.id).join(OrganizationUser, OrganizationUser.userId == User.id)
                                 .where(OrganizationUser.organizationId == org_id, User.email != registered_user["email"])
                                 .order_by(User.createdAt.desc()))
        proprietaire = await _id_utilisateur(registered_user["email"])
        await create_grant(db, org_id, proprietaire, membre, BILLING_CONSENT_RECORD, "allow")
        await db.commit()

    reponse = await client.post(
        "/api/v1/billing/consents",
        json={"accountId": str(compte), "consentTextVersion": VERSION_TEXTE, "scope": "payeur"},
        headers=_entete(jeton, str(org_id)),
    )

    assert reponse.status_code == 201, reponse.text


async def test_ca4_compte_d_un_autre_tenant_recoit_scope_mismatch(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : le propriétaire du tenant B ne peut pas consentir pour un compte du tenant A."""
    tenant_a = uuid.UUID(organization["id"])
    compte_a = await _compte_payeur(tenant_a)
    autre = await client.post("/api/v1/auth/register", json={
        "email": f"be076-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Tenant B BE-076",
    })
    login = await client.post("/api/v1/auth/login", json={"email": autre.json()["email"], "password": MOT_DE_PASSE})
    token_b = login.json()["accessToken"]
    org_b = await client.post("/api/v1/organizations", json={
        "name": "Tenant B", "slug": f"be076-b-{uuid.uuid4().hex[:8]}",
    }, headers={"Authorization": f"Bearer {token_b}"})
    org_b_id = org_b.json()["id"]
    avant = await _nombre_consentements()

    reponse = await client.post(
        "/api/v1/billing/consents",
        json={"accountId": str(compte_a), "consentTextVersion": VERSION_TEXTE, "scope": "payeur"},
        headers=_entete(token_b, org_b_id),
    )

    assert reponse.status_code == 403
    assert reponse.json()["error"]["code"] == "SCOPE_MISMATCH"
    assert await _nombre_consentements() == avant


async def test_compte_inexistant_et_compte_d_un_autre_tenant_repondent_pareil(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 (non-fuite) : un compte inexistant reçoit la même réponse qu'un compte hors scope."""
    org_id = organization["id"]
    reponse = await client.post(
        "/api/v1/billing/consents",
        json={"accountId": str(uuid.uuid4()), "consentTextVersion": VERSION_TEXTE, "scope": "payeur"},
        headers=_entete(registered_user["accessToken"], org_id),
    )

    assert reponse.status_code == 403
    assert reponse.json()["error"]["code"] == "SCOPE_MISMATCH"


async def test_correction_d_un_consentement_d_un_autre_compte_recoit_scope_mismatch(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 + CA-4 : `correctionOfId` pointant un consentement d'un autre compte est refusé."""
    org_id = organization["id"]
    entete = _entete(registered_user["accessToken"], org_id)
    compte_1 = await _compte_payeur(uuid.UUID(org_id))
    compte_2 = await _compte_payeur(uuid.UUID(org_id))
    origine = await client.post(
        "/api/v1/billing/consents",
        json={"accountId": str(compte_1), "consentTextVersion": VERSION_TEXTE, "scope": "payeur"},
        headers=entete,
    )
    avant = await _nombre_consentements()

    reponse = await client.post(
        "/api/v1/billing/consents",
        json={
            "accountId": str(compte_2), "consentTextVersion": VERSION_TEXTE, "scope": "payeur",
            "correctionOfId": origine.json()["id"],
        },
        headers=entete,
    )

    assert reponse.status_code == 403
    assert reponse.json()["error"]["code"] == "SCOPE_MISMATCH"
    assert await _nombre_consentements() == avant
