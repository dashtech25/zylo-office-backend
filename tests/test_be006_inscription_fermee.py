"""BE-006 : inscription publique fermée par défaut.

Chaque test correspond à un critère d'acceptation CA-n de la définition
`implementation-backend/tasks-socle-tenant-identite.md`, section BE-006.
Route couverte : POST /api/v1/auth/register. La garde de configuration est
`AUTH_PUBLIC_REGISTRATION_ENABLED` (fermée par défaut, refusée hors
development et test). `tests/conftest.py` ouvre cette garde pour la suite
historique ; chaque test ci-dessous la règle explicitement par monkeypatch.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.config import ConfigurationSecretError, Settings, settings
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User

from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
SECRET_FORT = "fort-0123456789abcdef0123456789abcdef"
SECRET_FORT_STORAGE = "stockage-fedcba9876543210fedcba9876543210"
DB_FORTE = "postgresql+asyncpg://zylo_test:mdp-propre-7H3kQ9@localhost:5432/zylo_test"
SECRET_CHIFFREMENT = "chiffrement-" + "0123456789abcdef" * 2
VARIABLES_CONFIG = (
    "ENVIRONMENT", "JWT_SECRET", "STORAGE_SIGNED_URL_SECRET", "DATABASE_URL",
    "APP_FIELD_ENCRYPTION_KEY", "AUTH_PUBLIC_REGISTRATION_ENABLED",
)


def _charge(payload_email: str) -> dict:
    return {"email": payload_email, "password": MOT_DE_PASSE, "fullName": "BE006"}


async def _compte_existe(email: str) -> bool:
    async with AsyncSessionLocal() as db:
        nombre = await db.scalar(select(func.count()).select_from(User).where(func.lower(User.email) == email.lower()))
    return nombre > 0


async def test_ca1_garde_fermee_renvoie_404_et_ne_cree_aucun_utilisateur(client: AsyncClient, monkeypatch):
    """CA-1 (refus) : garde fermée, 404 `registration_disabled`, aucun utilisateur créé."""
    monkeypatch.setattr(settings, "AUTH_PUBLIC_REGISTRATION_ENABLED", False)
    email = unique_email()

    res = await client.post("/api/v1/auth/register", json=_charge(email))

    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "registration_disabled"
    assert await _compte_existe(email) is False


async def test_ca2_garde_ouverte_renvoie_201_et_cree_un_utilisateur(client: AsyncClient, monkeypatch):
    """CA-2 : garde ouverte, inscription 201 et utilisateur créé en base."""
    monkeypatch.setattr(settings, "AUTH_PUBLIC_REGISTRATION_ENABLED", True)
    email = unique_email()

    res = await client.post("/api/v1/auth/register", json=_charge(email))

    assert res.status_code == 201, res.text
    assert res.json()["email"] == email
    assert await _compte_existe(email) is True


def _config_production(monkeypatch, **valeurs):
    for nom in VARIABLES_CONFIG:
        monkeypatch.delenv(nom, raising=False)
    base = {
        "ENVIRONMENT": "production",
        "JWT_SECRET": SECRET_FORT,
        "STORAGE_SIGNED_URL_SECRET": SECRET_FORT_STORAGE,
        "DATABASE_URL": DB_FORTE,
        "APP_FIELD_ENCRYPTION_KEY": SECRET_CHIFFREMENT,
    }
    base.update(valeurs)
    for nom, valeur in base.items():
        monkeypatch.setenv(nom, valeur)


def test_ca3_production_sans_configuration_refuse_l_inscription(monkeypatch):
    """CA-3 : en production sans variable explicite, l'inscription publique est fermée."""
    _config_production(monkeypatch)

    assert Settings(_env_file=None).AUTH_PUBLIC_REGISTRATION_ENABLED is False


def test_ca3_production_avec_inscription_forcee_au_demarrage_est_refusee(monkeypatch):
    """CA-3 (refus) : `true` explicite en production fait échouer le démarrage."""
    _config_production(monkeypatch, AUTH_PUBLIC_REGISTRATION_ENABLED="true")

    with pytest.raises(ConfigurationSecretError, match="AUTH_PUBLIC_REGISTRATION_ENABLED"):
        Settings(_env_file=None)


async def test_ca4_inscription_ne_cree_aucune_appartenance_a_une_organisation(
    client: AsyncClient, monkeypatch, organization: dict
):
    """CA-4 (isolation) : l'inscription ne rattache le nouvel utilisateur à aucune organisation existante."""
    monkeypatch.setattr(settings, "AUTH_PUBLIC_REGISTRATION_ENABLED", True)
    organisation_id = uuid.UUID(organization["id"])

    async with AsyncSessionLocal() as db:
        avant = await db.scalar(
            select(func.count()).select_from(OrganizationUser).where(OrganizationUser.organizationId == organisation_id)
        )

    email = unique_email()
    res = await client.post("/api/v1/auth/register", json=_charge(email))
    assert res.status_code == 201, res.text
    nouvel_utilisateur = uuid.UUID(res.json()["id"])

    async with AsyncSessionLocal() as db:
        apres = await db.scalar(
            select(func.count()).select_from(OrganizationUser).where(OrganizationUser.organizationId == organisation_id)
        )
        appartenances = await db.scalar(
            select(func.count()).select_from(OrganizationUser).where(OrganizationUser.userId == nouvel_utilisateur)
        )

    assert apres == avant
    assert appartenances == 0
