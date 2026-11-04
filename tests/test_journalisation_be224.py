"""Tests BE-224 : journalisation structurée, corrélation et redaction.

Couvre les critères CA-1 à CA-4 de la définition (implementation-backend/
tasks-exploitation-architecture.md, section BE-224). Les tests importent les
noms nouveaux à l'intérieur de chaque fonction : chaque test échoue donc pour
sa seule raison, sans faire échouer la collecte du module.
"""

import asyncio
import io
import json
import logging
import sys

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.middleware import RequestIdMiddleware

MOT_DE_PASSE_FACTICE = "Factice-MotDePasse-224"
EMAIL_FACTICE = "jean.dupont.224@example.com"
TENANT_BRUT = "7f3c9e2a-1111-4b5e-9d00-224224224224"


@pytest.fixture
def journal(monkeypatch):
    """Installe le journal applicatif (setup_logging) sur un tampon dédié, pour
    lire exactement les lignes émises ; restaure racine et stdout ensuite."""
    from app.core.logging import setup_logging

    tampon = io.StringIO()
    monkeypatch.setattr(sys, "stdout", tampon)
    racine = logging.getLogger()
    anciens_gestionnaires, ancien_niveau = list(racine.handlers), racine.level
    setup_logging()
    try:
        yield tampon
    finally:
        racine.handlers = anciens_gestionnaires
        racine.setLevel(ancien_niveau)


def _lignes_json(tampon) -> list[dict]:
    """Relit chaque ligne JSON émise dans le tampon du journal."""
    sortie = tampon.getvalue()
    return [json.loads(ligne) for ligne in sortie.splitlines() if ligne.startswith("{")]


async def _integration_fictive() -> None:
    """Appel d'intégration simulé : journalise comme un adaptateur externe."""
    logging.getLogger("zylo_office.integration").info("integration_appelee")


def _application_de_test():
    """Application ASGI minimale encadrée par RequestIdMiddleware.

    Le gestionnaire journalise dans l'API, crée une tâche asynchrone qui
    journalise à son tour, puis appelle une intégration simulée : les trois
    traces doivent partager le même correlationId (CA-1)."""

    async def endpoint(request):
        logging.getLogger("zylo_office.api").info("api_traitee")

        async def tache():
            logging.getLogger("zylo_office.tache").info("tache_asynchrone")

        await asyncio.create_task(tache())
        await _integration_fictive()
        return PlainTextResponse("ok")

    return RequestIdMiddleware(Starlette(routes=[Route("/trace", endpoint)]))


async def _requete(app, headers: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/trace", headers=headers)


# --- CA-1 : corrélation de bout en bout -------------------------------------------


async def test_correlation_id_distinct_du_request_id_dans_la_reponse():
    """Un X-Correlation-Id distinct de X-Request-Id doit être renvoyé tel quel
    (aujourd'hui X-Correlation-Id est une copie du request_id)."""
    reponse = await _requete(
        _application_de_test(),
        {"X-Request-Id": "req-224-A", "X-Correlation-Id": "corr-224-B"},
    )

    assert reponse.headers["X-Request-Id"] == "req-224-A"
    assert reponse.headers["X-Correlation-Id"] == "corr-224-B"


async def test_correlation_id_traverse_api_tache_et_integration(journal):
    """API, tâche asynchrone et intégration journalisent le même correlationId,
    et chaque ligne porte le requestId de la requête."""
    reponse = await _requete(
        _application_de_test(),
        {"X-Request-Id": "req-224-trace", "X-Correlation-Id": "corr-224-trace"},
    )
    assert reponse.status_code == 200

    lignes = [
        ligne
        for ligne in _lignes_json(journal)
        if ligne["logger"] in {"zylo_office.api", "zylo_office.tache", "zylo_office.integration"}
    ]
    assert {ligne["logger"] for ligne in lignes} == {
        "zylo_office.api",
        "zylo_office.tache",
        "zylo_office.integration",
    }
    assert {ligne.get("correlationId") for ligne in lignes} == {"corr-224-trace"}
    assert {ligne.get("requestId") for ligne in lignes} == {"req-224-trace"}


# --- CA-2 : aucun secret ni PII par défaut ----------------------------------------


async def test_redaction_retire_mot_de_passe_et_email_des_journaux(journal):
    """Un mot de passe factice passé en argument de message ou en champ extra,
    et un courriel, n'apparaissent jamais dans la sortie JSON."""
    logging.getLogger("zylo_office.test224").info(
        "connexion password=%s compte=%s",
        MOT_DE_PASSE_FACTICE,
        EMAIL_FACTICE,
        extra={"password": MOT_DE_PASSE_FACTICE, "email": EMAIL_FACTICE},
    )

    sortie = journal.getvalue()
    assert MOT_DE_PASSE_FACTICE not in sortie
    assert EMAIL_FACTICE not in sortie
    assert "connexion" in sortie


# --- CA-3 : tenant pseudonymisé dans les journaux plateforme ----------------------


def test_identifiant_tenant_pseudonymise_de_facon_stable():
    from app.core.logging import pseudonyme_tenant

    premier = pseudonyme_tenant(TENANT_BRUT)
    assert premier == pseudonyme_tenant(TENANT_BRUT)
    assert TENANT_BRUT not in premier
    assert premier != pseudonyme_tenant("autre-tenant-224")


async def test_identifiant_tenant_brut_absent_des_journaux_plateforme(journal):
    from app.core.logging import pseudonyme_tenant

    logging.getLogger("zylo_office.plateforme224").info(
        "acces_organisation", extra={"tenantId": TENANT_BRUT}
    )

    sortie = journal.getvalue()
    assert TENANT_BRUT not in sortie
    assert pseudonyme_tenant(TENANT_BRUT) in sortie


# --- CA-4 : lecture des journaux réservée ------------------------------------------


def test_lecture_des_journaux_refusee_sans_permission_avec_403():
    from app.core.errors import AppError
    from app.core.logging import PERMISSION_LECTURE_JOURNAUX, exige_lecture_journaux

    with pytest.raises(AppError) as erreur:
        exige_lecture_journaux(set())
    assert erreur.value.status_code == 403

    # Avec la permission, aucune exception n'est levée.
    exige_lecture_journaux({PERMISSION_LECTURE_JOURNAUX})
