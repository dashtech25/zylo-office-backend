"""BE-211 : webhook sortant (endpoint, livraison signée, DLQ, rotation, isolation).

Tests écrits d'après `### BE-211` de implementation-backend/tasks-donnees-api-contrats.md,
avant le code. Recommandations appliquées pour les points NON DÉFINI (POINTS-OUVERTS) :
5 tentatives à intervalle croissant, délai de hook 10 s, DLQ après la dernière tentative
(QE-API-16) ; HMAC-SHA256 horodaté, fenêtre anti-rejeu de 300 s (QE-API-19).

Couverture :
- CA-1 : chaque livraison porte une signature et un horodatage, vérifiables ;
- CA-2 : des échecs répétés placent la livraison en DLQ après le nombre maximal de tentatives ;
- CA-3 : une livraison n'est consultable que par le tenant propriétaire ; autre tenant : 404 ;
- CA-4 : pendant l'overlap de rotation, l'ancienne signature est acceptée ; après, refusée ;
- CA-5 : le corps de livraison ne contient que les champs de l'enveloppe minimisée ;
- CA-6 : création d'un endpoint sans `integrations.manage` : 403, rien n'est créé.

Droit : `integrations.manage` (déclaré par `app/integrations/permissions.py`, nommé
`integration.manage` dans la définition) ; lecture des livraisons : `integrations.read`.
"""

import datetime as dt
import json
import uuid

import httpx
import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.identity.models import Organization, OrganizationUser, User
from app.rbac.models import Permission, Role, RolePermission, UserRole

INTEGRATIONS_READ = "integrations.read"
INTEGRATIONS_MANAGE = "integrations.manage"
ROUTE = "/api/v1/webhook-endpoints"
ROUTE_LIVRAISONS = "/api/v1/webhook-deliveries"
URL = "https://client.example.test/hooks"
CLES_ENVELOPPE_MINIMISEE = {"eventId", "eventType", "schemaVersion", "occurredAt", "tenantId"}


def _entete(utilisateur: dict, organization_id: str) -> dict:
    return {
        "Authorization": f"Bearer {utilisateur['accessToken']}",
        "X-Organization-Id": organization_id,
    }


async def _accorder(user_id: uuid.UUID, org_id: uuid.UUID, codes: list[str]) -> None:
    """Attribue à l'utilisateur un rôle de test portant `codes` dans `org_id`."""
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=org_id, code=f"be211-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-211")
        db.add(role)
        await db.flush()
        for code in codes:
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(code=code, moduleCode="integrations", description="Permission de test BE-211")
                db.add(permission)
                await db.flush()
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        db.add(UserRole(userId=user_id, organizationId=org_id, roleId=role.id))
        await db.commit()


async def _utilisateur_id(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _membre_sans_droit(client, organization_id: str) -> dict:
    """Inscrit un utilisateur, le rattache à l'organisation, sans aucun rôle (refus `403`)."""
    from tests.conftest import unique_email

    email = unique_email()
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Sans droit"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=user.id))
        await db.commit()
    return {"email": email, "accessToken": login.json()["accessToken"], "id": str(user.id)}


async def _autre_organisation() -> uuid.UUID:
    """Crée un tenant B distinct du tenant de test."""
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="Tenant B BE-211", slug=f"be211-b-{uuid.uuid4().hex[:10]}")
        db.add(organisation)
        await db.flush()
        org_id = organisation.id
        await db.commit()
    return org_id


@pytest.fixture
async def gestionnaire(client, registered_user: dict, organization: dict) -> dict:
    """Propriétaire de test avec les permissions de lecture et d'écriture des intégrations."""
    await _accorder(
        await _utilisateur_id(registered_user["email"]),
        uuid.UUID(organization["id"]),
        [INTEGRATIONS_READ, INTEGRATIONS_MANAGE],
    )
    return registered_user


async def _creer_endpoint(client, utilisateur: dict, organisation: dict) -> dict:
    res = await client.post(ROUTE, json={"url": URL}, headers=_entete(utilisateur, organisation["id"]))
    assert res.status_code == 201, res.text
    return res.json()


def _donnees_evenement(org_id: uuid.UUID) -> dict:
    """Enveloppe canonique d'un événement de tenant (BE-150), sans secret."""
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": f"Test.BE211.{uuid.uuid4().hex}",
        "schemaVersion": 1,
        "occurredAt": "2026-11-05T10:00:00+00:00",
        "tenantId": str(org_id),
        "scope": {"type": "organization", "id": str(org_id)},
        "actor": {"userId": str(uuid.uuid4())},
        "subject": {"type": "Test", "id": str(uuid.uuid4())},
        "dataClassification": "internal",
        "correlationId": None,
        "causationId": None,
        "payload": {"valeur": f"valeur-{uuid.uuid4().hex}"},
    }


async def _publier_evenement(org_id: uuid.UUID) -> str:
    """Écrit un événement dans l'outbox du tenant et committe ; renvoie son eventId."""
    from app.evenements.outbox import enregistrer_evenement

    donnees = _donnees_evenement(org_id)
    async with AsyncSessionLocal() as db:
        await enregistrer_evenement(db, donnees, emetteur_tenant=org_id)
        await db.commit()
    return donnees["eventId"]


def _client_http(statut: int, requetes: list) -> httpx.AsyncClient:
    """Client HTTP factice : enregistre chaque requête et répond `statut`."""

    def repondre(requete: httpx.Request) -> httpx.Response:
        requetes.append(requete)
        return httpx.Response(statut)

    return httpx.AsyncClient(transport=httpx.MockTransport(repondre))


async def _dispatcher(org_id: uuid.UUID, maintenant: dt.datetime, client: httpx.AsyncClient):
    from app.integrations.webhooks_sortants import dispatcher_webhooks

    async with AsyncSessionLocal() as db:
        bilan = await dispatcher_webhooks(db, org_id, maintenant=maintenant, client=client)
        await db.commit()
    return bilan


async def _livraisons(endpoint_id: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        lignes = await db.execute(
            text(
                'SELECT id, status, attempts, "nextAttemptAt" FROM "webhook_delivery" '
                'WHERE "endpointId" = :id ORDER BY "createdAt", id'
            ),
            {"id": uuid.UUID(endpoint_id)},
        )
        return [dict(ligne._mapping) for ligne in lignes]


def _maintenant() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


async def test_ca1_chaque_livraison_est_signee_et_horodatee(client, gestionnaire, organization):
    from app.integrations.webhooks_sortants import verifier_signature

    endpoint = await _creer_endpoint(client, gestionnaire, organization)
    secret = endpoint["secret"]
    eventId = await _publier_evenement(uuid.UUID(organization["id"]))
    maintenant = _maintenant()
    requetes: list[httpx.Request] = []

    bilan = await _dispatcher(uuid.UUID(organization["id"]), maintenant, _client_http(200, requetes))

    assert bilan.livrees >= 1
    assert len(requetes) == 1
    requete = requetes[0]
    entete = requete.headers["X-Zylo-Signature"]
    corps = requete.content
    assert entete.startswith("t=") and ",v1=" in entete
    assert verifier_signature(entete, corps, [secret], maintenant) is True
    assert verifier_signature(entete, corps, ["mauvais-secret"], maintenant) is False
    assert verifier_signature(entete, corps + b" ", [secret], maintenant) is False
    assert json.loads(corps)["eventId"] == eventId
    livraison = (await _livraisons(endpoint["id"]))[0]
    assert livraison["status"] == "delivered"


async def test_ca2_echecs_repetes_mettent_en_dlq_apres_le_maximum(client, gestionnaire, organization):
    from app.integrations.webhooks_sortants import NOMBRE_MAX_TENTATIVES

    endpoint = await _creer_endpoint(client, gestionnaire, organization)
    await _publier_evenement(uuid.UUID(organization["id"]))
    base = _maintenant()
    requetes: list[httpx.Request] = []
    echec = _client_http(500, requetes)

    for passage in range(1, NOMBRE_MAX_TENTATIVES + 1):
        await _dispatcher(uuid.UUID(organization["id"]), base + dt.timedelta(days=passage), echec)
        livraison = (await _livraisons(endpoint["id"]))[0]
        assert livraison["attempts"] == passage
        attendu = "dlq" if passage == NOMBRE_MAX_TENTATIVES else "failed"
        assert livraison["status"] == attendu

    assert len(requetes) == NOMBRE_MAX_TENTATIVES
    await _dispatcher(uuid.UUID(organization["id"]), base + dt.timedelta(days=99), echec)
    assert len(requetes) == NOMBRE_MAX_TENTATIVES, "une livraison en DLQ n'est plus retentée"


async def test_ca3_livraison_consultable_par_son_tenant_seulement(client, gestionnaire, organization):
    endpoint = await _creer_endpoint(client, gestionnaire, organization)
    await _publier_evenement(uuid.UUID(organization["id"]))
    await _dispatcher(uuid.UUID(organization["id"]), _maintenant(), _client_http(200, []))
    livraison_id = (await _livraisons(endpoint["id"]))[0]["id"]

    lecture = await client.get(
        f"{ROUTE_LIVRAISONS}/{livraison_id}", headers=_entete(gestionnaire, organization["id"])
    )
    assert lecture.status_code == 200, lecture.text
    assert lecture.json()["status"] == "delivered"

    autre_org = str(await _autre_organisation())
    autre = await _membre_sans_droit(client, autre_org)
    await _accorder(uuid.UUID(autre["id"]), uuid.UUID(autre_org), [INTEGRATIONS_READ, INTEGRATIONS_MANAGE])
    refus = await client.get(f"{ROUTE_LIVRAISONS}/{livraison_id}", headers=_entete(autre, autre_org))
    assert refus.status_code == 404, refus.text


async def test_ca4_rotation_accepte_l_ancienne_signature_pendant_l_overlap(client, gestionnaire, organization):
    from app.integrations.webhooks_sortants import secrets_acceptes, verifier_signature
    from app.integrations.webhooks_sortants import signer

    endpoint = await _creer_endpoint(client, gestionnaire, organization)
    ancien = endpoint["secret"]
    rotation = await client.post(
        f"{ROUTE}/{endpoint['id']}/rotate-secret", headers=_entete(gestionnaire, organization["id"])
    )
    assert rotation.status_code == 200, rotation.text
    nouveau = rotation.json()["secret"]
    assert nouveau != ancien
    fin_overlap = dt.datetime.fromisoformat(rotation.json()["overlapJusquA"])

    maintenant = _maintenant()
    corps = b'{"eventId":"test"}'
    entete_ancien = signer(ancien, corps, int(maintenant.timestamp()))
    async with AsyncSessionLocal() as db:
        pendant = await secrets_acceptes(db, uuid.UUID(endpoint["id"]), maintenant)
    assert verifier_signature(entete_ancien, corps, pendant, maintenant) is True

    apres = fin_overlap + dt.timedelta(seconds=1)
    entete_ancien_apres = signer(ancien, corps, int(apres.timestamp()))
    async with AsyncSessionLocal() as db:
        apres_overlap = await secrets_acceptes(db, uuid.UUID(endpoint["id"]), apres)
    assert ancien not in apres_overlap
    assert verifier_signature(entete_ancien_apres, corps, apres_overlap, apres) is False


async def test_ca5_payload_minimise_aux_champs_de_l_enveloppe(client, gestionnaire, organization):
    await _creer_endpoint(client, gestionnaire, organization)
    await _publier_evenement(uuid.UUID(organization["id"]))
    requetes: list[httpx.Request] = []

    await _dispatcher(uuid.UUID(organization["id"]), _maintenant(), _client_http(200, requetes))

    assert len(requetes) == 1
    corps = json.loads(requetes[0].content)
    assert set(corps.keys()) == CLES_ENVELOPPE_MINIMISEE
    assert "valeur-" not in requetes[0].content.decode()


async def test_ca6_creation_sans_integrations_manage_renvoie_403(client, registered_user, organization):
    sans_droit = await _membre_sans_droit(client, organization["id"])
    res = await client.post(ROUTE, json={"url": URL}, headers=_entete(sans_droit, organization["id"]))

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"
    async with AsyncSessionLocal() as db:
        nombre = await db.scalar(
            text('SELECT count(*) FROM "webhook_endpoint" WHERE "organizationId" = :org'),
            {"org": uuid.UUID(organization["id"])},
        )
    assert nombre == 0


async def test_url_non_https_refusee(client, gestionnaire, organization):
    res = await client.post(
        ROUTE, json={"url": "http://client.example.test/hooks"}, headers=_entete(gestionnaire, organization["id"])
    )
    assert res.status_code == 422, res.text
