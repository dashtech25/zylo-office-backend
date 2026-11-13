"""Configuration des sessions par cookies et de CORS avec identifiants (T-037a).

Mêmes principes que tests/test_config_secrets.py : `Settings` est construit sans
`.env` (`_env_file=None`) pour ne dépendre que de l'environnement déclaré ici.
"""

import pytest
from pydantic import ValidationError

from app.core.config import ConfigurationSecretError, Settings

SECRET_FORT = "fort-0123456789abcdef0123456789abcdef"
SECRET_FORT_STORAGE = "stockage-fedcba9876543210fedcba9876543210"
DB_FORTE = "postgresql+asyncpg://zylo_test:mdp-propre-7H3kQ9@localhost:5432/zylo_test"
CHIFFREMENT = "chiffrement-" + "0123456789abcdef" * 2

VARIABLES = (
    "ENVIRONMENT",
    "JWT_SECRET",
    "STORAGE_SIGNED_URL_SECRET",
    "DATABASE_URL",
    "APP_FIELD_ENCRYPTION_KEY",
    "AUTH_COOKIE_SECURE",
    "AUTH_COOKIE_SAMESITE",
    "CORS_ORIGINS",
)


def _environnement(monkeypatch, **valeurs):
    for nom in VARIABLES:
        monkeypatch.delenv(nom, raising=False)
    for nom, valeur in valeurs.items():
        monkeypatch.setenv(nom, valeur)


def _settings() -> Settings:
    return Settings(_env_file=None)


def _production(**extra) -> dict:
    return {
        "ENVIRONMENT": "production",
        "JWT_SECRET": SECRET_FORT,
        "STORAGE_SIGNED_URL_SECRET": SECRET_FORT_STORAGE,
        "DATABASE_URL": DB_FORTE,
        "APP_FIELD_ENCRYPTION_KEY": CHIFFREMENT,
        **extra,
    }


def test_secure_est_vrai_hors_development_par_defaut(monkeypatch):
    _environnement(monkeypatch, **_production())
    assert _settings().cookies_secure is True


def test_secure_est_faux_en_development_par_defaut(monkeypatch):
    _environnement(monkeypatch, ENVIRONMENT="development")
    assert _settings().cookies_secure is False


def test_secure_desactive_refuse_hors_development(monkeypatch):
    _environnement(monkeypatch, **_production(AUTH_COOKIE_SECURE="false"))
    with pytest.raises(ConfigurationSecretError) as info:
        _settings()
    assert "AUTH_COOKIE_SECURE" in str(info.value)


def test_secure_desactive_admis_en_development(monkeypatch):
    _environnement(monkeypatch, ENVIRONMENT="development", AUTH_COOKIE_SECURE="false")
    assert _settings().cookies_secure is False


@pytest.mark.parametrize("valeur", ["none", "Lax-ish", ""])
def test_samesite_limite_a_lax_ou_strict(monkeypatch, valeur):
    # SameSite=None n'est pas admis : il exigerait Secure et ouvre les envois inter-sites.
    _environnement(monkeypatch, ENVIRONMENT="development", AUTH_COOKIE_SAMESITE=valeur)
    with pytest.raises(ValidationError):
        _settings()


def test_fin_de_transition_doit_etre_une_date_avec_fuseau(monkeypatch):
    _environnement(monkeypatch, ENVIRONMENT="development", AUTH_HEADER_ACCEPTED_UNTIL="2026-11-30T00:00:00")
    with pytest.raises(ConfigurationSecretError) as info:
        _settings()
    assert "AUTH_HEADER_ACCEPTED_UNTIL" in str(info.value)


@pytest.mark.parametrize("environnement", ["development", "production"])
def test_cors_joker_refuse_avec_identifiants(monkeypatch, environnement):
    _environnement(monkeypatch, **{"ENVIRONMENT": environnement, "CORS_ORIGINS": '["*"]',
                                   **({} if environnement == "development" else _production())})
    with pytest.raises(ConfigurationSecretError) as info:
        _settings()
    assert "CORS_ORIGINS" in str(info.value)
