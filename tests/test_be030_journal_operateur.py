"""BE-030 : journal opérateur des lectures sensibles, écrit dans `audit_event`.

Tests écrits d'après la définition `### BE-030` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.
Décision D2 : la table `operatorAuditLog` disparaît ; chaque lecture opérateur
devient une entrée de `audit_event` dont l'action est préfixée `operator.`.

Couverture :
- CA-1 : chaque lecture opérateur crée exactement une entrée ;
- CA-2 : l'entrée porte acteur, portée, action, cible, résultat et request ID ;
- CA-3 (refus) : une consultation refusée est journalisée avec `result = refused` ;
- CA-4 : aucune charge utile de réponse n'est stockée ;
- CA-5 : upgrade puis downgrade ciblés réussissent, une seule tête Alembic.
"""

import asyncio
import uuid

import pytest
import pytest_asyncio
from alembic import command
from httpx import AsyncClient
from sqlalchemy import select, text

from app.audit.models import AuditEvent
from app.core import migrations
from app.core.database import AsyncSessionLocal, engine
from app.core.migrations import config_alembic

# Révision de la migration BE-030 (remplace operatorAuditLog par audit_event).
REVISION_BE030 = "e5f6a7b8c9d0"


@pytest_asyncio.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Les tests de migration changent de boucle asyncio : le pool est vidé après chaque test."""
    yield
    await engine.dispose()


async def _moi(client: AsyncClient, registered_user: dict, monkeypatch, autorise: bool = True) -> tuple[dict, str]:
    """Retourne les en-têtes d'authentification et l'identifiant de l'utilisateur de test.

    Si `autorise` est vrai, l'utilisateur est ajouté à la liste d'exploitation ; sinon la
    liste ne contient qu'un autre identifiant (consultation refusée)."""
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    user_id = me.json()["id"]
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", user_id if autorise else str(uuid.uuid4()))
    return headers, user_id


async def _entrees_operateur(request_id: str) -> list[AuditEvent]:
    """Lit dans `audit_event` les entrées opérateur portant ce request ID."""
    async with AsyncSessionLocal() as db:
        return list((await db.scalars(
            select(AuditEvent).where(AuditEvent.request_id == request_id, AuditEvent.action.like("operator.%"))
        )).all())


async def test_be030_ca1_chaque_lecture_operateur_cree_exactement_une_entree(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    headers, _ = await _moi(client, registered_user, monkeypatch)

    reponses = {
        "be030-ca1-liste": "/api/v1/operator/organizations",
        "be030-ca1-organisation": f"/api/v1/operator/organizations/{organization['id']}",
        "be030-ca1-trace": "/api/v1/operator/requests/be030-trace-inconnue",
    }
    for request_id, chemin in reponses.items():
        reponse = await client.get(chemin, headers={**headers, "X-Request-Id": request_id})
        assert reponse.status_code == 200, chemin

    for request_id in reponses:
        assert len(await _entrees_operateur(request_id)) == 1, request_id


async def test_be030_ca2_entree_porte_acteur_portee_action_cible_resultat_et_request_id(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    headers, user_id = await _moi(client, registered_user, monkeypatch)

    reponse = await client.get(
        f"/api/v1/operator/organizations/{organization['id']}",
        headers={**headers, "X-Request-Id": "be030-ca2-organisation"},
    )
    assert reponse.status_code == 200

    (entree,) = await _entrees_operateur("be030-ca2-organisation")
    assert str(entree.actorUserId) == user_id
    assert entree.scopeResourceType == "organization"
    assert str(entree.scopeResourceId) == organization["id"]
    assert entree.action == "operator.organization.read"
    assert entree.entityType == "organization"
    assert str(entree.entityId) == organization["id"]
    assert entree.result == "success"
    assert entree.request_id == "be030-ca2-organisation"
    assert entree.organizationId is None or str(entree.organizationId) == organization["id"]
    assert entree.summary


async def test_be030_ca2_lecture_de_portee_plateforme_sans_organisation_cible(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    headers, _ = await _moi(client, registered_user, monkeypatch)

    reponse = await client.get("/api/v1/operator/organizations", headers={**headers, "X-Request-Id": "be030-ca2-liste"})
    assert reponse.status_code == 200

    (entree,) = await _entrees_operateur("be030-ca2-liste")
    assert entree.scopeResourceType == "platform"
    assert entree.scopeResourceId is None
    assert entree.action == "operator.organization.list"
    assert entree.result == "success"


async def test_be030_ca3_consultation_refusee_journalisee_avec_resultat_refus(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    headers, user_id = await _moi(client, registered_user, monkeypatch, autorise=False)

    reponse = await client.get(
        "/api/v1/operator/organizations", headers={**headers, "X-Request-Id": "be030-ca3-refus"},
    )
    assert reponse.status_code == 403
    assert reponse.json()["error"]["code"] == "operator_access_denied"

    entrees = await _entrees_operateur("be030-ca3-refus")
    assert len(entrees) == 1
    assert entrees[0].result == "refused"
    assert str(entrees[0].actorUserId) == user_id


async def test_be030_ca4_aucune_charge_utile_de_reponse_stockee(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    headers, _ = await _moi(client, registered_user, monkeypatch)
    nom = organization["name"]

    await client.get("/api/v1/operator/organizations", headers={**headers, "X-Request-Id": "be030-ca4-liste"})
    await client.get(
        f"/api/v1/operator/organizations/{organization['id']}",
        headers={**headers, "X-Request-Id": "be030-ca4-organisation"},
    )

    for request_id in ("be030-ca4-liste", "be030-ca4-organisation"):
        (entree,) = await _entrees_operateur(request_id)
        # Le journal ne garde que des métadonnées : pas de corps de réponse, pas de nom d'organisation.
        assert set(entree.changes or {}) <= {"outcome"}
        assert nom not in entree.summary
        assert nom not in str(entree.changes or {})


async def test_be030_ca5_upgrade_puis_downgrade_ciblés_reussissent_et_tete_unique(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    headers, _ = await _moi(client, registered_user, monkeypatch)
    await client.get("/api/v1/operator/requests/be030-ca5-reprise", headers={**headers, "X-Request-Id": "be030-ca5-reprise"})

    assert migrations.script_directory().get_heads() == [REVISION_BE030], "une seule tête, la migration BE-030"
    cfg = config_alembic()

    await asyncio.to_thread(command.downgrade, cfg, "-1")
    try:
        async with engine.begin() as conn:
            table = await conn.scalar(text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'operatorAuditLog'"
            ))
            repris = (await conn.execute(text(
                'SELECT action, outcome FROM "operatorAuditLog" WHERE "requestId" = :rid'
            ), {"rid": "be030-ca5-reprise"})).all()
        assert table == 1, "le downgrade recrée la table operatorAuditLog"
        assert [(a, o) for a, o in repris] == [("request_trace.read", "not_found")]
    finally:
        await asyncio.to_thread(command.upgrade, cfg, "head")
        await engine.dispose()

    assert migrations.script_directory().get_heads() == [REVISION_BE030]
    async with engine.begin() as conn:
        table = await conn.scalar(text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'operatorAuditLog'"
        ))
    assert table == 0, "la table operatorAuditLog est retirée après upgrade"
    entrees = await _entrees_operateur("be030-ca5-reprise")
    assert [e.action for e in entrees] == ["operator.request_trace.read"]
