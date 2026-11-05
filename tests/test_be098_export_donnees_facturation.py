"""BE-098 : demande d'export des données de facturation (POST /api/v1/billing/data-exports).

Intention : prouver les critères d'acceptation de BE-098
(implementation-backend/tasks-abonnements-facturation.md, section BE-098), écrits
d'après la définition avant le code :
- CA-1 : l'export ne contient que les objets du scope demandé (test de contenu) ;
- CA-2 : l'export ne contient aucun PAN, CVV ni secret (test de contenu) ;
- CA-3 : une demande sans permission renvoie `FORBIDDEN` ;
- CA-4 : une demande de scope d'un autre tenant ne retourne jamais les données du tenant A.

Le scope est un compte payeur (`billing_payer`) rattaché au tenant par un abonnement
(recommandation QE-FAC-22, comme BE-076). Le format de l'export est NON DÉFINI (QE-FAC-25) :
les tests fixent le contrat retenu (JSON structuré, `content`, sans secret de paiement).
Les colonnes de `data_export_request` (scope, requestedBy, status, requestedAt, fileRef)
sont lues en SQL brut pour que ce fichier ne dépende que de la base, pas du modèle.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.billing import service
from app.billing.models import BillingPayer, Invoice, Subscription
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.rbac.service import create_grant

MOT_DE_PASSE = "TestPassword123!"
URL_EXPORT = "/api/v1/billing/data-exports"
CODE_PERMISSION = "billing.data_export.request"
PAN_FACTICE = "4111111111111111"
SECRET_FACTICE = "secret-checkout-token-be098"


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(User.id).where(User.email == email))


async def _membre_sans_droit(client: AsyncClient, organization_id: uuid.UUID) -> str:
    """Utilisateur rattaché à l'organisation, sans permission d'export ; retourne son jeton."""
    cree = await client.post("/api/v1/auth/register", json={
        "email": f"be098-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-098",
    })
    login = await client.post("/api/v1/auth/login", json={"email": cree.json()["email"], "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=uuid.UUID(cree.json()["id"])))
        await db.commit()
    return login.json()["accessToken"]


async def _autre_organisation(client: AsyncClient) -> tuple[str, str]:
    """Crée un second tenant avec son propre propriétaire ; retourne (identifiant de l'organisation, jeton du propriétaire)."""
    email = f"be098-tenant-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Autre tenant"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jeton = login.json()["accessToken"]
    cree = await client.post(
        "/api/v1/organizations",
        json={"name": "Autre org BE-098", "slug": f"be098-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {jeton}"},
    )
    return cree.json()["id"], jeton


async def _compte_avec_factures(tenant_id: uuid.UUID, nombre_factures: int, marque: str) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Compte payeur rattaché au tenant par un abonnement, avec `nombre_factures` factures.

    Retourne l'identifiant du compte et celui de ses factures. Le plan est créé à la volée
    (service.get_or_create_plan) pour ne dépendre d'aucune ressource du catalogue.
    """
    async with AsyncSessionLocal() as db:
        payeur = BillingPayer(payerKind="organisation", accountRef=f"be098-{marque}-{uuid.uuid4().hex[:10]}")
        db.add(payeur)
        await db.flush()
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be098-{uuid.uuid4().hex[:10]}", f"Plan BE-098 {marque}", 0, "XAF", 30
        )
        maintenant = datetime.now(timezone.utc)
        abonnement = Subscription(
            organizationId=tenant_id, planId=plan.id, status="active",
            startDate=maintenant, endDate=maintenant + timedelta(days=30),
            payerId=payeur.id, beneficiaryTenantId=tenant_id,
        )
        db.add(abonnement)
        await db.flush()
        identifiants = []
        for numero in range(nombre_factures):
            facture = Invoice(
                subscriptionId=abonnement.id, amountCents=1500 + numero, amountMinor=1500 + numero,
                currency="XAF", status="pending", issuedAt=maintenant,
                idempotencyKey=f"be098-{marque}-{uuid.uuid4().hex}",
            )
            db.add(facture)
            await db.flush()
            identifiants.append(facture.id)
        await db.commit()
        return payeur.id, identifiants


async def _ajouter_tentative_de_paiement(facture_id: uuid.UUID) -> None:
    """Tentative de paiement portant un PAN et une URL de paiement secrète (ne doit jamais sortir)."""
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            'INSERT INTO "paymentAttempt" (id, "invoiceId", provider, mode, "idempotencyKey", '
            '"providerReference", "amountMinor", currency, status, "checkoutUrl", "requestedAt", '
            '"createdAt", "updatedAt") '
            "VALUES (:id, :facture, 'flutterwave', 'test', :cle, :pan, 1500, 'XAF', 'pending', :url, now(), now(), now())"
        ), {
            "id": uuid.uuid4(), "facture": facture_id, "cle": f"be098-{uuid.uuid4().hex}",
            "pan": PAN_FACTICE, "url": f"https://pay.example.test/checkout/{SECRET_FACTICE}",
        })
        await db.commit()


async def _nombre_demandes() -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(text("SELECT count(*) FROM data_export_request"))


async def _demande(demande_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        ligne = (await db.execute(text(
            'SELECT scope, "requestedBy", status, "requestedAt", "fileRef" FROM data_export_request WHERE id = :id'
        ), {"id": uuid.UUID(demande_id)})).mappings().one()
        return dict(ligne)


async def _nombre_audits_export(demande_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(text(
            "SELECT count(*) FROM audit_event WHERE action = 'billing.data_export.request' AND \"entityId\" = :id"
        ), {"id": uuid.UUID(demande_id)})


async def test_ca1_export_ne_contient_que_les_objets_du_scope_demande(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : seules les factures du compte demandé figurent dans l'export ; celles d'un autre compte du même tenant non."""
    org_id = uuid.UUID(organization["id"])
    compte_demande, factures_demandees = await _compte_avec_factures(org_id, 2, "demande")
    _, factures_autres = await _compte_avec_factures(org_id, 2, "autre")

    reponse = await client.post(
        URL_EXPORT,
        json={"accountId": str(compte_demande), "scope": "payeur"},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 201, reponse.text
    contenu = reponse.json()["content"]
    ids_factures = {uuid.UUID(f["id"]) for f in contenu["invoices"]}
    assert ids_factures == set(factures_demandees)
    texte = reponse.text
    for identifiant in factures_autres:
        assert str(identifiant) not in texte
    assert str(compte_demande) in texte


async def test_ca2_export_sans_pan_cvv_ni_secret(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : même si une tentative de paiement porte un PAN et une URL secrète, rien de tout cela ne sort."""
    org_id = uuid.UUID(organization["id"])
    compte, factures = await _compte_avec_factures(org_id, 1, "secrets")
    await _ajouter_tentative_de_paiement(factures[0])

    reponse = await client.post(
        URL_EXPORT,
        json={"accountId": str(compte), "scope": "payeur"},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 201, reponse.text
    texte = reponse.text
    assert PAN_FACTICE not in texte
    assert SECRET_FACTICE not in texte
    assert re.search(r"cvv|cvc|secret|checkoutUrl|providerReference", texte, re.IGNORECASE) is None
    assert re.search(r"(?<!\d)\d{13,19}(?!\d)", texte) is None


async def test_ca3_sans_permission_renvoie_forbidden_sans_ecriture(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 : un membre sans la permission d'export reçoit 403 FORBIDDEN ; aucune demande n'est créée."""
    org_id = uuid.UUID(organization["id"])
    compte, _ = await _compte_avec_factures(org_id, 1, "refus")
    jeton_sans_droit = await _membre_sans_droit(client, org_id)
    avant = await _nombre_demandes()

    reponse = await client.post(
        URL_EXPORT,
        json={"accountId": str(compte), "scope": "payeur"},
        headers=_entete(jeton_sans_droit, str(org_id)),
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"
    assert await _nombre_demandes() == avant


async def test_ca3_permission_accordee_permet_la_demande(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 (complément) : la permission `billing.data_export.request` accordée à un membre suffit."""
    org_id = uuid.UUID(organization["id"])
    compte, _ = await _compte_avec_factures(org_id, 1, "accorde")
    jeton = await _membre_sans_droit(client, org_id)
    async with AsyncSessionLocal() as db:
        membre = await db.scalar(
            select(User.id).join(OrganizationUser, OrganizationUser.userId == User.id)
            .where(OrganizationUser.organizationId == org_id, User.email != registered_user["email"])
            .order_by(User.createdAt.desc())
        )
        proprietaire = await _id_utilisateur(registered_user["email"])
        await create_grant(db, org_id, proprietaire, membre, CODE_PERMISSION, "allow")
        await db.commit()

    reponse = await client.post(
        URL_EXPORT,
        json={"accountId": str(compte), "scope": "payeur"},
        headers=_entete(jeton, str(org_id)),
    )

    assert reponse.status_code == 201, reponse.text


async def test_ca4_scope_d_un_autre_tenant_ne_retourne_jamais_ses_donnees(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : un acheteur du tenant B qui demande le compte du tenant A reçoit SCOPE_MISMATCH, sans donnée ni écriture."""
    org_a = uuid.UUID(organization["id"])
    compte_a, factures_a = await _compte_avec_factures(org_a, 2, "tenant-a")
    org_b, jeton_b = await _autre_organisation(client)
    avant = await _nombre_demandes()

    reponse = await client.post(
        URL_EXPORT,
        json={"accountId": str(compte_a), "scope": "payeur"},
        headers=_entete(jeton_b, org_b),
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "SCOPE_MISMATCH"
    for identifiant in factures_a:
        assert str(identifiant) not in reponse.text
    assert str(compte_a) not in reponse.text
    assert await _nombre_demandes() == avant


async def test_demande_enregistree_avec_demandeur_scope_et_trace_d_audit(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """La demande est une ligne data_export_request (scope, requestedBy, status, requestedAt) et un geste d'audit."""
    org_id = uuid.UUID(organization["id"])
    compte, _ = await _compte_avec_factures(org_id, 1, "trace")
    proprietaire = await _id_utilisateur(registered_user["email"])

    reponse = await client.post(
        URL_EXPORT,
        json={"accountId": str(compte), "scope": "payeur"},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    ligne = await _demande(corps["id"])
    assert ligne["scope"] == "payeur"
    assert ligne["requestedBy"] == proprietaire
    assert ligne["status"] == corps["status"]
    assert ligne["requestedAt"] is not None
    assert await _nombre_audits_export(corps["id"]) == 1
