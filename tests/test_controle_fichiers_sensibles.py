"""Contrôle automatisé : aucun dump de base ni fichier d'environnement n'est suivi par git (T-001).

Intention : le script scripts/dev/controle_fichiers_sensibles.sh est la source unique
des règles. Ces tests échouent si le dépôt suit un dump ou un .env (mode --index), et
vérifient que le script détecte bien les cas interdits sur un dépôt jetable (tmp_path),
sans toucher au dépôt réel.
"""

import os
import shutil
import subprocess

import pytest

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(BACKEND_ROOT, "scripts", "dev", "controle_fichiers_sensibles.sh")


def _lance(cwd: str, mode: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", SCRIPT, mode],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _depot_git_jetable(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git absent : contrôle non exécutable")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return str(tmp_path)


def test_depot_reel_ne_suit_aucun_dump_ni_env():
    if not os.path.isdir(os.path.join(BACKEND_ROOT, ".git")) and not os.path.isfile(
        os.path.join(BACKEND_ROOT, ".git")
    ):
        pytest.skip("pas de dépôt git (archive sans historique)")
    resultat = _lance(BACKEND_ROOT, "--index")
    assert resultat.returncode == 0, resultat.stderr


def test_index_detecte_dump_et_env_mais_pas_env_example(tmp_path):
    depot = _depot_git_jetable(tmp_path)
    for nom in ["sauvegarde.sql.gz", "export.dump", ".env", ".env.migration", "app/.env.local", ".env.example", "code.py"]:
        chemin = os.path.join(depot, nom)
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w") as f:
            f.write("factice\n")
    subprocess.run(["git", "-C", depot, "add", "-f", "."], check=True)

    resultat = _lance(depot, "--index")
    assert resultat.returncode == 1
    for interdit in ["sauvegarde.sql.gz", "export.dump", ".env", ".env.migration", "app/.env.local"]:
        assert interdit in resultat.stderr
    assert ".env.example" not in resultat.stderr
    assert "code.py" not in resultat.stderr


def test_staged_bloque_un_dump_ajoute_et_laisse_passer_le_reste(tmp_path):
    depot = _depot_git_jetable(tmp_path)
    with open(os.path.join(depot, "readme.txt"), "w") as f:
        f.write("ok\n")
    subprocess.run(["git", "-C", depot, "add", "readme.txt"], check=True)
    assert _lance(depot, "--staged").returncode == 0

    with open(os.path.join(depot, "base.sql"), "w") as f:
        f.write("factice\n")
    subprocess.run(["git", "-C", depot, "add", "-f", "base.sql"], check=True)
    resultat = _lance(depot, "--staged")
    assert resultat.returncode == 1
    assert "base.sql" in resultat.stderr


def test_mode_inconnu_refuse():
    resultat = subprocess.run(["bash", SCRIPT, "--inconnu"], capture_output=True, text=True)
    assert resultat.returncode == 2
