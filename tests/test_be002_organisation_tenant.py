"""BE-002 : organisation (tenant racine), modèle et contraintes.

Tests écrits d'après la définition `### BE-002` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.
"""

import inspect
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity import service as identity_service
from app.identity.models import Organization


async def _creer_organisation(name: str, slug: str, status: str = "active") -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name=name, slug=slug, status=status)
        db.add(organisation)
        await db.commit()
        return organisation.id


async def test_be002_ca1_organisation_relue_a_l_identique(client: AsyncClient):
    slug = f"be002-{uuid.uuid4().hex[:10]}"
    organisation_id = await _creer_organisation("Organisation BE-002", slug)

    async with AsyncSessionLocal() as db:
        relue = (await db.execute(select(Organization).where(Organization.id == organisation_id))).scalar_one()

    assert (relue.name, relue.slug, relue.status) == ("Organisation BE-002", slug, "active")


async def test_be002_ca2_slug_en_double_refuse_par_la_base(client: AsyncClient):
    slug = f"be002-{uuid.uuid4().hex[:10]}"
    await _creer_organisation("Première", slug)

    with pytest.raises(IntegrityError):
        await _creer_organisation("Seconde", slug)


async def test_be002_ca3_lectures_publiques_de_l_identite_sont_bornees_par_une_portee(client: AsyncClient):
    # Toute fonction publique de lecture (list_* / get_*) du service identity
    # doit recevoir un paramètre de portée : utilisateur ou organisation.
    portees = {"user_id", "organization_id", "organisation_id"}
    lectures = [
        (nom, fonction)
        for nom, fonction in inspect.getmembers(identity_service, inspect.iscoroutinefunction)
        if not nom.startswith("_") and nom.startswith(("list_", "get_"))
    ]

    assert lectures, "aucune lecture publique trouvée : le contrôle serait vide"
    for nom, fonction in lectures:
        parametres = set(inspect.signature(fonction).parameters)
        assert parametres & portees, f"{nom} ne reçoit aucun paramètre de portée"


async def test_be002_ca4_lecture_de_repository_sans_contexte_organisation_refusee(client: AsyncClient):
    # Contrat cible : une lecture de repository sans contexte d'organisation lève
    # AppError. Le module app/identity/repository.py n'existe pas encore (BE-009).
    from app.identity import repository  # noqa: PLC0415 — volontairement importé ici

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError):
            await repository.lire_organisation(db, uuid.uuid4(), contexte=None)


async def test_be002_ca5_organisation_d_un_autre_tenant_invisible(
    client: AsyncClient, registered_user: dict, organization: dict
):
    # O1 appartient à registered_user ; O2 appartient à un autre utilisateur.
    autre = await client.post(
        "/api/v1/auth/register",
        json={"email": f"be002-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com", "password": "TestPassword123!", "fullName": "Autre"},
    )
    assert autre.status_code in (200, 201), autre.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": autre.json()["email"], "password": "TestPassword123!"},
    )
    autre_headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}
    o2 = await client.post(
        "/api/v1/organizations",
        json={"name": "Organisation O2 secrète", "slug": f"be002-o2-{uuid.uuid4().hex[:8]}"},
        headers=autre_headers,
    )
    assert o2.status_code in (200, 201), o2.text
    o2_id = o2.json()["id"]

    headers = {
        "Authorization": f"Bearer {registered_user['accessToken']}",
        "X-Organization-Id": o2_id,
    }
    res = await client.get("/api/v1/organizations/current", headers=headers)

    assert res.status_code == 404
    assert "Organisation O2 secrète" not in res.text
    assert o2_id not in res.text
