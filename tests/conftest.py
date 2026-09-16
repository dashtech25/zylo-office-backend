import os
import uuid
from datetime import datetime, timezone

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://zylo_office:zylo_office_dev@localhost:5432/zylo_office_test"
)
# Le throttle de `run_truck_stop_detection` (2026-09-14) suppose des
# positions réelles espacées dans le temps — en test, des dizaines
# d'ingestions synthétiques partent en quelques millisecondes réelles,
# donc désactivé ici pour que chaque appel recalcule bien comme avant.
os.environ["TRUCK_STOP_DETECTION_THROTTLE_SECONDS"] = "0"

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
    _reset_test_database()
    yield


def _reset_test_database() -> None:
    """Vide la base de test en début de session — la base n'est jamais
    recréée entre deux runs : les lignes laissées par les runs précédents
    s'accumulent et saturent les petits espaces de codes (ex.
    country.isoCode2 = 2 caractères hexa = 256 valeurs — cause des collisions
    « duplicate key uq_country_isoCode2 » observées en suite complète, tests
    isolés pourtant verts). Après TRUNCATE chaque run repart d'une base
    migrée mais vide et devient déterministe.

    Aucune migration ne seed country/region/city/currency (vérifié sur
    alembic/versions/*.py) : la purge après upgrade est sûre. Alembic_version
    est préservée (les migrations viennent d'être appliquées) ; toute
    migration future qui seederait des données devra exempter ses tables ici."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _wipe() -> None:
        engine = create_async_engine(os.environ["DATABASE_URL"])
        try:
            async with engine.begin() as conn:
                tables = (await conn.execute(text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                ))).scalars().all()
                tables = [t for t in tables if t != "alembic_version"]
                if tables:
                    quoted = ", ".join(f'"{t}"' for t in tables)
                    # RESTART IDENTITY : séquences remises à zéro, ids déterministes.
                    await conn.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
        finally:
            await engine.dispose()

    asyncio.run(_wipe())


@pytest.fixture
async def client():
    from app.core.database import engine
    from app.main import app
    from app.modules.zylo_liquid.seed import seed_known_permissions
    from app.modules.zylo_tanker.seed import seed_known_permissions as seed_zylo_tanker_permissions
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
    await seed_zylo_tanker_permissions()

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
    from sqlalchemy.exc import IntegrityError

    from app.core.database import AsyncSessionLocal
    from app.shared.geo import City, Country, Region

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        # `isoCode2` est limité à 2 caractères (norme ISO 3166-1) et la base
        # de test est persistante entre les sessions : tirage renouvelé sur
        # violation d'unicité (même pattern que les helpers `_create_currency`
        # des fichiers de test Zylo Liquid).
        for _ in range(20):
            suffix = uuid.uuid4().hex[:8]
            country = Country(isoCode2=suffix[:2].upper(), isoCode3=suffix[:3].upper(), name=f"Testland {suffix}")
            db.add(country)
            try:
                await db.flush()
                break
            except IntegrityError:
                await db.rollback()
        else:
            raise AssertionError("impossible d'allouer un code pays unique")
        region = Region(countryId=country.id, name=f"Region {suffix}", code=f"R{suffix}")
        db.add(region)
        await db.flush()
        city = City(regionId=region.id, name=f"City {suffix}")
        db.add(city)
        await db.commit()
        await db.refresh(city)
        return {"id": str(city.id)}


async def register_holykell_sensor(organization_id: str, serial_number: str, measurement_type: str) -> int:
    """Aucun endpoint HTTP ne crée un HolykellAccount/HolykellDeviceRegistry —
    ces lignes n'existent en pratique que via la synchronisation de fond avec
    h-smartlink.com (hors périmètre API). Insertion directe via le service,
    comme pour le référentiel géo Core."""
    import random

    from app.core.database import AsyncSessionLocal
    from app.modules.zylo_liquid.models import HolykellAccount, HolykellDeviceRegistry

    async with AsyncSessionLocal() as db:
        account = HolykellAccount(
            organizationId=uuid.UUID(organization_id),
            holykellUsername=f"user-{uuid.uuid4().hex[:8]}",
            holykellPassword="secret",
        )
        db.add(account)
        await db.flush()

        sensor_id = random.randint(100000, 999999)
        now = datetime.now(timezone.utc).replace(tzinfo=None)  # colonnes TIMESTAMP WITHOUT TIME ZONE
        registry_entry = HolykellDeviceRegistry(
            holykellAccountId=account.id,
            hkGroupId=1,
            hkGroupName="Groupe Test",
            hkDeviceId=1,
            hkSerialNumber=serial_number,
            hkSensorId=sensor_id,
            hkSensorName=f"{measurement_type} Cuve Test",
            syncFrom=now,
            discoveredAt=now,
        )
        db.add(registry_entry)
        await db.commit()
        return sensor_id
