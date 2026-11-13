"""BE-229 : accès opérateur nominatif, JIT et approbation.

Tests écrits d'après la définition `### BE-229` de
implementation-backend/tasks-exploitation-architecture.md, avant le code.

Routes testées (chemins proposés par la définition, non définitifs) :
- `POST   /api/v1/admin/access-requests`
- `POST   /api/v1/admin/access-requests/{request_id}/approve`
- `DELETE /api/v1/admin/access-requests/{request_id}`

Fonction testée directement : `app.operator.access.exiger_acces_operateur`, la
décision « accès accordé et encore valide pour ce compte, ce tenant et cette
action », réutilisée par les routes de support.

Couverture :
- CA-1 : un opérateur hors allowlist serveur reçoit 403 ;
- CA-2 : auto-approbation refusée (403) ;
- CA-3 : accès accordé qui expire à l'échéance est refusé ; demande expirée refusée (403) ;
- CA-4 : révocation rend l'accès refusé immédiatement ;
- CA-5 : l'accès ne vaut que pour le tenant et l'action approuvés ;
- CA-6 : inventaire des routes, aucune route d'impersonation exposée.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.database import AsyncSessionLocal, engine

MOT_DE_PASSE = "TestPassword123!"
ACTION_CONSULTATION = "consulter_abonnement"
ACTION_AUTRE = "modifier_abonnement"
MOTIF = "Diagnostic de facturation demandé par le client"
CHEMIN = "/api/v1/admin/access-requests"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Les tests changent de boucle asyncio : le pool est vidé après chaque test."""
    yield
    await engine.dispose()


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    """Compte de test sans rôle particulier. Retourne son identifiant et son jeton."""
    email = f"be229-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-229"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    return {"id": me.json()["id"], "accessToken": jetons["accessToken"]}


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


def _allowlist(monkeypatch, *operateurs: dict) -> None:
    """Pose l'allowlist serveur d'exploitation (variable d'environnement, comme BE-030)."""
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", ",".join(o["id"] for o in operateurs))


async def _demande(client: AsyncClient, demandeur: dict, tenant_id: str, action: str = ACTION_CONSULTATION, duree: int = 30) -> dict:
    reponse = await client.post(
        CHEMIN,
        json={"tenantId": tenant_id, "action": action, "motif": MOTIF, "dureeMinutes": duree},
        headers=_entetes(demandeur),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()


async def _approuver(client: AsyncClient, approbateur: dict, demande: dict):
    return await client.post(f"{CHEMIN}/{demande['accessRequestId']}/approve", headers=_entetes(approbateur))


async def _accorder(client: AsyncClient, demandeur: dict, approbateur: dict, tenant_id: str, action: str = ACTION_CONSULTATION) -> dict:
    demande = await _demande(client, demandeur, tenant_id, action=action)
    reponse = await _approuver(client, approbateur, demande)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


async def _organisation(client: AsyncClient) -> dict:
    proprietaire = await _nouvel_utilisateur(client)
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant BE-229", "slug": f"tenant-be229-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return reponse.json()


async def _verifier(user_id: str, tenant_id: str, action: str) -> None:
    """Appelle la décision d'accès ; lève AppError(403) si refusée."""
    from app.operator.access import exiger_acces_operateur

    async with AsyncSessionLocal() as db:
        await exiger_acces_operateur(db, uuid.UUID(user_id), uuid.UUID(tenant_id), action)


async def _forcer_expiration(request_id: str, quand: datetime) -> None:
    """Déplace l'échéance d'une ligne en base (horloge contrôlée par le test)."""
    from app.operator.access import OperatorAccessRequest

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(OperatorAccessRequest)
            .where(OperatorAccessRequest.accessRequestId == uuid.UUID(request_id))
            .values(expiresAt=quand)
        )
        await db.commit()


# ---------------------------------------------------------------------------
# CA-1 : opérateur sans allowlist serveur -> 403
# ---------------------------------------------------------------------------


async def test_be229_ca1_operateur_hors_allowlist_recoit_403_a_la_creation(client: AsyncClient, monkeypatch):
    organisation = await _organisation(client)
    demandeur = await _nouvel_utilisateur(client)
    _allowlist(monkeypatch, {"id": str(uuid.uuid4())})

    reponse = await client.post(
        CHEMIN,
        json={"tenantId": organisation["id"], "action": ACTION_CONSULTATION, "motif": MOTIF, "dureeMinutes": 30},
        headers=_entetes(demandeur),
    )

    assert reponse.status_code == 403


async def test_be229_ca1_demande_sans_allowlist_n_est_pas_creee(client: AsyncClient, monkeypatch):
    organisation = await _organisation(client)
    demandeur = await _nouvel_utilisateur(client)
    _allowlist(monkeypatch)

    await client.post(
        CHEMIN,
        json={"tenantId": organisation["id"], "action": ACTION_CONSULTATION, "motif": MOTIF, "dureeMinutes": 30},
        headers=_entetes(demandeur),
    )

    _allowlist(monkeypatch, demandeur)
    from app.operator.access import OperatorAccessRequest
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        lignes = (await db.scalars(select(OperatorAccessRequest).where(OperatorAccessRequest.tenantId == uuid.UUID(organisation["id"])))).all()
    assert lignes == []


# ---------------------------------------------------------------------------
# CA-2 : auto-approbation refusée
# ---------------------------------------------------------------------------


async def test_be229_ca2_auto_approbation_refusee(client: AsyncClient, monkeypatch):
    organisation = await _organisation(client)
    operateur = await _nouvel_utilisateur(client)
    _allowlist(monkeypatch, operateur)
    demande = await _demande(client, operateur, organisation["id"])

    reponse = await _approuver(client, operateur, demande)

    assert reponse.status_code == 403


async def test_be229_ca2_approbateur_hors_allowlist_refuse(client: AsyncClient, monkeypatch):
    organisation = await _organisation(client)
    demandeur = await _nouvel_utilisateur(client)
    approbateur = await _nouvel_utilisateur(client)
    _allowlist(monkeypatch, demandeur)
    demande = await _demande(client, demandeur, organisation["id"])

    reponse = await _approuver(client, approbateur, demande)

    assert reponse.status_code == 403


# ---------------------------------------------------------------------------
# CA-3 : expiration de l'accès accordé et de la demande
# ---------------------------------------------------------------------------


async def test_be229_ca3_acces_accorde_valide_avant_echeance(client: AsyncClient, monkeypatch):
    organisation = await _organisation(client)
    demandeur = await _nouvel_utilisateur(client)
    approbateur = await _nouvel_utilisateur(client)
    _allowlist(monkeypatch, demandeur, approbateur)
    accorde = await _accorder(client, demandeur, approbateur, organisation["id"])

    await _verifier(demandeur["id"], organisation["id"], ACTION_CONSULTATION)

    assert accorde["status"] == "approuvee"


async def test_be229_ca3_acces_accorde_refuse_apres_echeance(client: AsyncClient, monkeypatch):
    from app.core.errors import AppError

    organisation = await _organisation(client)
    demandeur = await _nouvel_utilisateur(client)
    approbateur = await _nouvel_utilisateur(client)
    _allowlist(monkeypatch, demandeur, approbateur)
    accorde = await _accorder(client, demandeur, approbateur, organisation["id"])
    await _forcer_expiration(accorde["accessRequestId"], datetime.now(timezone.utc) - timedelta(seconds=1))

    with pytest.raises(AppError) as erreur:
        await _verifier(demandeur["id"], organisation["id"], ACTION_CONSULTATION)

    assert erreur.value.status_code == 403


async def test_be229_ca3_demande_expiree_refusee_a_l_approbation(client: AsyncClient, monkeypatch):
    organisation = await _organisation(client)
    demandeur = await _nouvel_utilisateur(client)
    approbateur = await _nouvel_utilisateur(client)
    _allowlist(monkeypatch, demandeur, approbateur)
    demande = await _demande(client, demandeur, organisation["id"])
    await _forcer_expiration(demande["accessRequestId"], datetime.now(timezone.utc) - timedelta(seconds=1))

    reponse = await _approuver(client, approbateur, demande)

    assert reponse.status_code == 403


# ---------------------------------------------------------------------------
# CA-4 : la révocation rend l'accès refusé immédiatement
# ---------------------------------------------------------------------------


async def test_be229_ca4_revocation_rend_l_acces_refuse_immediatement(client: AsyncClient, monkeypatch):
    from app.core.errors import AppError

    organisation = await _organisation(client)
    demandeur = await _nouvel_utilisateur(client)
    approbateur = await _nouvel_utilisateur(client)
    _allowlist(monkeypatch, demandeur, approbateur)
    accorde = await _accorder(client, demandeur, approbateur, organisation["id"])
    await _verifier(demandeur["id"], organisation["id"], ACTION_CONSULTATION)

    reponse = await client.delete(f"{CHEMIN}/{accorde['accessRequestId']}", headers=_entetes(approbateur))
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["status"] == "revoquee"
    assert reponse.json()["revokedAt"] is not None

    with pytest.raises(AppError) as erreur:
        await _verifier(demandeur["id"], organisation["id"], ACTION_CONSULTATION)
    assert erreur.value.status_code == 403


async def test_be229_ca4_revocation_hors_allowlist_refusee(client: AsyncClient, monkeypatch):
    organisation = await _organisation(client)
    demandeur = await _nouvel_utilisateur(client)
    approbateur = await _nouvel_utilisateur(client)
    _allowlist(monkeypatch, demandeur, approbateur)
    accorde = await _accorder(client, demandeur, approbateur, organisation["id"])
    _allowlist(monkeypatch, demandeur)

    reponse = await client.delete(f"{CHEMIN}/{accorde['accessRequestId']}", headers=_entetes(approbateur))

    assert reponse.status_code == 403


# ---------------------------------------------------------------------------
# CA-5 : isolation tenant et action
# ---------------------------------------------------------------------------


async def test_be229_ca5_acces_limite_au_tenant_approuve(client: AsyncClient, monkeypatch):
    from app.core.errors import AppError

    tenant_a = await _organisation(client)
    tenant_b = await _organisation(client)
    demandeur = await _nouvel_utilisateur(client)
    approbateur = await _nouvel_utilisateur(client)
    _allowlist(monkeypatch, demandeur, approbateur)
    await _accorder(client, demandeur, approbateur, tenant_a["id"])

    await _verifier(demandeur["id"], tenant_a["id"], ACTION_CONSULTATION)
    with pytest.raises(AppError) as erreur:
        await _verifier(demandeur["id"], tenant_b["id"], ACTION_CONSULTATION)
    assert erreur.value.status_code == 403


async def test_be229_ca5_acces_limite_a_l_action_approuvee(client: AsyncClient, monkeypatch):
    from app.core.errors import AppError

    organisation = await _organisation(client)
    demandeur = await _nouvel_utilisateur(client)
    approbateur = await _nouvel_utilisateur(client)
    _allowlist(monkeypatch, demandeur, approbateur)
    await _accorder(client, demandeur, approbateur, organisation["id"], action=ACTION_CONSULTATION)

    with pytest.raises(AppError) as erreur:
        await _verifier(demandeur["id"], organisation["id"], ACTION_AUTRE)
    assert erreur.value.status_code == 403


async def test_be229_ca5_tenant_absent_renvoie_404_a_la_demande(client: AsyncClient, monkeypatch):
    demandeur = await _nouvel_utilisateur(client)
    _allowlist(monkeypatch, demandeur)

    reponse = await client.post(
        CHEMIN,
        json={"tenantId": str(uuid.uuid4()), "action": ACTION_CONSULTATION, "motif": MOTIF, "dureeMinutes": 30},
        headers=_entetes(demandeur),
    )

    assert reponse.status_code == 404


# ---------------------------------------------------------------------------
# CA-6 : inventaire des routes, aucune impersonation exposée
# ---------------------------------------------------------------------------


def test_be229_ca6_aucune_route_d_impersonation_exposee():
    from app.main import app
    from tests.route_inventory import inventaire

    infos = inventaire(app)
    suspects = [
        f"{info.method} {info.path}"
        for info in infos
        if any(motif in info.path.lower() for motif in ("impersonat", "usurp", "/sudo", "switch-user"))
    ]

    assert suspects == []


def test_be229_ca6_routes_d_acces_operateur_sont_gardees():
    from app.main import app
    from tests.route_inventory import inventaire

    routes = {
        (info.method, info.path)
        for info in inventaire(app)
        if info.path.startswith("/api/v1/admin/access-requests")
    }

    assert routes == {
        ("POST", "/api/v1/admin/access-requests"),
        ("POST", "/api/v1/admin/access-requests/{request_id}/approve"),
        ("DELETE", "/api/v1/admin/access-requests/{request_id}"),
    }
