"""BE-253 : limites d'usage et détection d'abus.

Tests écrits d'après la définition `### BE-253` de
implementation-backend/tasks-exploitation-architecture.md, avant le code.

Périmètre : socle `app/core/ratelimit.py` (compteur persistant dans la table
`rate_limit_events`), monté sur une application FastAPI minimale, comme
BE-191. Le seuil vient de `Settings` (QE-EXP-07 : valeur par défaut provisoire).

Couverture :
- CA-1 : dépassement de seuil renvoie 429 ; seuil lu de la configuration ;
- CA-2 : compteurs scopés par tenant et par identité ; test d'isolation ;
- CA-3 : un abus détecté émet un événement d'alerte routé ;
- CA-4 : aucun score de réputation de tenant n'est calculé (inventaire).
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError, register_exception_handlers
from app.core.ratelimit import cle_limite, consomme, exiger_limite
from app.shared.quotas import PolitiqueQuota

INSTANT = datetime(2026, 1, 1, 12, 0, 10, tzinfo=timezone.utc)
RACINE_APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture
async def db():
    # Même précaution que la fixture `client` de conftest.py : `engine` est un
    # singleton ; sans dispose(), les connexions poolées d'une boucle précédente
    # sont réutilisées dans cette boucle et asyncpg lève "attached to a different loop".
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        yield session


def _tenant() -> str:
    import uuid

    return str(uuid.uuid4())


def _politique(maximum: int = 2) -> PolitiqueQuota:
    return PolitiqueQuota(nom="test-be253", categorie="technique", max_requetes=maximum, fenetre_secondes=60)


def _app_limitee(politique: PolitiqueQuota, horloge) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get(
        "/limite",
        dependencies=[
            Depends(
                exiger_limite(
                    politique,
                    lambda requete: (requete.headers.get("x-tenant", ""), requete.headers.get("x-identite", "")),
                    horloge=horloge,
                )
            )
        ],
    )
    async def route() -> dict:
        return {"ok": True}

    return app


# --- CA-1 : dépassement de seuil -> 429, seuil lu de la configuration -------


async def test_ca1_depassement_de_seuil_renvoie_429_avec_retry_after(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_MAX_REQUETES", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_FENETRE_SECONDES", 60)
    entetes = {"x-tenant": _tenant(), "x-identite": "utilisateur-1"}
    async with AsyncClient(
        transport=ASGITransport(app=_app_limitee(ratelimit.politique_limite_api(), lambda: INSTANT)),
        base_url="http://test",
    ) as client:
        assert (await client.get("/limite", headers=entetes)).status_code == 200
        assert (await client.get("/limite", headers=entetes)).status_code == 200
        reponse = await client.get("/limite", headers=entetes)

    assert reponse.status_code == 429
    assert reponse.json()["error"]["code"] == "rate_limited"
    # Fenêtre 12:00:00 - 12:01:00, instant 12:00:10 : 50 secondes restent à courir.
    assert reponse.headers["Retry-After"] == "50"


def test_ca1_seuil_par_defaut_lu_dans_settings(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_MAX_REQUETES", 7)
    monkeypatch.setattr(settings, "RATE_LIMIT_FENETRE_SECONDES", 33)
    politique = ratelimit.politique_limite_api()
    assert politique.max_requetes == 7
    assert politique.fenetre_secondes == 33


async def test_ca1_le_seuil_suit_la_configuration(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_MAX_REQUETES", 1)
    tenant = _tenant()
    await consomme(db, ratelimit.politique_limite_api(), tenant_id=tenant, identite="id-1", instant=INSTANT)
    with pytest.raises(AppError) as erreur:
        await consomme(db, ratelimit.politique_limite_api(), tenant_id=tenant, identite="id-1", instant=INSTANT)
    assert erreur.value.status_code == 429


# --- CA-2 : compteurs scopés par tenant et par identité ----------------------


async def test_ca2_meme_identite_dans_deux_tenants_compte_separement(db: AsyncSession):
    politique = _politique(maximum=1)
    tenant_a, tenant_b = _tenant(), _tenant()
    await consomme(db, politique, tenant_id=tenant_a, identite="partagee", instant=INSTANT)
    with pytest.raises(AppError):
        await consomme(db, politique, tenant_id=tenant_a, identite="partagee", instant=INSTANT)
    # Le tenant B n'hérite jamais du compteur du tenant A.
    await consomme(db, politique, tenant_id=tenant_b, identite="partagee", instant=INSTANT)


async def test_ca2_deux_identites_d_un_meme_tenant_comptent_separement(db: AsyncSession):
    politique = _politique(maximum=1)
    tenant = _tenant()
    await consomme(db, politique, tenant_id=tenant, identite="alice", instant=INSTANT)
    await consomme(db, politique, tenant_id=tenant, identite="bob", instant=INSTANT)
    with pytest.raises(AppError):
        await consomme(db, politique, tenant_id=tenant, identite="alice", instant=INSTANT)


def test_ca2_cle_depend_du_tenant_et_de_l_identite_sans_les_exposer():
    cle = cle_limite("tenant-a", "identite-x", "api")
    assert cle != cle_limite("tenant-b", "identite-x", "api")
    assert cle != cle_limite("tenant-a", "identite-y", "api")
    assert "identite-x" not in cle and "tenant-a" not in cle
    assert len(cle) == 64


# --- CA-3 : abus détecté -> événement d'alerte routé -------------------------


async def test_ca3_depassement_emet_un_evenement_d_abus_route(db: AsyncSession, monkeypatch):
    recus = []
    monkeypatch.setattr(ratelimit, "destinataires_abus", [recus.append])
    tenant = _tenant()
    politique = _politique(maximum=1)
    await consomme(db, politique, tenant_id=tenant, identite="ip-suspecte", instant=INSTANT)
    with pytest.raises(AppError):
        await consomme(db, politique, tenant_id=tenant, identite="ip-suspecte", instant=INSTANT)

    assert len(recus) == 1
    evenement = recus[0]
    assert evenement.tenant_id == tenant
    assert evenement.portee == "test-be253"
    # L'identité n'apparaît jamais en clair dans l'événement routé.
    assert "ip-suspecte" not in repr(evenement)


async def test_ca3_requetes_sous_le_seuil_n_emettent_aucun_evenement(db: AsyncSession, monkeypatch):
    recus = []
    monkeypatch.setattr(ratelimit, "destinataires_abus", [recus.append])
    await consomme(db, _politique(maximum=3), tenant_id=_tenant(), identite="calme", instant=INSTANT)
    assert recus == []


# --- CA-4 : aucun score de réputation de tenant -------------------------------


def test_ca4_aucun_score_de_reputation_de_tenant_dans_le_code():
    motif = re.compile(
        r"reput|(tenant|organisation|organization)_?score|score_?(tenant|organisation|organization)",
        re.IGNORECASE,
    )
    trouves = []
    for fichier in RACINE_APP.rglob("*.py"):
        for numero, ligne in enumerate(fichier.read_text(encoding="utf-8").splitlines(), start=1):
            if motif.search(ligne):
                trouves.append(f"{fichier.relative_to(RACINE_APP)}:{numero}")
    assert trouves == []
