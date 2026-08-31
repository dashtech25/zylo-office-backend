import os
import uuid

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://zylo_office:zylo_office_dev@localhost:5432/zylo_office_test"
)

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session", autouse=True)
def apply_migrations():
    """Base de test dédiée (jamais la base de dev) — migrations appliquées une
    seule fois pour toute la session de test."""
    alembic_cfg = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    yield


@pytest.fixture
async def client():
    from app.core.database import engine
    from app.main import app
    from app.modules_registry.seed import seed_known_modules

    # pytest-asyncio donne à chaque test sa propre boucle d'événements, mais
    # `engine` est un singleton créé une seule fois à l'import du module — ses
    # connexions poolées restent liées à la boucle qui les a ouvertes. Sans ce
    # dispose(), le test suivant réutilise une connexion d'une boucle fermée et
    # asyncpg lève "another operation is in progress". On force donc un pool
    # neuf, lié à la boucle courante, avant chaque test.
    await engine.dispose()

    # httpx.ASGITransport ne déclenche pas les événements "startup" de FastAPI
    # (contrairement à un vrai serveur uvicorn) — le seed des modules connus
    # doit donc être rejoué explicitement ici, sinon "zylo_liquid" n'existe
    # jamais dans la base de test et toute FK vers module.code échoue.
    await seed_known_modules()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def unique_email() -> str:
    return f"test-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"


@pytest.fixture
async def registered_user(client: AsyncClient):
    email = unique_email()
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Test User"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    tokens = login.json()
    return {"email": email, "password": password, "accessToken": tokens["accessToken"], "refreshToken": tokens["refreshToken"]}


@pytest.fixture
async def organization(client: AsyncClient, registered_user: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    res = await client.post("/api/v1/organizations", json={"name": "Test Org", "slug": f"test-org-{uuid.uuid4().hex[:8]}"}, headers=headers)
    return res.json()
