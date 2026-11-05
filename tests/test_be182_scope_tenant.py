"""Tests BE-182 : scope tenant et identifiants opaques.

Couvre les critères CA-1 à CA-5 de la définition (implementation-backend/
tasks-donnees-api-contrats.md, section BE-182).

Vocabulaire : la définition écrit `tenantId`. Le code de develop porte le même
rôle sous le nom `organizationId` (tenant racine = `organization`, BE-002) ; le
présent fichier garde ce nom existant et ne renomme aucune colonne. L'écart de
nom est signalé au rapport de la tâche.

Les tests de schéma lisent la base de test migrée (`alembic upgrade head`, fait
par `conftest.py`). Les tests d'isolation passent par l'API réelle.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.identity.models import Organization, User
from app.rbac.models import Role, UserRole
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"

# Tables portant `organizationId` qui restent nullables par décision d'origine.
# `audit_event` : `organizationId` est nul pour une portée plateforme, prévue
# mais non implémentée (app/audit/models.py, docstring) ; la portée plateforme
# n'a pas de tenant, donc pas de NOT NULL tant que la question reste ouverte.
TABLES_TENANT_NULLABLE_JUSTIFIEES = {"audit_event"}


def _entetes(utilisateur: dict, organisation_id: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['token']}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _creer_utilisateur(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-182"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "token": token}


async def _creer_organisation(client: AsyncClient, proprietaire: dict) -> str:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": f"Org {uuid.uuid4().hex[:6]}", "slug": f"org-{uuid.uuid4().hex[:10]}"},
        headers=_entetes(proprietaire),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _inserer_organisation() -> uuid.UUID:
    """Organisation minimale insérée directement (pour les tests de contrainte)."""
    async with AsyncSessionLocal() as db:
        org = Organization(name="Org BE-182", slug=f"org-be182-{uuid.uuid4().hex[:12]}", status="active")
        db.add(org)
        await db.commit()
        return org.id


async def _inserer_role(organisation_id: uuid.UUID, code: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=organisation_id, code=code, name=f"Rôle {code}")
        db.add(role)
        await db.commit()
        return role.id


async def _premier_utilisateur() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        utilisateur = User(email=unique_email(), hashedPassword="x", fullName="BE-182")
        db.add(utilisateur)
        await db.commit()
        return utilisateur.id


# ---------------------------------------------------------------------------
# CA-1 : `tenantId` NOT NULL sur chaque table tenant-scoped (test de schéma)
# ---------------------------------------------------------------------------


async def test_ca1_toute_table_tenant_scoped_est_not_null(client: AsyncClient):
    """Chaque table qui porte la colonne de tenant la déclare NOT NULL, sauf les
    exceptions justifiées ci-dessus. Le test lit `information_schema` sur la base
    migrée : il échoue tant qu'une migration n'a pas durci une table."""
    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(
                text(
                    "SELECT table_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = 'organizationId'"
                )
            )
        ).all()

    assert lignes, "aucune table tenant-scoped trouvée : la requête de schéma est fausse"
    nullables = sorted(
        nom for nom, nullable in lignes if nullable == "YES" and nom not in TABLES_TENANT_NULLABLE_JUSTIFIEES
    )
    assert nullables == [], f"colonnes de tenant nullables hors exceptions justifiées : {nullables}"


# ---------------------------------------------------------------------------
# CA-2 : une référence vers un autre tenant est refusée à l'insertion
# ---------------------------------------------------------------------------


async def test_ca2_reference_vers_autre_tenant_refusee_a_l_insertion(client: AsyncClient):
    """Une attribution de rôle dont `organizationId` diffère de celui du rôle
    référencé doit échouer en base : la clé composite (`organizationId`, `roleId`)
    interdit le lien inter-tenant, même avec un identifiant de rôle valide."""
    org_a = await _inserer_organisation()
    org_b = await _inserer_organisation()
    role_b = await _inserer_role(org_b, f"code-be182-{uuid.uuid4().hex[:8]}")
    utilisateur = await _premier_utilisateur()

    async with AsyncSessionLocal() as db:
        db.add(UserRole(userId=utilisateur, organizationId=org_a, roleId=role_b))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


# ---------------------------------------------------------------------------
# CA-3 : un tenant d'un autre tenant renvoie 404
# ---------------------------------------------------------------------------


async def test_ca3_tenant_d_une_autre_organisation_renvoie_404(client: AsyncClient):
    """Un utilisateur membre de B qui demande un chemin portant le tenant A (et
    un sélecteur B cohérent avec lui-même) reçoit 404, jamais 403 ni 200.

    Le code d'erreur renvoyé est `http_404` (enveloppe BE-001) et non
    `organization_not_found` (prévu par app/core/tenant_context.py) : l'écart
    relève de BE-180 et n'est pas testé ici.
    """
    proprietaire_a = await _creer_utilisateur(client)
    org_a = await _creer_organisation(client, proprietaire_a)
    proprietaire_b = await _creer_utilisateur(client)
    org_b = await _creer_organisation(client, proprietaire_b)

    res = await client.post(
        f"/api/v1/organizations/{org_a}/module-roles",
        json={"code": "be182_role", "name": "BE-182", "moduleCode": "zylo_liquid"},
        headers=_entetes(proprietaire_b, org_b),
    )
    assert res.status_code == 404, res.text


# ---------------------------------------------------------------------------
# CA-4 : un identifiant de ressource seul n'accorde aucun accès
# ---------------------------------------------------------------------------


async def test_ca4_identifiant_de_ressource_d_un_autre_tenant_sans_acces(client: AsyncClient):
    """Un rôle de A, identifié par son UUID, ne se supprime pas depuis B : le
    tenant résolu (B) ne contient pas la ressource, donc 404.

    Sans sélecteur de tenant, la requête ne peut pas résoudre de tenant : elle
    ne doit jamais réussir (4xx). La définition écrit 404 ; le code de BE-001 /
    BE-225 renvoie 422 pour un en-tête absent. L'écart est signalé, pas masqué.
    """
    proprietaire_a = await _creer_utilisateur(client)
    org_a = await _creer_organisation(client, proprietaire_a)
    proprietaire_b = await _creer_utilisateur(client)
    org_b = await _creer_organisation(client, proprietaire_b)
    role_a = await _inserer_role(uuid.UUID(org_a), f"code-be182-{uuid.uuid4().hex[:8]}")

    chemin = f"/api/v1/organizations/{org_b}/module-roles/assignments/{role_a}"
    res = await client.delete(chemin, headers=_entetes(proprietaire_b, org_b))
    assert res.status_code == 404, res.text

    sans_selecteur = await client.delete(chemin, headers=_entetes(proprietaire_b))
    assert 400 <= sans_selecteur.status_code < 500, sans_selecteur.text


# ---------------------------------------------------------------------------
# CA-5 : clé locale unique par tenant, pas au-delà
# ---------------------------------------------------------------------------


async def test_ca5_meme_cle_locale_dans_deux_tenants_acceptee(client: AsyncClient):
    """Deux organisations peuvent porter un rôle de même `code`."""
    org_a = await _inserer_organisation()
    org_b = await _inserer_organisation()
    code = f"code-be182-{uuid.uuid4().hex[:8]}"
    await _inserer_role(org_a, code)
    await _inserer_role(org_b, code)

    async with AsyncSessionLocal() as db:
        lignes = (await db.execute(select(Role.id).where(Role.code == code))).all()
    assert len(lignes) == 2


async def test_ca5_meme_cle_locale_dans_un_tenant_refusee(client: AsyncClient):
    """Une même organisation ne peut pas porter deux rôles de même `code`."""
    org_a = await _inserer_organisation()
    code = f"code-be182-{uuid.uuid4().hex[:8]}"
    await _inserer_role(org_a, code)

    async with AsyncSessionLocal() as db:
        db.add(Role(organizationId=org_a, code=code, name="doublon"))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
