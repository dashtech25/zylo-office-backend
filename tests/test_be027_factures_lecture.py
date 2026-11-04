"""BE-027 : lecture des factures de l'organisation courante.

Intention : prouver les critères d'acceptation de BE-027
(implementation-backend/tasks-socle-tenant-identite.md, section BE-027) :
- CA-1 : la liste ne contient que les factures de l'organisation active ;
- CA-2 (refus) : un membre sans permission de lecture de la facturation reçoit 403 ;
- CA-3 (isolation) : O1 demandant une facture de O2 reçoit 404 ;
- CA-4 : le statut affiché est celui de la base serveur, jamais celui d'une
  demande de l'interface (paramètre ou corps ignoré).

Routes testées : `GET /api/v1/organizations/current/invoices` et
`GET /api/v1/organizations/current/invoices/{invoiceId}`. L'organisation courante
vient de l'en-tête `X-Organization-Id`, validé par `get_current_organization_id`.
La permission de lecture (code NON DÉFINI, QE-SOC-06) est celle du socle
`app/billing/permissions.py::BILLING_INVOICE_READ`, accordée au rôle propriétaire.

Les tests créent leurs données par l'API (plan par le service de seed, abonnement
et facture par les routes existantes). Le statut « payé » est posé directement en
base pour vérifier CA-4 : aucune route n'écrit ce statut dans ce lot.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import update

from app.billing import service
from app.billing.models import Invoice
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"


async def creer_plan_catalogue(code: str, prix: int = 1000) -> None:
    async with AsyncSessionLocal() as db:
        await service.get_or_create_plan(db, "zylo_liquid", code, "Test Plan", prix, "XAF", 30)


def _entetes(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def creer_facture(client: AsyncClient, token: str, organization_id: str) -> str:
    """Crée un abonnement d'essai puis une facture pour l'organisation ; renvoie l'identifiant de la facture."""
    headers = _entetes(token, organization_id)
    plan_code = f"plan-{uuid.uuid4().hex[:8]}"
    await creer_plan_catalogue(plan_code)
    abonnement = await client.post(
        f"/api/v1/billing/organizations/{organization_id}/subscriptions", json={"planCode": plan_code}, headers=headers,
    )
    assert abonnement.status_code == 201, abonnement.text
    facture = await client.post(
        f"/api/v1/billing/organizations/{organization_id}/invoices",
        json={"subscriptionId": abonnement.json()["id"]},
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert facture.status_code == 201, facture.text
    return facture.json()["id"]


async def creer_organisation(client: AsyncClient, token: str) -> str:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Org BE-027", "slug": f"be027-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def utilisateur_connecte(client: AsyncClient) -> dict:
    email = unique_email()
    inscription = await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Membre"})
    assert inscription.status_code == 201, inscription.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return {"id": inscription.json()["id"], "accessToken": login.json()["accessToken"]}


async def ajouter_membre_sans_role(organization_id: str, user_id: str) -> None:
    """Rattache un utilisateur à l'organisation sans rôle : il est membre, mais n'a aucune permission."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=uuid.UUID(user_id)))
        await db.commit()


async def test_liste_ne_contient_que_les_factures_de_l_organisation_active(client: AsyncClient, registered_user: dict, organization: dict):
    token = registered_user["accessToken"]
    o1 = organization["id"]
    o2 = await creer_organisation(client, token)
    facture_o1 = await creer_facture(client, token, o1)
    facture_o2 = await creer_facture(client, token, o2)

    res = await client.get("/api/v1/organizations/current/invoices", headers=_entetes(token, o1))

    assert res.status_code == 200, res.text
    identifiants = [ligne["id"] for ligne in res.json()["data"]]
    assert facture_o1 in identifiants
    assert facture_o2 not in identifiants


async def test_membre_sans_permission_de_lecture_recoit_403(client: AsyncClient, registered_user: dict, organization: dict):
    token = registered_user["accessToken"]
    organisation_id = organization["id"]
    await creer_facture(client, token, organisation_id)
    membre = await utilisateur_connecte(client)
    await ajouter_membre_sans_role(organisation_id, membre["id"])

    liste = await client.get("/api/v1/organizations/current/invoices", headers=_entetes(membre["accessToken"], organisation_id))
    assert liste.status_code == 403, liste.text
    assert liste.json()["error"]["code"] == "permission_denied"


async def test_facture_d_une_autre_organisation_renvoie_404(client: AsyncClient, registered_user: dict, organization: dict):
    token = registered_user["accessToken"]
    o1 = organization["id"]
    o2 = await creer_organisation(client, token)
    facture_o2 = await creer_facture(client, token, o2)

    res = await client.get(f"/api/v1/organizations/current/invoices/{facture_o2}", headers=_entetes(token, o1))

    assert res.status_code == 404, res.text


async def test_detail_facture_de_l_organisation_courante(client: AsyncClient, registered_user: dict, organization: dict):
    token = registered_user["accessToken"]
    o1 = organization["id"]
    facture = await creer_facture(client, token, o1)

    res = await client.get(f"/api/v1/organizations/current/invoices/{facture}", headers=_entetes(token, o1))

    assert res.status_code == 200, res.text
    assert res.json()["id"] == facture
    assert res.json()["amountMinor"] == 1000
    assert res.json()["currency"] == "XAF"


async def test_statut_affiche_est_celui_de_la_base_serveur(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-4 : le statut vient de la base. Un statut envoyé par le client (paramètre de requête) est ignoré."""
    token = registered_user["accessToken"]
    o1 = organization["id"]
    facture = await creer_facture(client, token, o1)
    async with AsyncSessionLocal() as db:
        await db.execute(update(Invoice).where(Invoice.id == uuid.UUID(facture)).values(status="paid"))
        await db.commit()

    detail = await client.get(
        f"/api/v1/organizations/current/invoices/{facture}?status=pending", headers=_entetes(token, o1),
    )
    liste = await client.get("/api/v1/organizations/current/invoices?status=pending", headers=_entetes(token, o1))

    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "paid"
    ligne = next(ligne for ligne in liste.json()["data"] if ligne["id"] == facture)
    assert ligne["status"] == "paid"
