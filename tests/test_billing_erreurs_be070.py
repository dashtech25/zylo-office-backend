"""Codes d'erreur normalisés du domaine facturation (BE-070).

Ces tests fixent le catalogue défini dans `implementation-backend/tasks-abonnements-facturation.md`
(section BE-070) et les statuts HTTP recommandés par QE-FAC-02 et QE-FAC-19 :

- CA-1 : chacun des 17 codes est rendu dans l'enveloppe BE-001
  (`error.code`, `error.message`, `request_id`), sans détail interne ;
- CA-2 et CA-3 : refus de droit et isolation tenant. Aucune route facturation
  n'existe encore (0 route dans BE-070) : seule l'enveloppe est testée ici ;
- CA-4 : `RESULT_UNKNOWN` ne se mappe jamais sur un échec.

Les routes de test (`/api/v1/_test_be070/...`) ne sont montées que le temps
d'un test, puis retirées, comme dans tests/test_contrat_erreurs_be001.py.
"""

import httpx
import pytest
from fastapi import APIRouter

from app.billing.errors import BILLING_ERRORS, BillingErrorCode, billing_error
from app.main import app

_CATALOGUE_ATTENDU = {
    "FORBIDDEN": 403,
    "SCOPE_MISMATCH": 403,
    "INVALID_TRANSITION": 409,
    "QUOTE_EXPIRED": 422,
    "CONSENT_REQUIRED": 422,
    "PRICE_NOT_CONFIGURED": 422,
    "TAX_NOT_CONFIGURED": 422,
    "CURRENCY_NOT_CONFIGURED": 422,
    "PAYMENT_DECLINED": 402,
    "RESULT_UNKNOWN": 202,
    "PROVIDER_UNAVAILABLE": 503,
    "DUPLICATE": 409,
    "VERSION_CONFLICT": 409,
    "REFUND_LIMIT_EXCEEDED": 422,
    "ENTITLEMENT_SYNC_PENDING": 409,
    "RECONCILIATION_REQUIRED": 409,
    "APPROVAL_REQUIRED": 409,
}

_PREFIXE_ROUTES_TEST = "/api/v1/_test_be070"
_SECRET_INTERNE = "secret-interne-be070-4c9d"

_routes_test = APIRouter()


@_routes_test.get("/_test_be070/{code}")
def _route_qui_leve_un_code(code: str) -> None:
    """Lève l'erreur du catalogue désignée par `code` (route témoin)."""
    raise billing_error(BillingErrorCode(code))


@_routes_test.get("/_test_be070/interne/fuite")
def _route_qui_leve_une_exception_brute() -> None:
    """Une exception Python brute ne doit jamais sortir avec son texte interne."""
    raise RuntimeError(_SECRET_INTERNE)


@pytest.fixture
def routes_de_test():
    """Monte les routes de test sur l'application réelle, puis les retire."""
    app.include_router(_routes_test, prefix="/api/v1")
    try:
        yield
    finally:
        app.router.routes = [
            route
            for route in app.router.routes
            if not getattr(route, "path", "").startswith(_PREFIXE_ROUTES_TEST)
        ]


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def test_catalogue_contient_exactement_les_17_codes():
    assert {code.value for code in BillingErrorCode} == set(_CATALOGUE_ATTENDU)
    assert len(BillingErrorCode) == 17


def test_chaque_code_a_une_fiche_documentee():
    """Docstring de chaque code : une description et un message par défaut non vides."""
    assert set(BILLING_ERRORS) == set(BillingErrorCode)
    for code, fiche in BILLING_ERRORS.items():
        assert fiche.description.strip(), f"description absente pour {code}"
        assert fiche.message.strip(), f"message par défaut absent pour {code}"


def test_module_errors_a_une_documentation_de_module():
    import app.billing.errors as module

    assert module.__doc__ and "catalogue" in module.__doc__.lower()


@pytest.mark.parametrize("code", sorted(_CATALOGUE_ATTENDU))
def test_statut_http_recommande_par_code(code: str):
    """Statuts issus de QE-FAC-02 et QE-FAC-19 (POINTS-OUVERTS.md)."""
    assert BILLING_ERRORS[BillingErrorCode(code)].http_status == _CATALOGUE_ATTENDU[code]


@pytest.mark.parametrize("code", sorted(_CATALOGUE_ATTENDU))
async def test_code_rendu_dans_enveloppe_be001(code: str, client, routes_de_test):
    """CA-1 : code, message et request_id dans l'enveloppe BE-001, sans détail."""
    async with client:
        reponse = await client.get(f"/api/v1/_test_be070/{code}")

    assert reponse.status_code == _CATALOGUE_ATTENDU[code]
    corps = reponse.json()
    assert set(corps) == {"error", "request_id"}
    erreur = corps["error"]
    assert set(erreur) == {"code", "message", "field_errors", "details"}
    assert erreur["code"] == code
    assert isinstance(erreur["message"], str) and erreur["message"]
    assert erreur["details"] == []
    assert erreur["field_errors"] == {}
    assert corps["request_id"] == reponse.headers["X-Request-Id"]
    assert "Traceback" not in reponse.text
    assert "Error" not in reponse.text


async def test_exception_brute_ne_fuit_pas_de_detail_interne(client, routes_de_test):
    async with client:
        reponse = await client.get("/api/v1/_test_be070/interne/fuite")

    assert reponse.status_code == 500
    assert reponse.json()["error"]["code"] == "internal_error"
    assert _SECRET_INTERNE not in reponse.text


async def test_result_unknown_jamais_mappe_sur_un_echec(client, routes_de_test):
    """CA-4 : RESULT_UNKNOWN est un résultat incertain, pas un `failed`."""
    fiche = BILLING_ERRORS[BillingErrorCode.RESULT_UNKNOWN]
    assert fiche.outcome != "failed"
    assert fiche.http_status != 500

    async with client:
        reponse = await client.get("/api/v1/_test_be070/RESULT_UNKNOWN")

    assert reponse.status_code == 202
    assert reponse.json()["error"]["code"] == "RESULT_UNKNOWN"
    assert "failed" not in reponse.text.lower()


def test_forbidden_ne_depend_pas_de_l_objet_visé():
    """CA-2 (niveau enveloppe) : un refus de droit a le même code et le même statut
    quel que soit l'objet. Les routes réelles seront testées avec BE-076 et suivants."""
    premier = billing_error(BillingErrorCode.FORBIDDEN)
    second = billing_error(BillingErrorCode.FORBIDDEN)
    assert (premier.code, premier.status_code, premier.message) == (
        second.code,
        second.status_code,
        second.message,
    )
    assert premier.status_code == 403


def test_billing_error_renvoie_une_app_error_du_catalogue():
    from app.core.errors import AppError

    exc = billing_error(BillingErrorCode.DUPLICATE)
    assert isinstance(exc, AppError)
    assert exc.code == "DUPLICATE"
    assert exc.status_code == 409
    assert exc.message == BILLING_ERRORS[BillingErrorCode.DUPLICATE].message
