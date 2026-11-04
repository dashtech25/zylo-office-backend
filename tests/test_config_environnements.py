"""Configuration par environnement et base de test jetable (BE-221).

Intention : chaque critère d'acceptation de BE-221 est couvert par au moins un
test qui peut échouer.

- CA-1 : hors development, l'application refuse de démarrer si un secret
  obligatoire manque (échec fermé). Vérifié par un sous-processus Python qui
  importe la configuration : un arrêt en erreur est attendu.
- CA-2 : les tests n'utilisent que `zylo_t<NNN>_test`. Un nom voisin, une base
  de développement, ou `zylo_office_test` (même avec l'ancien opt-in) est refusé.
  La garde s'exécute à l'import de tests/conftest.py : chaque cas est joué dans
  un sous-processus `pytest --collect-only`, qui ne touche aucune base.
- CA-3 : aucune valeur de secret n'apparaît dans la sortie de démarrage
  (succès comme refus). Vérifié par capture de stdout et stderr.
- CA-4 : deux environnements (development et test, ou test et production) ne
  partagent aucun identifiant : secrets de signature, clé de chiffrement, URL
  de base de données.

Les tests construisent `Settings` avec `_env_file=None` ; les sous-processus
tournent dans un répertoire temporaire sans `.env`, pour ne dépendre que des
variables qu'ils déclarent.
"""

import os
import secrets
import subprocess
import sys

import pytest

from app.core.config import (
    FALLBACK_DB_PASSWORD,
    FALLBACK_JWT_SECRET,
    ConfigurationSecretError,
    Settings,
)

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FICHIER_GARDE = os.path.join("tests", "test_config_environnements.py")
VARIABLE_OPT_IN = "ZYLO_TEST_TOLERER_ZYLO_OFFICE_TEST"

# Variables lues par Settings : un sous-processus part d'un environnement vide
# de ces noms, puis pose uniquement ce que le test déclare.
VARIABLES_APPLICATION = (
    "ENVIRONMENT", "JWT_SECRET", "STORAGE_SIGNED_URL_SECRET", "DATABASE_URL",
    "APP_FIELD_ENCRYPTION_KEY", "AUTH_PUBLIC_REGISTRATION_ENABLED", "AUTH_COOKIE_SECURE",
    "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "TEST_DATABASE_URL", VARIABLE_OPT_IN,
)

SECRET_FORT = "fort-" + "0123456789abcdef" * 2
SECRET_FORT_STOCKAGE = "stockage-" + "fedcba9876543210" * 2
CLE_CHIFFREMENT = "chiffrement-" + "a1b2c3d4e5f60718" * 2
SECRET_COURT = "trop-court-123"
MOT_DE_PASSE_BASE = "mdp-" + secrets.token_hex(12)
SECRET_JWT_MARQUEUR = "marqueur-jwt-" + secrets.token_hex(12)


def _env_propre(**valeurs: str | None) -> dict[str, str]:
    """Copie de l'environnement sans variables de l'application, puis `valeurs` posées.

    Une valeur None retire la variable. Les variables de PATH et de Python sont
    conservées pour que le sous-processus puisse importer `app`.
    """
    env = {k: v for k, v in os.environ.items() if k not in VARIABLES_APPLICATION}
    env["PYTHONPATH"] = BACKEND_ROOT
    for nom, valeur in valeurs.items():
        if valeur is not None:
            env[nom] = valeur
    return env


def _importe_configuration(tmp_path, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Importe `app.core.config` dans un processus neuf, depuis un répertoire sans `.env`."""
    return subprocess.run(
        [sys.executable, "-c", "import app.core.config"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _settings(**environnement: str) -> Settings:
    """Settings construit sans fichier `.env`, à partir des seules valeurs données."""
    return Settings(_env_file=None, **environnement)


# ---------------------------------------------------------------- CA-1


@pytest.mark.parametrize(
    "variables",
    [
        # Secret de signature absent : le repli public serait utilisé.
        {"ENVIRONMENT": "production", "STORAGE_SIGNED_URL_SECRET": SECRET_FORT_STOCKAGE,
         "APP_FIELD_ENCRYPTION_KEY": CLE_CHIFFREMENT, "DATABASE_URL": "postgresql+asyncpg://u:mdp-propre-7H3kQ9@h:5432/zylo_prod"},
        # Clé de chiffrement absente hors development et test.
        {"ENVIRONMENT": "production", "JWT_SECRET": SECRET_FORT,
         "STORAGE_SIGNED_URL_SECRET": SECRET_FORT_STOCKAGE,
         "DATABASE_URL": "postgresql+asyncpg://u:mdp-propre-7H3kQ9@h:5432/zylo_prod"},
        # Environnement absent : le défaut production s'applique.
        {"JWT_SECRET": SECRET_FORT, "STORAGE_SIGNED_URL_SECRET": SECRET_FORT_STOCKAGE,
         "APP_FIELD_ENCRYPTION_KEY": CLE_CHIFFREMENT},
        # Environnement mal écrit : aucune correspondance exacte avec development.
        {"ENVIRONMENT": "Development", "JWT_SECRET": SECRET_FORT,
         "STORAGE_SIGNED_URL_SECRET": SECRET_FORT_STOCKAGE, "APP_FIELD_ENCRYPTION_KEY": CLE_CHIFFREMENT},
    ],
)
def test_demarrage_refuse_quand_un_secret_obligatoire_manque(tmp_path, variables):
    env = _env_propre(**{k: None for k in VARIABLES_APPLICATION}, **variables)
    if "ENVIRONMENT" not in variables:
        env.pop("ENVIRONMENT", None)
    res = _importe_configuration(tmp_path, env)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "ConfigurationSecretError" in res.stderr or "Démarrage refusé" in res.stderr


def test_configuration_absente_hors_development_leve_erreur_fermee(monkeypatch):
    for nom in VARIABLES_APPLICATION:
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ConfigurationSecretError) as info:
        _settings()
    assert "JWT_SECRET" in str(info.value)


def test_development_demarre_avec_les_replis(tmp_path):
    env = _env_propre(ENVIRONMENT="development")
    res = _importe_configuration(tmp_path, env)
    assert res.returncode == 0, res.stderr


def test_secret_de_repli_refuse_meme_si_la_variable_est_posee(monkeypatch):
    for nom in VARIABLES_APPLICATION:
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", FALLBACK_JWT_SECRET)
    monkeypatch.setenv("STORAGE_SIGNED_URL_SECRET", SECRET_FORT_STOCKAGE)
    monkeypatch.setenv("APP_FIELD_ENCRYPTION_KEY", CLE_CHIFFREMENT)
    monkeypatch.setenv("DATABASE_URL", f"postgresql+asyncpg://u:{SECRET_FORT}@h:5432/zylo_prod")
    with pytest.raises(ConfigurationSecretError):
        _settings()


# ---------------------------------------------------------------- CA-2


def _collecte_garde(url: str | None, opt_in: str | None = None) -> subprocess.CompletedProcess:
    """Collecte ce fichier avec TEST_DATABASE_URL donnée : la garde seule s'exécute."""
    env = {k: v for k, v in os.environ.items() if k not in ("TEST_DATABASE_URL", VARIABLE_OPT_IN)}
    if url is not None:
        env["TEST_DATABASE_URL"] = url
    if opt_in is not None:
        env[VARIABLE_OPT_IN] = opt_in
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", FICHIER_GARDE],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize(
    "nom_base",
    [
        "zylo_t221_test",
        "zylo_t005_test",
    ],
)
def test_base_zylo_t_nnn_test_acceptee(nom_base):
    res = _collecte_garde(f"postgresql+asyncpg://remy@/{nom_base}?host=/var/run/postgresql")
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.parametrize(
    "nom_base",
    [
        "zylo_t221a_test",       # suffixe lettre : hors du motif zylo_t<NNN>_test
        "zylo_t21_test",         # NNN à deux chiffres
        "zylo_t0221_test",       # NNN à quatre chiffres
        "zylo_t221_test_copie",  # suffixe après _test
        "zylo_office_test",      # ancien repli : jamais admise (CA-2)
        "zylo_office",
        "zylo",
        "zylo_dev",
        "zylo_liquid",
        "zylo_recette",
    ],
)
def test_base_hors_motif_refusee(nom_base):
    res = _collecte_garde(f"postgresql+asyncpg://remy@/{nom_base}?host=/var/run/postgresql")
    assert res.returncode != 0, res.stdout + res.stderr
    assert "n'est pas une base de test" in res.stdout + res.stderr


def test_zylo_office_test_refusee_meme_avec_l_ancien_opt_in():
    res = _collecte_garde(
        "postgresql+asyncpg://remy@/zylo_office_test?host=/var/run/postgresql",
        opt_in="1",
    )
    assert res.returncode != 0, res.stdout + res.stderr
    assert "n'est pas une base de test" in res.stdout + res.stderr


def test_base_de_developpement_jamais_base_de_test():
    """La base de test d'exécution ne désigne jamais une base de développement (CA-2)."""
    url = os.environ.get("TEST_DATABASE_URL", "")
    nom = url.rsplit("/", 1)[-1].split("?")[0]
    assert nom.startswith("zylo_t") and nom.endswith("_test"), nom
    assert nom not in {"zylo", "zylo_office", "zylo_dev", "zylo_liquid", "zylo_recette", "zylo_office_test"}


# ---------------------------------------------------------------- CA-3


def test_secrets_absents_de_la_sortie_au_demarrage_refuse(tmp_path):
    """Un refus affiche les noms des variables, jamais leurs valeurs (CA-3)."""
    env = _env_propre(
        ENVIRONMENT="production",
        JWT_SECRET=SECRET_JWT_MARQUEUR,  # trop court : refus attendu
        STORAGE_SIGNED_URL_SECRET=SECRET_FORT_STOCKAGE,
        APP_FIELD_ENCRYPTION_KEY=CLE_CHIFFREMENT,
        DATABASE_URL=f"postgresql+asyncpg://u:{MOT_DE_PASSE_BASE}@h:5432/zylo_prod",
    )
    res = _importe_configuration(tmp_path, env)
    sortie = res.stdout + res.stderr
    assert res.returncode != 0
    assert "JWT_SECRET" in sortie
    for valeur in (SECRET_JWT_MARQUEUR, MOT_DE_PASSE_BASE, CLE_CHIFFREMENT, SECRET_FORT_STOCKAGE):
        assert valeur not in sortie


def test_secrets_absents_de_la_sortie_au_demarrage_accepte(tmp_path):
    env = _env_propre(
        ENVIRONMENT="production",
        JWT_SECRET=SECRET_FORT,
        STORAGE_SIGNED_URL_SECRET=SECRET_FORT_STOCKAGE,
        APP_FIELD_ENCRYPTION_KEY=CLE_CHIFFREMENT,
        DATABASE_URL=f"postgresql+asyncpg://u:{MOT_DE_PASSE_BASE}@h:5432/zylo_prod",
    )
    res = _importe_configuration(tmp_path, env)
    sortie = res.stdout + res.stderr
    assert res.returncode == 0, sortie
    for valeur in (SECRET_FORT, SECRET_FORT_STOCKAGE, CLE_CHIFFREMENT, MOT_DE_PASSE_BASE):
        assert valeur not in sortie


# ---------------------------------------------------------------- CA-4


def test_developpement_et_test_ne_partagent_aucun_identifiant(monkeypatch):
    """Les valeurs de développement (replis) et celles de test sont disjointes (CA-4)."""
    for nom in VARIABLES_APPLICATION:
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    dev = _settings()
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("JWT_SECRET", "test-only-" + "x" * 40)
    monkeypatch.setenv("STORAGE_SIGNED_URL_SECRET", "test-only-storage-" + "y" * 40)
    monkeypatch.setenv("APP_FIELD_ENCRYPTION_KEY", "test-only-cle-" + "z" * 40)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://remy@/zylo_t221_test")
    test = _settings()
    champs = ("JWT_SECRET", "STORAGE_SIGNED_URL_SECRET", "APP_FIELD_ENCRYPTION_KEY", "DATABASE_URL")
    for champ in champs:
        assert getattr(dev, champ) != getattr(test, champ), champ
    assert dev.DATABASE_URL != test.DATABASE_URL
    assert FALLBACK_DB_PASSWORD not in test.DATABASE_URL


def test_production_et_test_ne_partagent_aucun_identifiant(monkeypatch):
    for nom in VARIABLES_APPLICATION:
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", SECRET_FORT)
    monkeypatch.setenv("STORAGE_SIGNED_URL_SECRET", SECRET_FORT_STOCKAGE)
    monkeypatch.setenv("APP_FIELD_ENCRYPTION_KEY", CLE_CHIFFREMENT)
    monkeypatch.setenv("DATABASE_URL", f"postgresql+asyncpg://zylo_prod:{MOT_DE_PASSE_BASE}@h:5432/zylo_prod")
    prod = _settings()
    test = Settings(_env_file=None, ENVIRONMENT="test", JWT_SECRET="test-only-" + "x" * 40,
                    STORAGE_SIGNED_URL_SECRET="test-only-storage-" + "y" * 40,
                    APP_FIELD_ENCRYPTION_KEY="test-only-cle-" + "z" * 40,
                    DATABASE_URL="postgresql+asyncpg://remy@/zylo_t221_test")
    for champ in ("JWT_SECRET", "STORAGE_SIGNED_URL_SECRET", "APP_FIELD_ENCRYPTION_KEY", "DATABASE_URL"):
        assert getattr(prod, champ) != getattr(test, champ), champ
