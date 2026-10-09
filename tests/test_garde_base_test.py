"""Garde de base de test (T-005).

Intention : pytest refuse de démarrer si TEST_DATABASE_URL est absente ou ne
désigne pas une base de test (zylo_t<NNN>[a-z]?_test), sinon il viderait une
base de développement. Chaque cas est joué dans un sous-processus pytest, car
la garde s'exécute à l'import de tests/conftest.py. Le sous-processus ne fait
que collecter ce fichier (--collect-only) : aucune base n'est touchée.
"""

import os
import subprocess
import sys

import pytest

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FICHIER = os.path.join("tests", "test_garde_base_test.py")
VARIABLE_OPT_IN = "ZYLO_TEST_TOLERER_ZYLO_OFFICE_TEST"


def _collecte(url: str | None, opt_in: str | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("TEST_DATABASE_URL", VARIABLE_OPT_IN)}
    if url is not None:
        env["TEST_DATABASE_URL"] = url
    if opt_in is not None:
        env[VARIABLE_OPT_IN] = opt_in
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", FICHIER],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _sortie(res: subprocess.CompletedProcess) -> str:
    return res.stdout + res.stderr


def test_variable_absente_refusee_avec_commande_env_tache():
    res = _collecte(None)
    assert res.returncode != 0
    assert "TEST_DATABASE_URL est absente" in _sortie(res)
    assert "scripts/dev/env_tache.sh creer" in _sortie(res)


def test_variable_vide_refusee():
    res = _collecte("")
    assert res.returncode != 0
    assert "TEST_DATABASE_URL est absente" in _sortie(res)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://zylo_office:x@localhost:5432/zylo_office",
        "postgresql+asyncpg://remy@/zylo?host=/var/run/postgresql",
        "postgresql+asyncpg://remy@/zylo_dev?host=/var/run/postgresql",
        "postgresql+asyncpg://remy@/zylo_liquid?host=/var/run/postgresql",
        "postgresql+asyncpg://remy@/zylo_recette?host=/var/run/postgresql",
        # zylo_office interdite même sur un autre port ou hôte
        "postgresql+asyncpg://zylo_office:x@localhost:5433/zylo_office",
        "postgresql+asyncpg://zylo_office:x@autre-hote:6543/zylo_office",
        # motifs proches mais hors motif
        "postgresql+asyncpg://remy@/zylo_t05_test?host=/var/run/postgresql",
        "postgresql+asyncpg://remy@/zylo_t005_test_copie?host=/var/run/postgresql",
        "postgresql+asyncpg://remy@/zylo_t005A_test?host=/var/run/postgresql",
        "postgresql+asyncpg://remy@/zylo_t005_test?host=/var/run/postgresql&dbname=zylo",
        "postgresql+asyncpg://remy@/?host=/var/run/postgresql",
    ],
)
def test_nom_de_base_interdit_refuse(url: str):
    res = _collecte(url)
    assert res.returncode != 0, _sortie(res)
    assert "n'est pas une base de test" in _sortie(res)


def test_zylo_office_test_refusee_sans_opt_in():
    res = _collecte("postgresql+asyncpg://zylo_office:x@localhost:5432/zylo_office_test")
    assert res.returncode != 0
    assert "n'est pas une base de test" in _sortie(res)


def test_zylo_office_test_tolree_avec_opt_in_explicite():
    res = _collecte(
        "postgresql+asyncpg://zylo_office:x@localhost:5432/zylo_office_test",
        opt_in="1",
    )
    assert res.returncode == 0, _sortie(res)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://remy@/zylo_t005_test?host=/var/run/postgresql",
        "postgresql+asyncpg://remy@/zylo_t005a_test?host=/var/run/postgresql",
        "postgresql+asyncpg://zylo_office:x@localhost:5433/zylo_t041_test",
    ],
)
def test_nom_de_base_valide_accepte(url: str):
    res = _collecte(url)
    assert res.returncode == 0, _sortie(res)
