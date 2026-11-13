"""BE-003 : utilisateur global et unicité du courriel.

Tests écrits d'après la définition `### BE-003` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.security import verify_password
from app.identity.models import Organization, OrganizationUser, User

MOT_DE_PASSE = "TestPassword123!"


async def test_be003_ca1_courriel_en_double_casse_differente_refuse(client: AsyncClient):
    base = f"be003-{uuid.uuid4().hex[:10]}"
    async with AsyncSessionLocal() as db:
        db.add(User(email=f"{base}@Zylo-Test.example.com", hashedPassword="x", fullName="Premier"))
        await db.commit()

    async with AsyncSessionLocal() as db:
        db.add(User(email=f"{base.upper()}@zylo-test.EXAMPLE.com", hashedPassword="x", fullName="Second"))
        try:
            await db.commit()
        except IntegrityError:
            return
    raise AssertionError("un second compte au même courriel (casse différente) a été accepté")


async def test_be003_ca2_mot_de_passe_jamais_en_clair(client: AsyncClient):
    email = f"be003-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    res = await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Clair"})
    assert res.status_code in (200, 201), res.text

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()

    assert user.hashedPassword != MOT_DE_PASSE
    assert MOT_DE_PASSE not in user.hashedPassword
    assert user.hashedPassword.startswith("$2")  # condensat bcrypt
    assert verify_password(MOT_DE_PASSE, user.hashedPassword)


async def test_be003_ca3_utilisateur_inexistant_sans_session(client: AsyncClient):
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": f"inconnu-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com", "password": MOT_DE_PASSE},
    )

    assert res.status_code == 401
    corps = res.json()
    assert "accessToken" not in corps
    assert "refreshToken" not in corps


async def test_be003_ca4_meme_courriel_dans_deux_organisations_une_seule_ligne_user(client: AsyncClient):
    email = f"be003-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    async with AsyncSessionLocal() as db:
        utilisateur = User(email=email, hashedPassword="x", fullName="Multi")
        db.add(utilisateur)
        await db.flush()
        for indice in (1, 2):
            organisation = Organization(name=f"Org {indice}", slug=f"be003-{uuid.uuid4().hex[:10]}")
            db.add(organisation)
            await db.flush()
            db.add(OrganizationUser(organizationId=organisation.id, userId=utilisateur.id))
        await db.commit()
        user_id = utilisateur.id

    async with AsyncSessionLocal() as db:
        lignes = (await db.execute(select(func.count()).select_from(User).where(func.lower(User.email) == email.lower()))).scalar_one()
        appartenances = (await db.execute(select(func.count()).select_from(OrganizationUser).where(OrganizationUser.userId == user_id))).scalar_one()

    assert lignes == 1
    assert appartenances == 2
