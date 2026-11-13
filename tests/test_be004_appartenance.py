"""BE-004 : appartenance utilisateur-organisation (table `organization_user`).

Tests écrits d'après la définition `### BE-004` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.

Périmètre : CA-1 (deux contextes distincts), CA-2 (non-membre refusé en 404
sans donnée de l'organisation), CA-3 (suppression de l'appartenance retire
l'accès à la requête suivante). Les tests passent par les routes réelles :
`X-Organization-Id` reste un sélecteur, la preuve est l'appartenance en base.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser

MOT_DE_PASSE = "TestPassword123!"


async def _inscrire_et_connecter(client: AsyncClient, nom: str) -> dict:
    """Crée un compte et renvoie ses en-têtes d'authentification et son identifiant."""
    email = f"be004-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": nom})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    jetons = login.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jetons['accessToken']}"})
    assert me.status_code == 200, me.text
    return {"authorization": f"Bearer {jetons['accessToken']}", "userId": me.json()["id"]}


async def _creer_organisation(client: AsyncClient, proprietaire: dict, nom: str) -> str:
    """Crée une organisation ; son créateur en devient membre (create_organization)."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be004-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": proprietaire["authorization"]},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _entetes(utilisateur: dict, organisation_id: str) -> dict:
    return {"Authorization": utilisateur["authorization"], "X-Organization-Id": organisation_id}


async def test_be004_ca1_utilisateur_rattache_a_deux_organisations_a_deux_contextes_distincts(client: AsyncClient):
    alice = await _inscrire_et_connecter(client, "Alice")
    o1 = await _creer_organisation(client, alice, "Organisation O1")
    o2 = await _creer_organisation(client, alice, "Organisation O2")

    liste = await client.get("/api/v1/organizations", headers={"Authorization": alice["authorization"]})
    assert liste.status_code == 200, liste.text
    assert {org["id"] for org in liste.json()} >= {o1, o2}

    contexte_1 = await client.get("/api/v1/organizations/current", headers=_entetes(alice, o1))
    contexte_2 = await client.get("/api/v1/organizations/current", headers=_entetes(alice, o2))
    assert contexte_1.status_code == 200, contexte_1.text
    assert contexte_2.status_code == 200, contexte_2.text
    assert contexte_1.json()["id"] == o1
    assert contexte_2.json()["id"] == o2
    assert contexte_1.json()["name"] == "Organisation O1"
    assert contexte_2.json()["name"] == "Organisation O2"


async def test_be004_ca1_une_seule_appartenance_par_couple_utilisateur_organisation(client: AsyncClient):
    alice = await _inscrire_et_connecter(client, "Alice")
    o1 = await _creer_organisation(client, alice, "Organisation unique")

    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(
                select(OrganizationUser).where(
                    OrganizationUser.organizationId == uuid.UUID(o1),
                    OrganizationUser.userId == uuid.UUID(alice["userId"]),
                )
            )
        ).scalars().all()
        assert len(lignes) == 1
        doublon = OrganizationUser(organizationId=lignes[0].organizationId, userId=lignes[0].userId)
        db.add(doublon)
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_be004_ca2_non_membre_n_obtient_aucune_donnee_de_l_organisation_en_404(client: AsyncClient):
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire")
    intrus = await _inscrire_et_connecter(client, "Intrus")
    o2 = await _creer_organisation(client, proprietaire, "Organisation O2 privée")
    o1 = await _creer_organisation(client, intrus, "Organisation O1 de l'intrus")

    # Lecture de l'organisation courante avec l'en-tête d'une organisation étrangère.
    courant = await client.get("/api/v1/organizations/current", headers=_entetes(intrus, o2))
    assert courant.status_code == 404, courant.text
    assert courant.json().get("code", courant.json().get("error", {}).get("code")) in (
        "organization_not_found",
        None,
    )
    assert "Organisation O2 privée" not in courant.text

    # Route portant l'identifiant de l'organisation étrangère : même refus uniforme.
    par_chemin = await client.get(
        f"/api/v1/organizations/{o2}/protected-demo", headers=_entetes(intrus, o2)
    )
    assert par_chemin.status_code == 404, par_chemin.text

    # La liste de l'intrus ne contient pas l'organisation de l'autre.
    liste = await client.get("/api/v1/organizations", headers={"Authorization": intrus["authorization"]})
    ids = {org["id"] for org in liste.json()}
    assert o2 not in ids
    assert o1 in ids


async def test_be004_ca3_suppression_de_l_appartenance_retire_l_acces_a_la_requete_suivante(client: AsyncClient):
    alice = await _inscrire_et_connecter(client, "Alice")
    o1 = await _creer_organisation(client, alice, "Organisation retirée")

    avant = await client.get("/api/v1/organizations/current", headers=_entetes(alice, o1))
    assert avant.status_code == 200, avant.text

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(OrganizationUser).where(
                OrganizationUser.organizationId == uuid.UUID(o1),
                OrganizationUser.userId == uuid.UUID(alice["userId"]),
            )
        )
        await db.commit()
        restant = await db.scalar(
            select(func.count()).select_from(OrganizationUser).where(
                OrganizationUser.organizationId == uuid.UUID(o1),
                OrganizationUser.userId == uuid.UUID(alice["userId"]),
            )
        )
        assert restant == 0

    apres = await client.get("/api/v1/organizations/current", headers=_entetes(alice, o1))
    assert apres.status_code == 404, apres.text
    assert "Organisation retirée" not in apres.text
