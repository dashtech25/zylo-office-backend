"""Tests BE-181 : contexte de requête (correlationId, operationId, request_id de BE-001).

Couvre les critères CA-1 à CA-5 de la définition (implementation-backend/
tasks-donnees-api-contrats.md, section BE-181). Application ASGI minimale
encadrée par RequestIdMiddleware, sans base de données.

Les noms nouveaux (contextvars, champs) sont importés dans chaque fonction :
chaque test échoue donc pour sa seule raison, sans faire échouer la collecte.
"""

import io
import json
import logging
import sys
import uuid

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core.middleware import RequestIdMiddleware

CLE_IDEMPOTENCE_A = "cle-be181-operation-a-0001"
CLE_IDEMPOTENCE_B = "cle-be181-operation-b-0002"
SECRET_AUTORISATION = "Bearer SECRET-BE181-JETON-0123456789"
SECRET_COOKIE = "session=SECRET-BE181-COOKIE-9876543210"


def _lignes_contexte(request) -> dict:
    """Lit le contexte posé par le middleware (lecture côté route)."""
    etat = request.state
    return {
        "request_id": getattr(etat, "request_id", None),
        "correlation_id": getattr(etat, "correlation_id", None),
        "operation_id": getattr(etat, "operation_id", None),
    }


async def _echo(request):
    """Route GET : renvoie le contexte vu par la route, et journalise une ligne."""
    logging.getLogger("zylo_office.be181").info("echo_appele")
    return JSONResponse(_lignes_contexte(request))


async def _mutation(request):
    """Route POST : mutation fictive qui journalise, et renvoie le contexte."""
    logging.getLogger("zylo_office.be181").info("mutation_appelee")
    return JSONResponse(_lignes_contexte(request), status_code=201)


async def _journalise_secret(request):
    """Route qui journalise, par erreur, un en-tête d'autorisation et un cookie
    dans des champs `extra` et dans le message (cas à rejeter par la redaction)."""
    logging.getLogger("zylo_office.be181").info(
        "appel_avec_secrets",
        extra={
            "authorization": request.headers.get("authorization"),
            "cookie": request.headers.get("cookie"),
        },
    )
    logging.getLogger("zylo_office.be181").info(
        "diagnostic token=SECRET-BE181-JETON-0123456789 pour l'appel"
    )
    return JSONResponse({"ok": True})


def _application_de_test():
    """Application ASGI minimale encadrée par RequestIdMiddleware."""
    app = Starlette(
        routes=[
            Route("/echo", _echo, methods=["GET"]),
            Route("/mutation", _mutation, methods=["POST"]),
            Route("/secrets", _journalise_secret, methods=["GET"]),
        ]
    )
    return RequestIdMiddleware(app)


@pytest.fixture
def journal(monkeypatch):
    """Installe le journal applicatif (setup_logging) sur un tampon dédié."""
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
    return [json.loads(ligne) for ligne in tampon.getvalue().splitlines() if ligne.startswith("{")]


async def test_ca1_reponse_porte_request_id_de_be001_distinct_par_requete():
    """CA-1 : chaque réponse porte le request_id produit par BE-001, vu aussi par
    la route ; deux requêtes successives ont deux identifiants distincts."""
    transport = httpx.ASGITransport(app=_application_de_test())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        premiere = await client.get("/echo")
        seconde = await client.get("/echo")

    id1 = premiere.headers["X-Request-Id"]
    id2 = seconde.headers["X-Request-Id"]
    assert premiere.json()["request_id"] == id1, "la route doit voir le request_id de la réponse"
    assert seconde.json()["request_id"] == id2
    assert id1 != id2, "deux requêtes successives doivent avoir deux request_id distincts"


async def test_ca2_correlation_client_reprise_a_l_identique():
    """CA-2 : un X-Correlation-Id valide fourni par le client est repris tel quel,
    sans écraser le request_id ; sans en-tête, un correlationId est généré."""
    transport = httpx.ASGITransport(app=_application_de_test())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        fourni = await client.get("/echo", headers={"X-Correlation-Id": "corr.be181:client-01"})
        absent = await client.get("/echo")

    assert fourni.headers["X-Correlation-Id"] == "corr.be181:client-01"
    assert fourni.json()["correlation_id"] == "corr.be181:client-01"
    assert fourni.json()["request_id"] == fourni.headers["X-Request-Id"]
    assert fourni.json()["request_id"] != "corr.be181:client-01"

    genere = absent.headers["X-Correlation-Id"]
    assert genere, "un correlationId doit être généré à défaut"
    uuid.UUID(genere)  # lève ValueError si la valeur générée n'est pas un UUID


async def test_ca3_operation_id_stable_lors_d_un_rejeu_de_mutation():
    """CA-3 : chaque mutation reçoit un operationId ; un rejeu (même Idempotency-Key,
    même route) reçoit le même operationId ; une autre clé en reçoit un autre."""
    transport = httpx.ASGITransport(app=_application_de_test())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        initial = await client.post("/mutation", headers={"Idempotency-Key": CLE_IDEMPOTENCE_A})
        rejeu = await client.post("/mutation", headers={"Idempotency-Key": CLE_IDEMPOTENCE_A})
        autre = await client.post("/mutation", headers={"Idempotency-Key": CLE_IDEMPOTENCE_B})
        sans_cle_1 = await client.post("/mutation")
        sans_cle_2 = await client.post("/mutation")

    op_initial = initial.json()["operation_id"]
    assert op_initial, "une mutation doit recevoir un operationId"
    uuid.UUID(op_initial)
    assert rejeu.json()["operation_id"] == op_initial, "un rejeu doit réutiliser le même operationId"
    assert autre.json()["operation_id"] != op_initial
    assert sans_cle_1.json()["operation_id"] != sans_cle_2.json()["operation_id"]


async def test_ca3_operation_id_absent_des_lectures():
    """CA-3 (bord) : une lecture (GET) ne reçoit pas d'operationId de mutation."""
    transport = httpx.ASGITransport(app=_application_de_test())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        lecture = await client.get("/echo", headers={"Idempotency-Key": CLE_IDEMPOTENCE_A})

    assert lecture.json()["operation_id"] is None


async def test_ca4_chaque_ligne_de_journal_porte_le_request_id(journal):
    """CA-4 : chaque ligne émise pendant la requête porte le requestId de la
    réponse ; et l'operationId d'une mutation, quand il existe."""
    transport = httpx.ASGITransport(app=_application_de_test())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.post("/mutation", headers={"Idempotency-Key": CLE_IDEMPOTENCE_A})

    lignes = [ligne for ligne in _lignes_json(journal) if ligne["logger"] == "zylo_office.be181"]
    assert lignes, "la route doit avoir journalisé"
    request_id = reponse.headers["X-Request-Id"]
    assert all(ligne["requestId"] == request_id for ligne in lignes)
    op_id = reponse.json()["operation_id"]
    assert all(ligne.get("operationId") == op_id for ligne in lignes)


async def test_ca5_secret_d_en_tete_jamais_ecrit_dans_le_journal(journal):
    """CA-5 : un jeton d'autorisation ou un cookie ne figure jamais dans le
    journal, ni dans un champ `extra`, ni dans le texte d'un message."""
    transport = httpx.ASGITransport(app=_application_de_test())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get(
            "/secrets",
            headers={"Authorization": SECRET_AUTORISATION, "Cookie": SECRET_COOKIE},
        )

    sortie = journal.getvalue()
    assert "SECRET-BE181-JETON-0123456789" not in sortie
    assert "SECRET-BE181-COOKIE-9876543210" not in sortie
