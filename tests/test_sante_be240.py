"""Tests de la readiness et du statut technique opérateur (BE-240).

Contrat fixé ici, à implémenter dans `app/operator/health.py` :

- `GET /api/v1/internal/ready` : réservé au réseau interne (liste
  `HEALTH_INTERNAL_NETWORKS`, vide par défaut). Depuis le réseau externe, ou
  si la liste est vide, la route répond 404 (elle n'existe pas pour l'extérieur).
  La réponse liste chaque composant (`name`, `status`), sans secret ni PII.
- `GET /api/v1/admin/status` : réservé à l'opérateur habilité (allowlist
  `OPERATOR_READ_USER_IDS`). Sans droit : 403 `operator_access_denied`.
- Statuts de composant : `ok`, `unavailable`, `unknown`. Le statut global est
  `ready` seulement si tous les composants sont `ok` ; sinon `not ready` (HTTP 503).
  Un composant `unknown` (sonde en erreur inattendue) n'est jamais présenté comme sain.
- Chaque réponse porte `verifiedAt` : l'horodatage UTC de la vérification.

La base indisponible est simulée par surcharge de `get_db`, comme dans
tests/test_statut_technique_be032.py. Le composant `unknown` est simulé en
remplaçant la sonde `base_repond` du module par une fonction qui lève une erreur
inattendue.
"""

import os
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.main import app
from app.audit.models import AuditLog

RESEAU_INTERNE_TEST = ["127.0.0.0/8"]
CHAMPS_COMPOSANT_AUTORISES = {"name", "status"}
CHAMPS_REPONSE_AUTORISES = {"status", "verifiedAt", "components"}


class _SessionEnPanne:
    """Session factice : toute requête échoue comme une base injoignable."""

    async def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, OSError("connexion refusée"))

    async def rollback(self) -> None:
        return None


@pytest.fixture
def base_en_panne():
    """Remplace `get_db` par une session en panne, le temps d'un test."""
    async def _dependance() -> AsyncGenerator:
        yield _SessionEnPanne()

    app.dependency_overrides[get_db] = _dependance
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def reseau_interne(monkeypatch):
    """Déclare le client de test (127.0.0.1 dans ASGITransport) comme réseau interne."""
    monkeypatch.setattr(settings, "HEALTH_INTERNAL_NETWORKS", RESEAU_INTERNE_TEST)


def _composants(body: dict) -> dict[str, str]:
    return {c["name"]: c["status"] for c in body["components"]}


async def test_readiness_repond_composant_par_composant_sans_secret(
    client: AsyncClient, reseau_interne,
):
    response = await client.get("/api/v1/internal/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert set(body) <= CHAMPS_REPONSE_AUTORISES
    assert body["components"], "au moins un composant doit être listé"
    for composant in body["components"]:
        assert set(composant) == CHAMPS_COMPOSANT_AUTORISES
    assert set(_composants(body).values()) == {"ok"}

    # Aucun secret, aucune URL de base, aucun nom de base de test dans le corps.
    texte = response.text
    url_test = os.environ["TEST_DATABASE_URL"]
    assert "postgresql" not in texte
    assert "zylo_t240_test" not in texte
    assert "/var/run/postgresql" not in texte
    assert url_test.split("host=")[-1] not in texte


async def test_readiness_composant_indisponible_rend_non_pret(
    client: AsyncClient, reseau_interne, base_en_panne,
):
    response = await client.get("/api/v1/internal/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not ready"
    assert _composants(body)["database"] == "unavailable"
    assert "connexion refusée" not in response.text


async def test_composant_en_erreur_inattendue_est_inconnu_jamais_sain(
    client: AsyncClient, reseau_interne, monkeypatch,
):
    async def sonde_en_erreur(db):
        raise RuntimeError("état indéterminé")

    monkeypatch.setattr("app.operator.health.base_repond", sonde_en_erreur)

    response = await client.get("/api/v1/internal/ready")

    assert response.status_code == 503
    body = response.json()
    assert _composants(body)["database"] == "unknown"
    assert body["status"] == "not ready"
    assert "état indéterminé" not in response.text


async def test_readiness_refuse_le_reseau_externe_et_liste_vide(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "HEALTH_INTERNAL_NETWORKS", ["10.99.0.0/16"])
    assert (await client.get("/api/v1/internal/ready")).status_code == 404

    monkeypatch.setattr(settings, "HEALTH_INTERNAL_NETWORKS", [])
    assert (await client.get("/api/v1/internal/ready")).status_code == 404


async def test_statut_operateur_sans_droit_donne_403(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.delenv("OPERATOR_READ_USER_IDS", raising=False)
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}

    response = await client.get("/api/v1/admin/status", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "operator_access_denied"


async def test_statut_operateur_avec_droit_liste_les_composants_et_date_de_verification(
    client: AsyncClient, registered_user: dict, monkeypatch,
):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", me.json()["id"])
    avant = datetime.now(timezone.utc) - timedelta(seconds=5)

    response = await client.get(
        "/api/v1/admin/status", headers={**headers, "X-Request-Id": "status-be240-lecture"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert _composants(body)["database"] == "ok"
    assert "email" not in response.text

    verifie = datetime.fromisoformat(body["verifiedAt"].replace("Z", "+00:00"))
    assert verifie.tzinfo is not None
    assert avant <= verifie <= datetime.now(timezone.utc) + timedelta(seconds=5)

    async with AsyncSessionLocal() as db:
        lignes = list((await db.scalars(
            select(AuditLog).where(AuditLog.request_id == "status-be240-lecture", AuditLog.action.like("operator.%"))
        )).all())
    assert len(lignes) == 1
    assert lignes[0].action == "operator.status.read"
    assert lignes[0].changes["outcome"] == "success"


async def test_statut_operateur_et_readiness_portent_la_date_de_verification(
    client: AsyncClient, reseau_interne,
):
    response = await client.get("/api/v1/internal/ready")

    assert response.status_code == 200
    verifie = datetime.fromisoformat(response.json()["verifiedAt"].replace("Z", "+00:00"))
    assert verifie.tzinfo is not None
