"""BE-031 : console opérateur en lecture seule, routes sous `/api/v1/admin`.

Tests écrits d'après la définition `### BE-031` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.

Routes visées (décision : préfixe `/api/v1/admin`) :
- `GET /api/v1/admin/organizations` (liste) ;
- `GET /api/v1/admin/organizations/{orgId}` (détail abonnement et modules) ;
- `GET /api/v1/admin/requests/{request_id}` (recherche par request ID).

Couverture :
- CA-1 (refus) : un utilisateur absent de `OPERATOR_READ_USER_IDS` reçoit 403 sur les trois routes ;
- CA-2 (refus) : une liste vide refuse toute lecture (fail-closed) ;
- CA-3 : chaque consultation crée une entrée `audit_event` d'action `operator.` ;
- CA-4 : la recherche par request ID distingue `trouvé`, `non trouvé`, `refus` et `erreur` ;
- CA-5 (isolation) : la réponse ne contient que l'état d'abonnement et de module ;
- CA-6 : PUT, POST et DELETE sur ces routes renvoient 405.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal

CHEMIN_LISTE = "/api/v1/admin/organizations"
CHEMIN_DETAIL = "/api/v1/admin/organizations/{org_id}"
CHEMIN_TRACE = "/api/v1/admin/requests/{request_id}"


def _entetes(registered_user: dict) -> dict:
    return {"Authorization": f"Bearer {registered_user['accessToken']}"}


async def _autoriser(client: AsyncClient, registered_user: dict, monkeypatch, autorise: bool = True) -> str:
    """Place l'utilisateur de test dans l'allowlist (`autorise`) ou un autre identifiant seulement."""
    me = await client.get("/api/v1/auth/me", headers=_entetes(registered_user))
    user_id = me.json()["id"]
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", user_id if autorise else str(uuid.uuid4()))
    return user_id


async def _entrees(request_id: str) -> list[AuditEvent]:
    """Entrées `operator.` de `audit_event` portant ce request ID."""
    async with AsyncSessionLocal() as db:
        return list((await db.scalars(
            select(AuditEvent).where(AuditEvent.request_id == request_id, AuditEvent.action.like("operator.%"))
        )).all())


async def _semer_trace(user_id: str, request_id: str) -> None:
    """Insère un événement d'audit portant le request ID, pour le cas « trouvé »."""
    async with AsyncSessionLocal() as db:
        db.add(AuditEvent(
            organizationId=None, actorUserId=uuid.UUID(user_id), action="billing.invoice.create",
            entityType="Invoice", entityId=uuid.uuid4(),
            summary=f"Facture créée (request_id={request_id})", changes=None,
            request_id=request_id, eventId=uuid.uuid4().hex, result="success",
        ))
        await db.commit()


async def test_be031_ca1_utilisateur_non_liste_recoit_403_sur_trois_routes(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    await _autoriser(client, registered_user, monkeypatch, autorise=False)
    chemins = [CHEMIN_LISTE, CHEMIN_DETAIL.format(org_id=organization["id"]), CHEMIN_TRACE.format(request_id="be031-ca1")]

    for chemin in chemins:
        reponse = await client.get(chemin, headers=_entetes(registered_user))
        assert reponse.status_code == 403, chemin
        assert reponse.json()["error"]["code"] == "operator_access_denied", chemin


async def test_be031_ca2_liste_vide_refuse_toute_lecture(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "")
    chemins = [CHEMIN_LISTE, CHEMIN_DETAIL.format(org_id=organization["id"]), CHEMIN_TRACE.format(request_id="be031-ca2")]

    for chemin in chemins:
        reponse = await client.get(chemin, headers=_entetes(registered_user))
        assert reponse.status_code == 403, chemin


async def test_be031_ca3_chaque_consultation_cree_une_entree_operateur(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    await _autoriser(client, registered_user, monkeypatch)
    cas = {
        "be031-ca3-liste": CHEMIN_LISTE,
        "be031-ca3-detail": CHEMIN_DETAIL.format(org_id=organization["id"]),
        "be031-ca3-trace": CHEMIN_TRACE.format(request_id="be031-ca3-inconnue"),
    }
    for request_id, chemin in cas.items():
        reponse = await client.get(chemin, headers={**_entetes(registered_user), "X-Request-Id": request_id})
        assert reponse.status_code == 200, chemin

    for request_id in cas:
        entrees = await _entrees(request_id)
        assert len(entrees) == 1, request_id
        assert entrees[0].action.startswith("operator."), request_id


async def test_be031_ca4_recherche_distingue_trouve_non_trouve_refus_et_erreur(
    client: AsyncClient, registered_user: dict, monkeypatch,
):
    user_id = await _autoriser(client, registered_user, monkeypatch)
    await _semer_trace(user_id, "be031-ca4-trouve")

    trouve = await client.get(
        CHEMIN_TRACE.format(request_id="be031-ca4-trouve"),
        headers={**_entetes(registered_user), "X-Request-Id": "be031-ca4-lecture-trouve"},
    )
    assert trouve.status_code == 200
    assert trouve.json()["found"] is True
    assert trouve.json()["outcome"] == "found"

    non_trouve = await client.get(
        CHEMIN_TRACE.format(request_id="be031-ca4-absent"),
        headers={**_entetes(registered_user), "X-Request-Id": "be031-ca4-lecture-absente"},
    )
    assert non_trouve.status_code == 200
    assert non_trouve.json()["found"] is False
    assert non_trouve.json()["outcome"] == "not_found"

    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(uuid.uuid4()))
    refus = await client.get(
        CHEMIN_TRACE.format(request_id="be031-ca4-refus"),
        headers={**_entetes(registered_user), "X-Request-Id": "be031-ca4-lecture-refus"},
    )
    assert refus.status_code == 403
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", user_id)

    def _echec(*_args, **_kwargs):
        raise SQLAlchemyError("panne simulée de la base")

    monkeypatch.setattr("app.operator.router._chercher_traces", _echec)
    erreur = await client.get(
        CHEMIN_TRACE.format(request_id="be031-ca4-erreur"),
        headers={**_entetes(registered_user), "X-Request-Id": "be031-ca4-lecture-erreur"},
    )
    assert erreur.status_code == 503
    assert erreur.json()["error"]["code"] == "request_trace_error"

    issues = {}
    for request_id in ("be031-ca4-lecture-trouve", "be031-ca4-lecture-absente", "be031-ca4-lecture-refus", "be031-ca4-lecture-erreur"):
        (entree,) = await _entrees(request_id)
        issues[request_id] = (entree.result, (entree.changes or {}).get("outcome"))
    assert issues == {
        "be031-ca4-lecture-trouve": ("success", "found"),
        "be031-ca4-lecture-absente": ("success", "not_found"),
        "be031-ca4-lecture-refus": ("refused", "refused"),
        "be031-ca4-lecture-erreur": ("error", "error"),
    }


async def test_be031_ca5_reponses_sans_contenu_tenant(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    await _autoriser(client, registered_user, monkeypatch)
    headers = _entetes(registered_user)

    liste = await client.get(CHEMIN_LISTE, headers=headers)
    detail = await client.get(CHEMIN_DETAIL.format(org_id=organization["id"]), headers=headers)
    trace = await client.get(CHEMIN_TRACE.format(request_id="be031-ca5"), headers=headers)
    assert liste.status_code == detail.status_code == trace.status_code == 200

    for ligne in liste.json()["data"]:
        assert set(ligne) == {"id", "name", "slug", "status"}
    assert set(detail.json()) == {"organization", "subscription", "modules"}
    assert set(detail.json()["organization"]) == {"id", "name", "slug", "status"}
    for module in detail.json()["modules"]:
        assert set(module) == {"moduleCode", "name", "status"}
    assert set(trace.json()) == {"requestId", "found", "outcome", "events"}
    assert registered_user["email"] not in liste.text
    assert registered_user["email"] not in detail.text


async def test_be031_ca6_ecriture_renvoie_405(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    await _autoriser(client, registered_user, monkeypatch)
    headers = _entetes(registered_user)
    chemins = [CHEMIN_LISTE, CHEMIN_DETAIL.format(org_id=organization["id"]), CHEMIN_TRACE.format(request_id="be031-ca6")]

    for chemin in chemins:
        for methode in ("PUT", "POST", "DELETE"):
            reponse = await client.request(methode, chemin, headers=headers, json={})
            assert reponse.status_code == 405, f"{methode} {chemin}"


async def test_be031_prefixe_admin_unique(client: AsyncClient, registered_user: dict, monkeypatch):
    """Les routes opérateur sont montées sous /api/v1/admin ; l'ancien préfixe n'existe plus."""
    await _autoriser(client, registered_user, monkeypatch)
    headers = _entetes(registered_user)

    ancien = await client.get("/api/v1/operator/organizations", headers=headers)
    assert ancien.status_code == 404
    nouveau = await client.get(CHEMIN_LISTE, headers=headers)
    assert nouveau.status_code == 200

