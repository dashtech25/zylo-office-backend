"""Idempotence des commandes mutantes (BE-232).

Le test expose, sur une petite application FastAPI dédiée (pas sur l'application
principale), deux commandes protégées par `require_permission` et par
`run_idempotent`. Chaque test vérifie un critère d'acceptation de la définition :

- CA-1 : deux envois de la même clé produisent un seul effet et la même réponse ;
- CA-2 : même clé, payload différent : 409 ;
- CA-3 : une clé du tenant A n'est pas reconnue pour le tenant B ;
- CA-4 : une commande sans droit reçoit 403 avant toute mémorisation ;
- CA-5 : une clé expirée est traitée comme nouvelle (TTL lu dans la configuration).
"""

import uuid

import pytest
from fastapi import Body, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.idempotency import IdempotencyKey, require_idempotency_key, run_idempotent
from app.core.security import get_current_user
from app.rbac.service import get_current_organization_id, require_permission

# Permission accordée au propriétaire d'une organisation (socle).
PERMISSION_ACCORDEE = "billing.subscription.manage"
# Permission déclarée nulle part : personne ne la détient, pas même le propriétaire.
PERMISSION_JAMAIS_ACCORDEE = "test.idempotence.jamais"


def _construire_application(compteur: list[int]) -> FastAPI:
    """Application de test : deux commandes qui comptent leurs exécutions réelles."""
    application = FastAPI()

    def _ajouter_commande(chemin: str, permission: str) -> None:
        @application.post(chemin, status_code=201, dependencies=[Depends(require_permission(permission))])
        async def commande(
            request: Request,
            charge: dict = Body(...),
            cle: str = Depends(require_idempotency_key),
            organisation_id: uuid.UUID = Depends(get_current_organization_id),
            current_user=Depends(get_current_user),
            db=Depends(get_db),
        ):
            async def produire() -> tuple[int, dict]:
                compteur.append(1)
                return 201, {"numero": len(compteur), "nom": charge.get("nom")}

            reponse = await run_idempotent(
                db,
                cle=cle,
                organisation_id=organisation_id,
                acteur_id=current_user.id,
                methode=request.method,
                chemin=request.url.path,
                charge=charge,
                produire=produire,
            )
            return JSONResponse(status_code=reponse.statut, content=reponse.corps)

    _ajouter_commande("/test-idempotence/creer", PERMISSION_ACCORDEE)
    _ajouter_commande("/test-idempotence/refusee", PERMISSION_JAMAIS_ACCORDEE)
    return application


def _client_pour(application: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


def _entetes(utilisateur: dict, organisation_id: str, cle: str | None) -> dict[str, str]:
    entetes = {
        "Authorization": f"Bearer {utilisateur['accessToken']}",
        "X-Organization-Id": organisation_id,
    }
    if cle is not None:
        entetes["Idempotency-Key"] = cle
    return entetes


async def _nombre_de_cles() -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(IdempotencyKey))


async def test_ca1_meme_cle_un_seul_effet_et_meme_reponse(registered_user, organization):
    """CA-1 : le second envoi ne ré-exécute pas la commande et rend la même réponse."""
    compteur: list[int] = []
    cle = f"cle-ca1-{uuid.uuid4().hex}"
    async with _client_pour(_construire_application(compteur)) as client:
        entetes = _entetes(registered_user, organization["id"], cle)
        premiere = await client.post("/test-idempotence/creer", json={"nom": "A"}, headers=entetes)
        seconde = await client.post("/test-idempotence/creer", json={"nom": "A"}, headers=entetes)

    assert premiere.status_code == 201, premiere.text
    assert seconde.status_code == premiere.status_code
    assert seconde.json() == premiere.json()
    assert len(compteur) == 1


async def test_ca2_meme_cle_payload_different_renvoie_409_sans_effet(registered_user, organization):
    """CA-2 : même clé avec un autre contenu : 409, et aucune exécution en plus."""
    compteur: list[int] = []
    cle = f"cle-ca2-{uuid.uuid4().hex}"
    async with _client_pour(_construire_application(compteur)) as client:
        entetes = _entetes(registered_user, organization["id"], cle)
        await client.post("/test-idempotence/creer", json={"nom": "A"}, headers=entetes)
        conflit = await client.post("/test-idempotence/creer", json={"nom": "B"}, headers=entetes)

    assert conflit.status_code == 409, conflit.text
    assert conflit.json()["error"]["code"] == "idempotency_key_reused"
    assert len(compteur) == 1


async def test_ca3_cle_d_un_tenant_non_reconnue_pour_un_autre(registered_user, client, organization):
    """CA-3 : la même clé, envoyée pour une autre organisation, déclenche une nouvelle exécution."""
    autre = await client.post(
        "/api/v1/organizations",
        json={"name": "Autre Org", "slug": f"autre-org-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    autre_organisation = autre.json()
    compteur: list[int] = []
    cle = f"cle-ca3-{uuid.uuid4().hex}"
    async with _client_pour(_construire_application(compteur)) as api:
        reponse_a = await api.post(
            "/test-idempotence/creer", json={"nom": "A"},
            headers=_entetes(registered_user, organization["id"], cle),
        )
        reponse_b = await api.post(
            "/test-idempotence/creer", json={"nom": "A"},
            headers=_entetes(registered_user, autre_organisation["id"], cle),
        )

    assert reponse_a.status_code == 201 and reponse_b.status_code == 201
    assert reponse_b.json()["numero"] != reponse_a.json()["numero"]
    assert len(compteur) == 2


async def test_ca4_refus_de_droit_renvoie_403_avant_memorisation(registered_user, organization):
    """CA-4 : sans permission, 403 et aucune ligne de clé n'est créée."""
    compteur: list[int] = []
    cle = f"cle-ca4-{uuid.uuid4().hex}"
    avant = await _nombre_de_cles()
    async with _client_pour(_construire_application(compteur)) as client:
        refus = await client.post(
            "/test-idempotence/refusee", json={"nom": "A"},
            headers=_entetes(registered_user, organization["id"], cle),
        )

    assert refus.status_code == 403, refus.text
    assert refus.json()["error"]["code"] == "permission_denied"
    assert compteur == []
    assert await _nombre_de_cles() == avant


async def test_ca5_cle_expiree_traitee_comme_nouvelle(registered_user, organization, monkeypatch):
    """CA-5 : avec un TTL nul (valeur lue de la configuration), la clé est expirée
    dès la première réponse : le second envoi exécute de nouveau la commande."""
    monkeypatch.setattr(settings, "IDEMPOTENCY_KEY_TTL_HOURS", 0)
    compteur: list[int] = []
    cle = f"cle-ca5-{uuid.uuid4().hex}"
    async with _client_pour(_construire_application(compteur)) as client:
        entetes = _entetes(registered_user, organization["id"], cle)
        await client.post("/test-idempotence/creer", json={"nom": "A"}, headers=entetes)
        seconde = await client.post("/test-idempotence/creer", json={"nom": "A"}, headers=entetes)

    assert seconde.status_code == 201, seconde.text
    assert len(compteur) == 2
