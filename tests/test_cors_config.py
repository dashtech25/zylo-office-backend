from app.core.config import Settings

# Intention (T-003) : les origines CORS se configurent par variable d'environnement,
# pour que chaque worktree déclare son port frontend (docs/process/ports.md).
# `_env_file=None` ignore le .env du worktree : le test ne dépend pas du poste.


def test_defaut_couvre_checkout_principal_et_e2e():
    origines = Settings(_env_file=None).CORS_ORIGINS
    assert "http://localhost:3001" in origines
    assert "http://127.0.0.1:3001" in origines
    assert "http://localhost:3055" in origines


def test_variable_d_environnement_remplace_le_defaut(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3203"]')
    assert Settings(_env_file=None).CORS_ORIGINS == ["http://localhost:3203"]
