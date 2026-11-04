"""BE-120 : socle de portée administration (plateforme ou tenant explicite).

Tests écrits d'après la définition `### BE-120` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Couverture :
- CA-1 : les portées `platform` et `tenant:<id>` sont distinctes ; une portée
  mal formée est rejetée (422) ;
- CA-2 (refus de droit) : la portée `platform` sur un contenu tenant renvoie 403 ;
- CA-3 (isolation tenant) : un administrateur global sans affectation tenant
  reçoit 403 (et non 404) sur le contenu du tenant A ;
- CA-4 (refus de droit) : un sujet sans aucune affectation reçoit 403 sur toute
  route d'administration.

Aucune route n'est ajoutée par BE-120 : CA-2 et CA-3 sont testés sur la fonction
de garde elle-même, CA-4 sur les routes `/api/v1/admin` existantes.
"""

import uuid

import pytest
from fastapi import Request
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import User
from app.operator.scope import (
    assert_tenant_content_scope,
    admin_scope_from_request,
    parse_admin_scope,
    require_admin_scope,
)

CHEMIN_LISTE = "/api/v1/admin/organizations"
CHEMIN_TRACE = "/api/v1/admin/requests/{request_id}"


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


def _requete(valeur_entete: str | None) -> Request:
    """Requête Starlette minimale portant (ou non) l'en-tête de portée."""
    entetes = [] if valeur_entete is None else [(b"x-admin-scope", valeur_entete.encode())]
    return Request({
        "type": "http", "method": "GET", "path": CHEMIN_LISTE,
        "headers": entetes, "path_params": {}, "query_string": b"",
    })


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    """Second compte, sans adhésion à l'organisation de test."""
    email = f"be120-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    mot_de_passe = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": mot_de_passe, "fullName": "Admin BE-120"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": mot_de_passe})
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    return {"id": me.json()["id"], "accessToken": jetons["accessToken"]}


async def _charger_utilisateur(identifiant: str) -> User:
    async with AsyncSessionLocal() as db:
        return await db.get(User, uuid.UUID(identifiant))


# ---------------------------------------------------------------------------
# CA-1 : distinction des portées et rejet des portées mal formées
# ---------------------------------------------------------------------------


def test_be120_ca1_portees_plateforme_et_tenant_sont_distinctes():
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    plateforme = parse_admin_scope("platform")
    tenant_a = parse_admin_scope(f"tenant:{org_a}")
    tenant_b = parse_admin_scope(f"tenant:{org_b}")

    assert plateforme.is_platform
    assert not tenant_a.is_platform
    assert tenant_a.organization_id == org_a
    assert plateforme != tenant_a
    assert tenant_a != tenant_b


@pytest.mark.parametrize("brut_builder", [
    lambda org: "",
    lambda org: "PLATFORM",
    lambda org: "global",
    lambda org: "tenant:",
    lambda org: "tenant:pas-un-uuid",
    lambda org: f"tenant:{org}x",
    lambda org: f"tenant:{str(org).upper()}",
    lambda org: f"tenant :{org}",
    lambda org: f"tenant:{org}/",
])
def test_be120_ca1_portee_mal_formee_rejetee_422(brut_builder):
    brut = brut_builder(uuid.uuid4())
    with pytest.raises(AppError) as info:
        parse_admin_scope(brut)
    assert info.value.status_code == 422
    assert info.value.code == "admin_scope_invalid"


def test_be120_ca1_en_tete_absent_vaut_plateforme_et_en_tete_mal_forme_422():
    assert admin_scope_from_request(_requete(None)).is_platform
    with pytest.raises(AppError) as info:
        admin_scope_from_request(_requete("tenant:n-importe-quoi"))
    assert info.value.status_code == 422


# ---------------------------------------------------------------------------
# CA-2 : la portée plateforme ne donne jamais accès au contenu tenant
# ---------------------------------------------------------------------------


def test_be120_ca2_portee_plateforme_refusee_sur_contenu_tenant_403():
    with pytest.raises(AppError) as info:
        assert_tenant_content_scope(parse_admin_scope("platform"), uuid.uuid4())
    assert info.value.status_code == 403


def test_be120_ca2_portee_tenant_acceptee_pour_son_tenant_seulement():
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    assert_tenant_content_scope(parse_admin_scope(f"tenant:{org_a}"), org_a)
    with pytest.raises(AppError) as info:
        assert_tenant_content_scope(parse_admin_scope(f"tenant:{org_a}"), org_b)
    assert info.value.status_code == 403


# ---------------------------------------------------------------------------
# CA-3 : administrateur global sans affectation tenant
# ---------------------------------------------------------------------------


async def test_be120_ca3_admin_global_sans_affectation_recoit_403_sur_tenant_a(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    admin = await _nouvel_utilisateur(client)
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", admin["id"])
    utilisateur = await _charger_utilisateur(admin["id"])

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as info:
            await require_admin_scope(_requete(f"tenant:{organization['id']}"), utilisateur, db)

    assert info.value.status_code == 403
    assert info.value.code == "admin_scope_denied"


async def test_be120_ca3_admin_global_avec_affectation_tenant_obtient_la_portee(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    # Le propriétaire de l'organisation est à la fois dans l'allowlist (autorité
    # plateforme) et membre actif du tenant : la portée tenant est accordée.
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", (await client.get("/api/v1/auth/me", headers=_entetes(registered_user))).json()["id"])
    proprietaire = await _charger_utilisateur((await client.get("/api/v1/auth/me", headers=_entetes(registered_user))).json()["id"])

    async with AsyncSessionLocal() as db:
        portee = await require_admin_scope(_requete(f"tenant:{organization['id']}"), proprietaire, db)

    assert not portee.is_platform
    assert str(portee.organization_id) == organization["id"]


# ---------------------------------------------------------------------------
# CA-4 : sujet sans aucune affectation, refus sur toute route d'administration
# ---------------------------------------------------------------------------


async def test_be120_ca4_sujet_sans_affectation_recoit_403_sur_toute_route_admin(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(uuid.uuid4()))
    chemins = [CHEMIN_LISTE, CHEMIN_TRACE.format(request_id="be120-ca4")]

    for chemin in chemins:
        reponse = await client.get(chemin, headers=_entetes(registered_user))
        assert reponse.status_code == 403, chemin


async def test_be120_ca4_membre_non_habilite_recoit_403_sur_portee_tenant(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    # Membre actif du tenant mais hors autorité plateforme : aucune portée admin.
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(uuid.uuid4()))
    utilisateur = await _charger_utilisateur((await client.get("/api/v1/auth/me", headers=_entetes(registered_user))).json()["id"])

    async with AsyncSessionLocal() as db:
        for valeur in (None, f"tenant:{organization['id']}"):
            with pytest.raises(AppError) as info:
                await require_admin_scope(_requete(valeur), utilisateur, db)
            assert info.value.status_code == 403, valeur
