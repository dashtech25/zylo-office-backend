"""BE-117 : exports de données asynchrones (portail organisation).

Intention : prouver par des tests les critères d'acceptation de BE-117
(implementation-backend/tasks-portail-organisation.md, section BE-117) :
- CA-1 : POST retourne 202 avec le statut `export_requested` ; le traitement est confié à un
  traitement de fond, il ne s'exécute pas dans la requête ;
- CA-2 : aucun lien de téléchargement tant que le statut n'est pas `ready` ;
- CA-3 : après `expiresAt`, le téléchargement est refusé (horloge figée) ;
- CA-4 : sans `data.export`, 403 ; export d'une autre organisation, 404 ;
- CA-5 : aucune durée codée en dur ; sans valeur de configuration, aucun lien n'est émis.

Routes testées :
- POST /api/v1/organizations/{organization_id}/exports
- GET /api/v1/organizations/{organization_id}/exports/{export}
- GET /api/v1/organizations/{organization_id}/exports/{export}/download

Écarts (consignés dans le rapport) :
- la permission est `data.export` (format `domaine.action`, comme les autres codes du portail), et
  non `data:export` écrit dans la fiche ;
- le traitement de fond est lancé par `BackgroundTasks` (pas de file de travail durable).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

import app.portail.exports.router as routeur_exports
import app.portail.exports.service as service_exports
from app.audit.models import AuditEvent
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser
from app.portail.exports.models import PortailExportJob

MOT_DE_PASSE = "TestPassword123!"
DUREE_CONFIGUREE = 900


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


@pytest.fixture
def duree_configuree(monkeypatch) -> int:
    """Durée de vie de l'export fixée par la configuration (et non par le code)."""
    monkeypatch.setattr(settings, "EXPORT_EXPIRATION_SECONDS", DUREE_CONFIGUREE, raising=False)
    return DUREE_CONFIGUREE


@pytest.fixture
def traitement_de_fond_espionne(monkeypatch) -> list[uuid.UUID]:
    """Remplace le traitement de fond par un espion qui ne fait que noter l'appel."""
    appels: list[uuid.UUID] = []

    async def espion(export_id: uuid.UUID) -> None:
        appels.append(export_id)

    monkeypatch.setattr(routeur_exports, "traiter_export", espion)
    return appels


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _url(organization_id: str, export_id: str | None = None, suffixe: str = "") -> str:
    base = f"/api/v1/organizations/{organization_id}/exports"
    if export_id is None:
        return base
    return f"{base}/{export_id}{suffixe}"


async def _membre_sans_droit(client: AsyncClient, organization_id: str) -> str:
    """Utilisateur rattaché à l'organisation sans rôle ni permission d'export ; retourne son jeton."""
    membre = await client.post("/api/v1/auth/register", json={
        "email": f"be117-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-117",
    })
    login = await client.post("/api/v1/auth/login", json={"email": membre.json()["email"], "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=uuid.UUID(membre.json()["id"])))
        await db.commit()
    return login.json()["accessToken"]


async def _organisation_etrangere(client: AsyncClient) -> tuple[str, str]:
    """Organisation d'un autre utilisateur, hors de portée de l'utilisateur de test.

    Retourne (identifiant de l'organisation, identifiant de son créateur)."""
    autre = await client.post("/api/v1/auth/register", json={
        "email": f"be117-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Autre BE-117",
    })
    login = await client.post("/api/v1/auth/login", json={"email": autre.json()["email"], "password": MOT_DE_PASSE})
    res = await client.post(
        "/api/v1/organizations", json={"name": "Org B BE-117", "slug": f"be117-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {login.json()['accessToken']}"},
    )
    return res.json()["id"], autre.json()["id"]


async def _export_en_base(organization_id: uuid.UUID, requested_by: uuid.UUID) -> PortailExportJob:
    """Demande d'export écrite directement en base, sans passer par l'API (pour l'isolation)."""
    async with AsyncSessionLocal() as db:
        ligne = PortailExportJob(
            id=uuid.uuid4(), organizationId=organization_id, requestedBy=requested_by,
            perimetre="membres", statut="export_requested", contenu=None, expiresAt=None,
        )
        db.add(ligne)
        await db.commit()
        return ligne.id


async def _ligne(export_id: uuid.UUID) -> PortailExportJob:
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(PortailExportJob).where(PortailExportJob.id == export_id)
        )).scalar_one()


async def _demander(client: AsyncClient, token: str, organization_id: str) -> dict:
    return await client.post(_url(organization_id), json={}, headers=_entete(token, organization_id))


async def test_ca1_post_retourne_202_sans_traiter_dans_la_requete(
    client: AsyncClient, registered_user: dict, organization: dict, duree_configuree, traitement_de_fond_espionne
):
    """CA-1 : POST retourne 202 et `export_requested` ; le traitement est confié au traitement de fond."""
    org_id = organization["id"]

    reponse = await _demander(client, registered_user["accessToken"], org_id)

    assert reponse.status_code == 202, reponse.text
    corps = reponse.json()
    assert corps["statut"] == "export_requested"
    assert corps["lienTelechargement"] is None
    assert traitement_de_fond_espionne == [uuid.UUID(corps["id"])]
    ligne = await _ligne(uuid.UUID(corps["id"]))
    assert ligne.statut == "export_requested"
    assert ligne.contenu is None


async def test_ca2_aucun_lien_tant_que_le_statut_nest_pas_ready(
    client: AsyncClient, registered_user: dict, organization: dict, duree_configuree, traitement_de_fond_espionne
):
    """CA-2 : sans statut `ready`, ni lien ni contenu ; une fois traité, le lien apparaît."""
    org_id = organization["id"]
    token = registered_user["accessToken"]
    export_id = (await _demander(client, token, org_id)).json()["id"]

    statut = await client.get(_url(org_id, export_id), headers=_entete(token, org_id))
    assert statut.status_code == 200, statut.text
    assert statut.json()["statut"] == "export_requested"
    assert statut.json()["lienTelechargement"] is None

    refus = await client.get(_url(org_id, export_id, "/download"), headers=_entete(token, org_id))
    assert refus.status_code == 409, refus.text
    assert refus.json()["error"]["code"] == "export_not_ready"

    await service_exports.traiter_export(uuid.UUID(export_id))

    pret = await client.get(_url(org_id, export_id), headers=_entete(token, org_id))
    assert pret.json()["statut"] == "ready"
    assert pret.json()["lienTelechargement"] == _url(org_id, export_id, "/download")
    telechargement = await client.get(_url(org_id, export_id, "/download"), headers=_entete(token, org_id))
    assert telechargement.status_code == 200, telechargement.text
    contenu = telechargement.json()["contenu"]
    assert any(membre["email"] == registered_user["email"] for membre in contenu)
    assert all("hashedPassword" not in membre for membre in contenu)


async def test_ca3_telechargement_refuse_apres_expiration(
    client: AsyncClient, registered_user: dict, organization: dict, duree_configuree, traitement_de_fond_espionne,
    monkeypatch,
):
    """CA-3 : téléchargement accepté avant `expiresAt`, refusé en 410 après (horloge figée)."""
    org_id = organization["id"]
    token = registered_user["accessToken"]
    export_id = (await _demander(client, token, org_id)).json()["id"]
    await service_exports.traiter_export(uuid.UUID(export_id))

    avant = await client.get(_url(org_id, export_id, "/download"), headers=_entete(token, org_id))
    assert avant.status_code == 200, avant.text
    expiration = datetime.fromisoformat((await client.get(
        _url(org_id, export_id), headers=_entete(token, org_id))).json()["expiresAt"])

    monkeypatch.setattr(service_exports, "maintenant", lambda: expiration + timedelta(seconds=1))

    statut = await client.get(_url(org_id, export_id), headers=_entete(token, org_id))
    assert statut.json()["statut"] == "expired"
    assert statut.json()["lienTelechargement"] is None
    apres = await client.get(_url(org_id, export_id, "/download"), headers=_entete(token, org_id))
    assert apres.status_code == 410, apres.text
    assert apres.json()["error"]["code"] == "export_expired"
    ligne = await _ligne(uuid.UUID(export_id))
    assert ligne.contenu is None
    assert ligne.statut == "expired"


async def test_ca3_telechargement_journalise(
    client: AsyncClient, registered_user: dict, organization: dict, duree_configuree, traitement_de_fond_espionne
):
    """Le téléchargement réussi laisse une trace d'audit de l'organisation (lien journalisé)."""
    org_id = organization["id"]
    token = registered_user["accessToken"]
    export_id = (await _demander(client, token, org_id)).json()["id"]
    await service_exports.traiter_export(uuid.UUID(export_id))

    await client.get(_url(org_id, export_id, "/download"), headers=_entete(token, org_id))

    async with AsyncSessionLocal() as db:
        trace = (await db.execute(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.organizationId == uuid.UUID(org_id),
            AuditEvent.action == service_exports.ACTION_TELECHARGEMENT,
        ))).scalar_one()
    assert trace >= 1


async def test_ca4_sans_permission_data_export_403(
    client: AsyncClient, registered_user: dict, organization: dict, duree_configuree, traitement_de_fond_espionne
):
    """CA-4 : un membre sans `data.export` ne peut ni demander ni lire ni télécharger un export."""
    org_id = organization["id"]
    export_id = (await _demander(client, registered_user["accessToken"], org_id)).json()["id"]
    token_membre = await _membre_sans_droit(client, org_id)

    demande = await _demander(client, token_membre, org_id)
    assert demande.status_code == 403, demande.text
    assert demande.json()["error"]["code"] == "permission_denied"
    lecture = await client.get(_url(org_id, export_id), headers=_entete(token_membre, org_id))
    assert lecture.status_code == 403, lecture.text
    telechargement = await client.get(_url(org_id, export_id, "/download"), headers=_entete(token_membre, org_id))
    assert telechargement.status_code == 403, telechargement.text


async def test_ca4_export_d_une_autre_organisation_404(
    client: AsyncClient, registered_user: dict, organization: dict, duree_configuree
):
    """CA-4 : un export d'une autre organisation est indiscernable d'un export absent (404)."""
    org_id = organization["id"]
    token = registered_user["accessToken"]
    autre_org_id, autre_createur_id = await _organisation_etrangere(client)
    export_etranger = await _export_en_base(uuid.UUID(autre_org_id), uuid.UUID(autre_createur_id))

    sous_mauvaise_portee = await client.get(
        _url(org_id, str(export_etranger)), headers=_entete(token, org_id))
    assert sous_mauvaise_portee.status_code == 404, sous_mauvaise_portee.text
    assert sous_mauvaise_portee.json()["error"]["code"] == "export_not_found"

    organisation_etrangere = await client.get(
        _url(autre_org_id, str(export_etranger)), headers=_entete(token, autre_org_id))
    assert organisation_etrangere.status_code == 404, organisation_etrangere.text


async def test_ca5_sans_configuration_aucun_lien_n_est_emis(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch, traitement_de_fond_espionne
):
    """CA-5 : sans durée configurée, l'export reste `export_requested`, sans lien ni expiration."""
    monkeypatch.setattr(settings, "EXPORT_EXPIRATION_SECONDS", None, raising=False)
    org_id = organization["id"]
    token = registered_user["accessToken"]
    export_id = (await _demander(client, token, org_id)).json()["id"]

    await service_exports.traiter_export(uuid.UUID(export_id))

    statut = await client.get(_url(org_id, export_id), headers=_entete(token, org_id))
    assert statut.json()["statut"] == "export_requested"
    assert statut.json()["lienTelechargement"] is None
    assert statut.json()["expiresAt"] is None
    refus = await client.get(_url(org_id, export_id, "/download"), headers=_entete(token, org_id))
    assert refus.status_code == 409, refus.text
    ligne = await _ligne(uuid.UUID(export_id))
    assert ligne.contenu is None
    assert ligne.expiresAt is None


async def test_ca5_duree_lue_dans_la_configuration(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch, traitement_de_fond_espionne
):
    """CA-5 : l'échéance suit la valeur de configuration (aucune durée codée en dur)."""
    duree = 7203
    monkeypatch.setattr(settings, "EXPORT_EXPIRATION_SECONDS", duree, raising=False)
    org_id = organization["id"]
    export_id = (await _demander(client, registered_user["accessToken"], org_id)).json()["id"]

    avant_traitement = datetime.now(timezone.utc)
    await service_exports.traiter_export(uuid.UUID(export_id))

    ligne = await _ligne(uuid.UUID(export_id))
    assert ligne.statut == "ready"
    ecart = (ligne.expiresAt - avant_traitement).total_seconds() - duree
    assert abs(ecart) < 60, ecart
