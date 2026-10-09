"""Refus au démarrage hors développement (T-002).

Intention : aucun secret de repli ne doit servir hors `ENVIRONMENT=development`,
variable absente comprise. Les tests construisent `Settings` sans lire de
fichier `.env` (`_env_file=None`) pour ne dépendre que de l'environnement
qu'ils déclarent.
"""

import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.core.config import (
    FALLBACK_DB_PASSWORD,
    FALLBACK_JWT_SECRET,
    ConfigurationSecretError,
    Settings,
)

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Secrets propres, longs, sans rapport avec les valeurs de repli.
SECRET_FORT = "fort-0123456789abcdef0123456789abcdef"
SECRET_FORT_STORAGE = "stockage-fedcba9876543210fedcba9876543210"
DB_FORTE = "postgresql+asyncpg://zylo_test:mdp-propre-7H3kQ9@localhost:5432/zylo_test"
DB_REPLI = f"postgresql+asyncpg://zylo_office:{FALLBACK_DB_PASSWORD}@localhost:5432/zylo_office"
SECRET_COURT = "trop-court-123"
SECRET_CHIFFREMENT = "chiffrement-" + "0123456789abcdef" * 2

VARIABLES = ("ENVIRONMENT", "JWT_SECRET", "STORAGE_SIGNED_URL_SECRET", "DATABASE_URL", "APP_FIELD_ENCRYPTION_KEY")


def _environnement(monkeypatch, **valeurs):
    """Repart d'un environnement sans variables de l'application, puis pose `valeurs`."""
    for nom in VARIABLES:
        monkeypatch.delenv(nom, raising=False)
    for nom, valeur in valeurs.items():
        monkeypatch.setenv(nom, valeur)


def _settings():
    return Settings(_env_file=None)


def test_environnement_par_defaut_est_production():
    assert Settings.model_fields["ENVIRONMENT"].default == "production"


def test_variable_absente_avec_secret_de_repli_refuse(monkeypatch):
    _environnement(monkeypatch, DATABASE_URL=DB_FORTE, STORAGE_SIGNED_URL_SECRET=SECRET_FORT_STORAGE)
    with pytest.raises(ConfigurationSecretError) as info:
        _settings()
    assert "JWT_SECRET" in str(info.value)


@pytest.mark.parametrize("environnement", ["production", "staging", ""])
@pytest.mark.parametrize("cle", ["", SECRET_COURT])
def test_cle_de_chiffrement_obligatoire_hors_development_et_test(monkeypatch, environnement, cle):
    _environnement(
        monkeypatch,
        ENVIRONMENT=environnement,
        JWT_SECRET=SECRET_FORT,
        STORAGE_SIGNED_URL_SECRET=SECRET_FORT_STORAGE,
        DATABASE_URL=DB_FORTE,
        APP_FIELD_ENCRYPTION_KEY=cle,
    )
    with pytest.raises(ConfigurationSecretError) as info:
        _settings()
    assert "APP_FIELD_ENCRYPTION_KEY" in str(info.value)


def test_cle_de_chiffrement_non_exigee_en_development(monkeypatch):
    _environnement(monkeypatch, ENVIRONMENT="development")
    assert _settings().APP_FIELD_ENCRYPTION_KEY == ""


def test_cle_de_chiffrement_non_exigee_en_test(monkeypatch):
    # En test, les autres secrets doivent être valides (règles strictes) ; seule la clé est dispensée.
    _environnement(
        monkeypatch,
        ENVIRONMENT="test",
        JWT_SECRET=SECRET_FORT,
        STORAGE_SIGNED_URL_SECRET=SECRET_FORT_STORAGE,
        DATABASE_URL=DB_FORTE,
    )
    assert _settings().APP_FIELD_ENCRYPTION_KEY == ""


@pytest.mark.parametrize(
    "variables, attendu",
    [
        ({"JWT_SECRET": FALLBACK_JWT_SECRET}, "JWT_SECRET"),
        ({"STORAGE_SIGNED_URL_SECRET": FALLBACK_JWT_SECRET}, "STORAGE_SIGNED_URL_SECRET"),
        ({"DATABASE_URL": DB_REPLI}, "DATABASE_URL"),
        ({"JWT_SECRET": SECRET_COURT}, "JWT_SECRET"),
    ],
)
@pytest.mark.parametrize("environnement", ["production", "test", "staging", "Development", ""])
def test_hors_development_secret_de_repli_ou_court_refuse(monkeypatch, environnement, variables, attendu):
    base = {
        "ENVIRONMENT": environnement,
        "JWT_SECRET": SECRET_FORT,
        "STORAGE_SIGNED_URL_SECRET": SECRET_FORT_STORAGE,
        "DATABASE_URL": DB_FORTE,
        "APP_FIELD_ENCRYPTION_KEY": SECRET_CHIFFREMENT,
    }
    base.update(variables)
    _environnement(monkeypatch, **base)
    with pytest.raises(ConfigurationSecretError) as info:
        _settings()
    assert attendu in str(info.value)


def test_message_de_refus_ne_contient_aucune_valeur_de_secret(monkeypatch):
    _environnement(
        monkeypatch,
        ENVIRONMENT="production",
        JWT_SECRET=SECRET_COURT,
        STORAGE_SIGNED_URL_SECRET=SECRET_FORT_STORAGE,
        DATABASE_URL=DB_REPLI,
    )
    with pytest.raises(ConfigurationSecretError) as info:
        _settings()
    message = str(info.value)
    assert "JWT_SECRET" in message and "DATABASE_URL" in message
    for valeur in (SECRET_COURT, FALLBACK_DB_PASSWORD, SECRET_FORT_STORAGE):
        assert valeur not in message


def test_refus_n_est_pas_une_validation_error(monkeypatch):
    # Une ValidationError de pydantic joint la valeur d'entrée (donc les secrets).
    _environnement(monkeypatch, ENVIRONMENT="production", JWT_SECRET=FALLBACK_JWT_SECRET,
                   STORAGE_SIGNED_URL_SECRET=SECRET_FORT_STORAGE, DATABASE_URL=DB_FORTE)
    with pytest.raises(ConfigurationSecretError) as info:
        _settings()
    assert not isinstance(info.value, ValidationError)


@pytest.mark.parametrize("environnement", ["production", "test"])
def test_secrets_valides_hors_development_acceptes(monkeypatch, environnement):
    _environnement(
        monkeypatch,
        ENVIRONMENT=environnement,
        JWT_SECRET=SECRET_FORT,
        STORAGE_SIGNED_URL_SECRET=SECRET_FORT_STORAGE,
        DATABASE_URL=DB_FORTE,
        APP_FIELD_ENCRYPTION_KEY=SECRET_CHIFFREMENT,
    )
    settings = _settings()
    assert settings.ENVIRONMENT == environnement
    assert settings.JWT_SECRET == SECRET_FORT


def test_development_accepte_les_replis(monkeypatch):
    _environnement(monkeypatch, ENVIRONMENT="development")
    settings = _settings()
    assert settings.JWT_SECRET == FALLBACK_JWT_SECRET
    assert settings.STORAGE_SIGNED_URL_SECRET == FALLBACK_JWT_SECRET
    assert settings.DATABASE_URL == DB_REPLI


def _importe_app_main(environnement_extra: dict[str, str]) -> subprocess.CompletedProcess:
    """Importe app.main dans un sous-processus isolé du .env du dépôt."""
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": BACKEND_ROOT}
    env.update(environnement_extra)
    # cwd hors dépôt : aucun .env ne doit influencer le démarrage testé.
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=os.path.dirname(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_import_app_main_refuse_sans_environnement_et_avec_repli():
    resultat = _importe_app_main({})
    assert resultat.returncode != 0
    assert "ConfigurationSecretError" in resultat.stderr
    assert "JWT_SECRET" in resultat.stderr


def test_import_app_main_accepte_development_avec_replis():
    resultat = _importe_app_main({"ENVIRONMENT": "development"})
    assert resultat.returncode == 0, resultat.stderr[-800:]


def test_import_app_main_accepte_production_avec_secrets_valides():
    resultat = _importe_app_main({
        "ENVIRONMENT": "production",
        "JWT_SECRET": SECRET_FORT,
        "STORAGE_SIGNED_URL_SECRET": SECRET_FORT_STORAGE,
        "DATABASE_URL": DB_FORTE,
        "APP_FIELD_ENCRYPTION_KEY": SECRET_CHIFFREMENT,
    })
    assert resultat.returncode == 0, resultat.stderr[-800:]
