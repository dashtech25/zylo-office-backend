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
    from app.modules.zylo_liquid.seed import seed_known_permissions
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
    # et des permissions déclarées doit donc être rejoué explicitement ici,
    # sinon "zylo_liquid" et ses permissions n'existent jamais dans la base de
    # test et toute FK vers module.code/permission.code échoue.
    await seed_known_modules()
    await seed_known_permissions()

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


@pytest.fixture
async def zylo_liquid_organization(client: AsyncClient, registered_user: dict, organization: dict):
    """Organisation avec le module zylo_liquid activé — l'activation accorde
    désormais automatiquement au owner toutes les permissions déclarées par ce
    module (app.modules_registry.service.grant_module_permissions_to_owner),
    fixture réutilisable par tous les futurs tests d'endpoints Zylo Liquid
    (Point 3 §20)."""
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    activate_res = await client.post(f"/api/v1/modules/organizations/{organization['id']}/activate", json={"moduleCode": "zylo_liquid"}, headers=headers)
    assert activate_res.status_code == 200, activate_res.text
    return organization


@pytest.fixture
async def test_city() -> dict:
    """Aucun endpoint HTTP n'existe pour le référentiel géographique Core
    (Country/Region/City) — insertion directe via le service, comme pour les
    permissions avant l'existence d'un RBAC HTTP."""
    from app.core.database import AsyncSessionLocal
    from app.shared.geo import City, Country, Region

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        country = Country(isoCode2=suffix[:2].upper(), isoCode3=suffix[:3].upper(), name=f"Testland {suffix}")
        db.add(country)
        await db.flush()
        region = Region(countryId=country.id, name=f"Region {suffix}", code=f"R{suffix}")
        db.add(region)
        await db.flush()
        city = City(regionId=region.id, name=f"City {suffix}")
        db.add(city)
        await db.commit()
        await db.refresh(city)
        return {"id": str(city.id)}
