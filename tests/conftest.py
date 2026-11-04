import os
import uuid
from datetime import datetime, timezone

# Intention (T-002) : les tests déclarent leur environnement. `test` applique
# les règles strictes de app/core/config.py : aucun secret de repli n'est
# accepté, donc les secrets ci-dessous sont explicites, propres aux tests et
# assez longs. Ils écrasent volontairement le .env du worktree (variables
# d'environnement prioritaires), sans jamais reprendre de valeur réelle.
os.environ["ENVIRONMENT"] = "test"
# Les tests historiques utilisent /auth/register pour créer leurs acteurs.
# Le comportement fail-closed est vérifié séparément avec le réglage désactivé.
os.environ["AUTH_PUBLIC_REGISTRATION_ENABLED"] = "true"
# T-027 : clé de chiffrement de test, propre au dépôt de test, jamais une valeur réelle.
os.environ["APP_FIELD_ENCRYPTION_KEY"] = "test-only-field-encryption-key-" + "0123456789abcdef" * 2
os.environ["JWT_SECRET"] = "test-only-jwt-secret-" + "0123456789abcdef" * 2
os.environ["STORAGE_SIGNED_URL_SECRET"] = "test-only-storage-secret-" + "fedcba9876543210" * 2
# T-037a : transition ouverte pour les tests existants (en-tête Authorization et jetons
# dans le JSON encore acceptés). Les tests de fin de transition la ferment par monkeypatch,
# pour que la suite ne dépende pas de l'horloge réelle.
os.environ["AUTH_HEADER_ACCEPTED_UNTIL"] = "2099-01-01T00:00:00+00:00"

# Le throttle de `run_truck_stop_detection` (2026-09-14) suppose des
# positions réelles espacées dans le temps — en test, des dizaines
# d'ingestions synthétiques partent en quelques millisecondes réelles,
# donc désactivé ici pour que chaque appel recalcule bien comme avant.
os.environ["TRUCK_STOP_DETECTION_THROTTLE_SECONDS"] = "0"

import re
from urllib.parse import parse_qs, urlsplit

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Garde de base de test (T-005). Intention : pytest vide la base à chaque
# session (TRUNCATE de toutes les tables). Il ne doit donc JAMAIS pointer vers
# une base de développement ou partagée. Règles :
#  - TEST_DATABASE_URL doit être définie et non vide, sans valeur de repli ;
#  - le nom de base doit suivre le motif zylo_t<NNN>[a-z]?_test, créé par
#    scripts/dev/env_tache.sh (une base par tâche) ;
#  - seule exception : zylo_office_test, héritée de l'ancien repli, et
#    uniquement si ZYLO_TEST_TOLERER_ZYLO_OFFICE_TEST=1 est posée explicitement.
# Les noms zylo, zylo_office, zylo_dev, zylo_liquid, zylo_recette ne passent
# jamais, quel que soit le port ou l'hôte.
MOTIF_BASE_DE_TEST = re.compile(r"^zylo_t[0-9]{3}[a-z]?_test$")
BASE_TOLEREE_OPT_IN = "zylo_office_test"
VARIABLE_OPT_IN = "ZYLO_TEST_TOLERER_ZYLO_OFFICE_TEST"
COMMANDE_ENV_TACHE = "scripts/dev/env_tache.sh creer <NNN> back"


def _noms_de_base(url: str) -> list[str]:
    """Nom de base de l'URL, et ceux donnés par ?dbname= ou ?database= (asyncpg)."""
    parties = urlsplit(url)
    noms = [parties.path.lstrip("/")]
    requete = parse_qs(parties.query)
    for cle in ("dbname", "database"):
        noms.extend(requete.get(cle, []))
    return noms


def verifie_base_de_test(url: str | None) -> None:
    """Lève pytest.exit (message en français) si la base n'est pas une base de test."""
    if not url:
        pytest.exit(
            "TEST_DATABASE_URL est absente : pytest refuse de démarrer, car il vide la base "
            "de test. Dans un worktree déjà créé : export TEST_DATABASE_URL=\"$(sed -n "
            "'s/^TEST_DATABASE_URL=//p' .env)\". Sinon, créez l'environnement de la tâche : "
            f"{COMMANDE_ENV_TACHE}.",
            returncode=3,
        )
    for nom in _noms_de_base(url):
        if nom == BASE_TOLEREE_OPT_IN and os.environ.get(VARIABLE_OPT_IN) == "1":
            continue
        if not MOTIF_BASE_DE_TEST.match(nom):
            pytest.exit(
                f"Base refusée : « {nom} » n'est pas une base de test (motif attendu : "
                f"zylo_t<NNN>[a-z]?_test). pytest vide cette base à chaque session. "
                f"Créez la base de la tâche avec {COMMANDE_ENV_TACHE} et exportez son "
                "TEST_DATABASE_URL. zylo_office_test n'est tolérée qu'avec "
                f"{VARIABLE_OPT_IN}=1.",
                returncode=3,
            )


verifie_base_de_test(os.environ.get("TEST_DATABASE_URL"))
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]


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
    from app.core.field_crypto import chiffrer
    from app.modules.zylo_liquid.models import HolykellAccount, HolykellDeviceRegistry

    async with AsyncSessionLocal() as db:
        account = HolykellAccount(
            organizationId=uuid.UUID(organization_id),
            holykellUsername=f"user-{uuid.uuid4().hex[:8]}",
            holykellPasswordChiffre=chiffrer("secret"),
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
