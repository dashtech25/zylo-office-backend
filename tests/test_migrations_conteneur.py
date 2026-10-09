"""T-028 / T-051 : migrations hors démarrage, commandes explicites, conteneur durci.

Intention : prouver par des tests que
- le démarrage de l'application ne migre, ne seed et ne rejoue aucun backfill ;
- `migrer` refuse une migration destructive sans confirmation ni sauvegarde ;
- les liste de révisions destructives reste complète (balayage AST de upgrade()) ;
- seeds et backfills sont idempotents et ne touchent pas le rôle manager ;
- l'image n'exécute pas de migration et tourne sous un utilisateur non root.

Ces tests utilisent la base de test (TEST_DATABASE_URL, conftest). Aucune base
de développement n'est lue ni modifiée. Le contrôle Docker réel (build, run) est
fait hors pytest : voir docs/operations/deploiement.md.
"""

import ast
import os
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app import cli
from app.core import migrations
from app.core.database import AsyncSessionLocal
from app.core.migrations import (
    REVISIONS_DESTRUCTIVES,
    MigrationError,
    garde_destructive,
    revisions_attendues,
    revisions_en_attente,
    verifie_revision_a_jour,
)
from app.modules_registry.models import Module
from app.rbac.models import Permission, Role, RolePermission

RACINE = Path(__file__).resolve().parent.parent
REVISION_DESTRUCTIVE = "7ffb9473d45e"


def _lit(chemin: str) -> str:
    return (RACINE / chemin).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Conteneur (T-051) : contrôle statique du Dockerfile et du contexte de build
# ---------------------------------------------------------------------------


def _instructions_dockerfile() -> list[tuple[str, str]]:
    """Instructions du Dockerfile (mot-clé, reste de la ligne), prolongements `\\` recollés."""
    lignes = _lit("Dockerfile").replace("\\\n", " ").splitlines()
    instructions = []
    for ligne in lignes:
        propre = ligne.strip()
        if not propre or propre.startswith("#"):
            continue
        mot, _, reste = propre.partition(" ")
        instructions.append((mot.upper(), reste.strip()))
    return instructions


def test_cmd_du_conteneur_ne_lance_aucune_migration():
    cmd = [reste for mot, reste in _instructions_dockerfile() if mot in {"CMD", "ENTRYPOINT"}]
    assert cmd, "le Dockerfile doit définir un CMD"
    for valeur in cmd:
        assert "alembic" not in valeur, f"le démarrage du conteneur ne doit jamais migrer : {valeur}"
        assert "app.cli" not in valeur, f"le démarrage du conteneur ne doit jamais lancer de commande d'exploitation : {valeur}"
        assert "uvicorn" in valeur


def test_conteneur_tourne_sous_utilisateur_non_root():
    instructions = _instructions_dockerfile()
    users = [reste for mot, reste in instructions if mot == "USER"]
    assert users, "le Dockerfile doit déclarer USER"
    utilisateur = users[-1].split(":")[0]
    assert utilisateur not in {"root", "0"}, f"USER doit être non root : {users[-1]}"
    # L'étape finale (après le dernier FROM) est celle qui s'exécute : USER doit y figurer.
    derniere_etape = max(i for i, (mot, _) in enumerate(instructions) if mot == "FROM")
    assert any(mot == "USER" for mot, _ in instructions[derniere_etape:]), "USER doit être dans l'étape finale"


def test_conteneur_declare_un_healthcheck_et_port_explicite():
    mots = [mot for mot, _ in _instructions_dockerfile()]
    assert "HEALTHCHECK" in mots
    assert "EXPOSE" in mots


def test_dockerignore_exclut_secrets_sauvegardes_et_depot():
    motifs = {ligne.strip() for ligne in _lit(".dockerignore").splitlines() if ligne.strip() and not ligne.startswith("#")}
    obligatoires = {".env", ".env.*", "backups", "var", ".git", "**/*.sql", "**/*.sql.gz", "**/*.dump", "**/*.pgdump", "**/*.pem", "**/*.key"}
    manquants = sorted(obligatoires - motifs)
    assert not manquants, f".dockerignore incomplet, motifs manquants : {manquants}"


def test_dockerignore_ne_retire_aucun_fichier_necessaire_au_demarrage():
    """Le démarrage a besoin de app/, alembic/, alembic.ini : aucun motif ne doit les couvrir."""
    motifs = [ligne.strip() for ligne in _lit(".dockerignore").splitlines() if ligne.strip() and not ligne.startswith("#")]
    for necessaire in ("app/main.py", "app/cli.py", "app/core/migrations.py", "alembic/env.py", "alembic.ini", "requirements.txt"):
        for motif in motifs:
            assert not Path(necessaire).match(motif), f"le motif {motif!r} exclurait {necessaire}"


# ---------------------------------------------------------------------------
# Migrations : révisions destructives et garde (T-028)
# ---------------------------------------------------------------------------


def _revisions_destructives_par_ast() -> set[str]:
    """Révisions dont upgrade() supprime une table ou une colonne, ou fait TRUNCATE/DELETE."""
    trouvees: set[str] = set()
    for fichier in sorted((RACINE / "alembic" / "versions").glob("*.py")):
        source = fichier.read_text(encoding="utf-8")
        arbre = ast.parse(source)
        revision = None
        for noeud in arbre.body:
            if isinstance(noeud, ast.AnnAssign) and getattr(noeud.target, "id", "") == "revision":
                revision = ast.literal_eval(noeud.value)
            if isinstance(noeud, ast.Assign) and any(getattr(t, "id", "") == "revision" for t in noeud.targets):
                revision = ast.literal_eval(noeud.value)
        for noeud in arbre.body:
            if isinstance(noeud, ast.FunctionDef) and noeud.name == "upgrade":
                corps = ast.get_source_segment(source, noeud) or ""
                if re.search(r"op\.(drop_table|drop_column)\b|TRUNCATE|DELETE\s+FROM", corps, re.IGNORECASE):
                    trouvees.add(revision)
    return trouvees


def test_liste_des_revisions_destructives_est_complete():
    """Toute migration qui détruit des données dans upgrade() doit figurer dans la garde."""
    assert _revisions_destructives_par_ast() == set(REVISIONS_DESTRUCTIVES)


def test_revisions_en_attente_depuis_base_vide_et_depuis_la_tete():
    tete = revisions_attendues()
    assert len(tete) == 1, "une seule tête Alembic attendue"
    assert REVISION_DESTRUCTIVE in revisions_en_attente(set())
    assert revisions_en_attente(tete) == []


def test_revisions_en_attente_depuis_0240_contiennent_la_destructive():
    en_attente = revisions_en_attente({"0240c128e5de"})
    assert REVISION_DESTRUCTIVE in en_attente
    assert "0240c128e5de" not in en_attente


def test_revision_inconnue_du_code_refuse_sans_rien_appliquer():
    with pytest.raises(MigrationError, match="inconnue du dépôt"):
        revisions_en_attente({"ffffffffffff"})


def test_garde_destructive_refuse_sans_confirmation():
    with pytest.raises(MigrationError, match="refusées sans confirmation"):
        garde_destructive([REVISION_DESTRUCTIVE], base_vide=False, confirmation=False, sauvegarde=None)


def test_garde_destructive_refuse_sans_sauvegarde_existante(tmp_path: Path):
    with pytest.raises(MigrationError, match="obligatoire"):
        garde_destructive([REVISION_DESTRUCTIVE], base_vide=False, confirmation=True, sauvegarde=None)
    with pytest.raises(MigrationError, match="introuvable ou vide"):
        garde_destructive([REVISION_DESTRUCTIVE], base_vide=False, confirmation=True, sauvegarde=str(tmp_path / "absent.sql.gz"))
    vide = tmp_path / "vide.sql.gz"
    vide.write_bytes(b"")
    with pytest.raises(MigrationError, match="introuvable ou vide"):
        garde_destructive([REVISION_DESTRUCTIVE], base_vide=False, confirmation=True, sauvegarde=str(vide))


def test_garde_destructive_accepte_confirmation_et_sauvegarde(tmp_path: Path):
    dump = tmp_path / "sauvegarde.sql.gz"
    dump.write_bytes(b"contenu-non-vide")
    accepte = garde_destructive([REVISION_DESTRUCTIVE], base_vide=False, confirmation=True, sauvegarde=str(dump))
    assert accepte == [REVISION_DESTRUCTIVE]


def test_garde_destructive_ignore_base_vide_et_migrations_non_destructives():
    assert garde_destructive([REVISION_DESTRUCTIVE], base_vide=True, confirmation=False, sauvegarde=None) == [REVISION_DESTRUCTIVE]
    assert garde_destructive(["f1a2b3c4d5e7"], base_vide=False, confirmation=False, sauvegarde=None) == []


async def test_demarrage_refuse_un_schema_non_a_jour(monkeypatch):
    async def base_en_retard():
        return {"0240c128e5de"}, False

    monkeypatch.setattr(migrations, "lit_etat_base", base_en_retard)
    with pytest.raises(MigrationError, match="python -m app.cli migrer"):
        await verifie_revision_a_jour()


async def test_demarrage_accepte_un_schema_a_jour(client):
    # La base de test est migrée à la tête par conftest : le contrôle doit passer
    # sans rien écrire.
    await verifie_revision_a_jour()


def test_on_startup_ne_seed_ni_ne_backfill_ni_ne_migre():
    arbre = ast.parse(_lit("app/main.py"))
    corps = next(
        noeud for noeud in ast.walk(arbre) if isinstance(noeud, ast.AsyncFunctionDef) and noeud.name == "on_startup"
    )
    appels = {
        noeud.func.id if isinstance(noeud.func, ast.Name) else getattr(noeud.func, "attr", "")
        for noeud in ast.walk(corps)
        if isinstance(noeud, ast.Call)
    }
    interdits = {n for n in appels if n.startswith(("seed_", "backfill_", "execute_", "upgrade", "command"))}
    assert not interdits, f"on_startup appelle encore des commandes de données : {sorted(interdits)}"
    assert "verifie_revision_a_jour" in appels


# ---------------------------------------------------------------------------
# Seeds et backfills explicites (base de test)
# ---------------------------------------------------------------------------


async def _compte_lignes() -> tuple[int, int]:
    async with AsyncSessionLocal() as db:
        permissions = await db.scalar(select(func.count()).select_from(Permission))
        modules = await db.scalar(select(func.count()).select_from(Module))
    return permissions, modules


async def test_seeds_sont_idempotents(client):
    await cli.execute_seeds()
    avant = await _compte_lignes()
    await cli.execute_seeds()
    assert await _compte_lignes() == avant


async def test_backfill_repare_owner_sans_toucher_le_manager(zylo_liquid_organization: dict):
    organisation = uuid.UUID(zylo_liquid_organization["id"])

    async with AsyncSessionLocal() as db:
        owner = await db.scalar(select(Role).where(Role.organizationId == organisation, Role.code == "owner"))
        retiree = await db.scalar(select(RolePermission).where(RolePermission.roleId == owner.id).limit(1))
        await db.delete(retiree)
        manager = Role(organizationId=organisation, code="manager", name="Manager")
        db.add(manager)
        await db.commit()
        manager_id = manager.id

    async def permissions_du_manager() -> int:
        async with AsyncSessionLocal() as db:
            return await db.scalar(select(func.count()).select_from(RolePermission).where(RolePermission.roleId == manager_id))

    assert await permissions_du_manager() == 0

    premier = await cli.execute_backfills()
    assert premier["permissionsOwnerSocleAjoutees"] + premier["permissionsOwnerModulesAjoutees"] >= 1
    assert await permissions_du_manager() == 0, "le backfill ne doit jamais élargir le rôle manager"

    second = await cli.execute_backfills()
    assert second == {"permissionsOwnerSocleAjoutees": 0, "permissionsOwnerModulesAjoutees": 0}
    assert await permissions_du_manager() == 0


# ---------------------------------------------------------------------------
# Interface en ligne de commande
# ---------------------------------------------------------------------------


def test_cli_migrer_en_dry_run_et_a_jour_n_ecrit_rien(capsys):
    assert cli.main(["migrer", "--dry-run"]) == 0
    assert cli.main(["migrer"]) == 0
    assert "rien a appliquer" in capsys.readouterr().out


def test_cli_refuse_une_migration_destructive_sans_confirmation(monkeypatch, capsys):
    async def base_avant_la_destructive():
        return {"0240c128e5de"}, False

    appels = []
    monkeypatch.setattr(cli, "lit_etat_base", base_avant_la_destructive)
    monkeypatch.setattr(cli.command, "upgrade", lambda *a, **k: appels.append(a))

    assert cli.main(["migrer"]) == cli.CODE_REFUS
    assert appels == [], "aucune migration ne doit être lancée sans confirmation"
    assert "refusées sans confirmation" in capsys.readouterr().err


def test_cli_commande_inconnue_est_refusee():
    with pytest.raises(SystemExit):
        cli.main(["demarrer"])


def test_env_de_test_pointe_une_base_dediee():
    url = os.environ.get("DATABASE_URL", "")
    assert re.search(r"zylo_t\d{3}[a-z]?_test", url), "les tests de migrations ne tournent que sur une base zylo_t<NNN>_test"
