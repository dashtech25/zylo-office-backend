"""BE-044 : compatibilité, dépendances et plan de mise à jour des versions de module.

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-modules-droits.md,
section BE-044) avant le code.

Découpage :
- tests purs (sans base) sur `app.modules_registry.compatibilite` : CA-1, CA-2, CA-3, CA-5 ;
- tests d'API sur les deux routes `POST .../compatibility-evaluations` et `POST .../upgrade-plans` :
  CA-4 (403, aucune évaluation créée) et persistance des résultats ;
- test de migration : la révision BE-044 crée les deux tables et son downgrade les retire.

Décisions de test (voir la docstring de `app.modules_registry.compatibilite`) :
- le format de `prerequisites` n'est pas défini par la spec : on retient une liste de
  `{"code": str, "version": str | None}` ;
- `compatibility.manifestVersion` (entier) porte l'information de compatibilité ; absent = inconnu ;
- `compatibility.rollbackPossible` (booléen strict) porte le retour arrière ; absent = faux ;
- les droits plateforme passent par les allowlists d'environnement, posées avec `monkeypatch`.
"""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.identity.models import User
from app.modules_registry.compatibilite import (
    EntreeCatalogue,
    construire_plan_mise_a_jour,
    evaluer_compatibilite,
)
from app.modules_registry.models import ModuleCompatibilityEvaluation, ModuleUpgradePlan

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REVISION_PRECEDENTE_BE044 = "169de7fb56af"
URL_MODULES = "/api/v1/admin/modules"


# --------------------------------------------------------------------------------------------
# Tests purs (sans base de données)
# --------------------------------------------------------------------------------------------


def _entree(code, version, *, publiee=True, compatibility=None, prerequisites=None) -> EntreeCatalogue:
    return EntreeCatalogue(
        code=code,
        version=version,
        publiee=publiee,
        compatibility=compatibility,
        prerequisites=prerequisites,
    )


COMPATIBILITE_OK = {"manifestVersion": 1}


def test_ca1_cycle_de_dependances_donne_incompatible_dependency_cycle():
    """CA-1 : A dépend de B, B dépend de A : `incompatible`, motif `DEPENDENCY_CYCLE`."""
    a = _entree("mod_a", "1.0.0", compatibility=COMPATIBILITE_OK, prerequisites=[{"code": "mod_b", "version": None}])
    b = _entree("mod_b", "1.0.0", compatibility=COMPATIBILITE_OK, prerequisites=[{"code": "mod_a", "version": None}])

    resultat = evaluer_compatibilite(a, [a, b])

    assert resultat.result == "incompatible"
    assert "DEPENDENCY_CYCLE" in [motif["motif"] for motif in resultat.reasons]


def test_ca1_auto_dependance_est_un_cycle():
    """Un module qui se dépend lui-même forme un cycle de longueur 1."""
    a = _entree("mod_a", "1.0.0", compatibility=COMPATIBILITE_OK, prerequisites=[{"code": "mod_a", "version": None}])

    resultat = evaluer_compatibilite(a, [a])

    assert resultat.result == "incompatible"
    assert "DEPENDENCY_CYCLE" in [motif["motif"] for motif in resultat.reasons]


def test_ca2_dependance_absente_donne_incompatible_prerequisite_missing():
    """CA-2 : un prérequis absent du catalogue produit `incompatible`, motif `PREREQUISITE_MISSING`."""
    a = _entree(
        "mod_a",
        "1.0.0",
        compatibility=COMPATIBILITE_OK,
        prerequisites=[{"code": "mod_absent", "version": "2.0.0"}],
    )

    resultat = evaluer_compatibilite(a, [a])

    assert resultat.result == "incompatible"
    assert "PREREQUISITE_MISSING" in [motif["motif"] for motif in resultat.reasons]


def test_ca2_prerequis_present_mais_non_publie_est_absent():
    """Une dépendance qui n'est pas publiée ne compte pas comme disponible."""
    a = _entree("mod_a", "1.0.0", compatibility=COMPATIBILITE_OK, prerequisites=[{"code": "mod_b", "version": None}])
    b = _entree("mod_b", "1.0.0", publiee=False, compatibility=COMPATIBILITE_OK)

    resultat = evaluer_compatibilite(a, [a, b])

    assert resultat.result == "incompatible"
    assert "PREREQUISITE_MISSING" in [motif["motif"] for motif in resultat.reasons]


@pytest.mark.parametrize(
    "compatibility",
    [
        None,
        {},
        {"autreInformation": "x"},
    ],
)
def test_ca3_sans_information_de_compatibilite_donne_unknown_jamais_compatible(compatibility):
    """CA-3 : pas d'information de compatibilité -> `unknown`, jamais `compatible`."""
    a = _entree("mod_a", "1.0.0", compatibility=compatibility, prerequisites=None)

    resultat = evaluer_compatibilite(a, [a])

    assert resultat.result == "unknown"
    assert resultat.result != "compatible"


def test_compatible_seulement_si_manifeste_supporte_et_dependances_satisfaites():
    """Contrôle positif : le résultat `compatible` existe et exige les deux conditions."""
    a = _entree("mod_a", "1.0.0", compatibility=COMPATIBILITE_OK, prerequisites=[])

    assert evaluer_compatibilite(a, [a]).result == "compatible"


def test_manifeste_non_supporte_donne_incompatible():
    """Une version de manifeste hors `VERSIONS_MANIFESTE_SUPPORTEES` rend la version incompatible."""
    a = _entree("mod_a", "1.0.0", compatibility={"manifestVersion": 99}, prerequisites=[])

    resultat = evaluer_compatibilite(a, [a])

    assert resultat.result == "incompatible"
    assert "MANIFEST_VERSION_UNSUPPORTED" in [motif["motif"] for motif in resultat.reasons]


def test_manifeste_booleen_n_est_pas_une_version_supportee():
    """`True` vaut 1 en Python : un booléen ne doit pas passer pour la version de manifeste 1."""
    a = _entree("mod_a", "1.0.0", compatibility={"manifestVersion": True}, prerequisites=[])

    assert evaluer_compatibilite(a, [a]).result != "compatible"


def test_ca5_rollback_absent_donne_forward_only_et_aucune_etape_de_retour_arriere():
    """CA-5 : sans `rollbackPossible` déclaré, le plan est `forwardOnly`, sans retour arrière."""
    plan = construire_plan_mise_a_jour("1.0.0", "2.0.0", source_compatibility=None)

    assert plan["rollbackPossible"] is False
    assert plan["forwardOnly"] is True
    assert all("rollback" not in etape["action"] for etape in plan["steps"])


def test_ca5_retour_arriere_declare_ne_le_propose_pas_automatiquement():
    """CA-5 : même déclaré possible, aucune étape de retour arrière n'est ajoutée au plan."""
    plan = construire_plan_mise_a_jour("1.0.0", "2.0.0", source_compatibility={"rollbackPossible": True})

    assert plan["rollbackPossible"] is True
    assert plan["forwardOnly"] is False
    assert all("rollback" not in etape["action"] for etape in plan["steps"])


def test_ca5_rollbackpossible_non_booleen_strict_compte_comme_absent():
    """Une valeur non booléenne (ex. chaîne « true ») ne vaut pas retour arrière possible."""
    plan = construire_plan_mise_a_jour("1.0.0", "2.0.0", source_compatibility={"rollbackPossible": "true"})

    assert plan["rollbackPossible"] is False
    assert plan["forwardOnly"] is True


# --------------------------------------------------------------------------------------------
# Tests d'API
# --------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    from app.core.database import engine

    await engine.dispose()
    yield


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


def _entetes(registered_user: dict) -> dict:
    return {"Authorization": f"Bearer {registered_user['accessToken']}"}


async def _donner_droits(monkeypatch, registered_user: dict, *, publish: bool) -> None:
    user_id = await _id_utilisateur(registered_user["email"])
    monkeypatch.setenv("PLATFORM_MODULE_WRITE_USER_IDS", str(user_id))
    monkeypatch.setenv("PLATFORM_MODULE_PUBLISH_USER_IDS", str(user_id) if publish else "")


async def _creer_module(client: AsyncClient, registered_user: dict) -> dict:
    code = f"mod-be044-{uuid.uuid4().hex[:10]}"
    res = await client.post(
        URL_MODULES,
        json={"code": code, "name": "Module BE-044", "description": "Test de compatibilité"},
        headers=_entetes(registered_user),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _creer_version(client: AsyncClient, registered_user: dict, module_id: str, **champs) -> dict:
    corps = {"version": "1.0.0", "digest": "sha256:abc", "provenance": "depot/be044", "licence": "proprietary"}
    corps.update(champs)
    res = await client.post(
        f"{URL_MODULES}/{module_id}/versions", json=corps, headers=_entetes(registered_user)
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _compter(table: str) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


async def test_ca4_sans_droit_evaluation_refusee_et_rien_n_est_cree(
    client: AsyncClient, registered_user: dict, monkeypatch
):
    """CA-4 : un acteur sans `platform.module.publish` reçoit 403, aucune évaluation n'est créée."""
    await _donner_droits(monkeypatch, registered_user, publish=True)
    module = await _creer_module(client, registered_user)
    version = await _creer_version(client, registered_user, module["id"], compatibility=COMPATIBILITE_OK)

    monkeypatch.setenv("PLATFORM_MODULE_PUBLISH_USER_IDS", "")
    avant = await _compter("module_compatibility_evaluations")

    res = await client.post(
        f"{URL_MODULES}/{module['id']}/versions/{version['id']}/compatibility-evaluations",
        headers=_entetes(registered_user),
    )

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"
    assert await _compter("module_compatibility_evaluations") == avant


async def test_ca4_sans_droit_plan_refuse_et_rien_n_est_cree(
    client: AsyncClient, registered_user: dict, monkeypatch
):
    """CA-4 (plans) : sans droit, `upgrade-plans` renvoie 403 et n'écrit aucune ligne."""
    await _donner_droits(monkeypatch, registered_user, publish=True)
    module = await _creer_module(client, registered_user)
    await _creer_version(client, registered_user, module["id"], version="1.0.0")
    await _creer_version(client, registered_user, module["id"], version="2.0.0")

    monkeypatch.setenv("PLATFORM_MODULE_PUBLISH_USER_IDS", "")
    avant = await _compter("module_upgrade_plans")

    res = await client.post(
        f"{URL_MODULES}/{module['id']}/upgrade-plans",
        json={"fromVersion": "1.0.0", "toVersion": "2.0.0"},
        headers=_entetes(registered_user),
    )

    assert res.status_code == 403, res.text
    assert await _compter("module_upgrade_plans") == avant


async def test_evaluation_sans_information_renvoie_unknown_et_persiste_le_resultat(
    client: AsyncClient, registered_user: dict, monkeypatch
):
    """CA-3 via l'API : version sans compatibilité -> `unknown` ; l'évaluation est journalisée en base."""
    await _donner_droits(monkeypatch, registered_user, publish=True)
    module = await _creer_module(client, registered_user)
    version = await _creer_version(client, registered_user, module["id"])

    res = await client.post(
        f"{URL_MODULES}/{module['id']}/versions/{version['id']}/compatibility-evaluations",
        headers=_entetes(registered_user),
    )

    assert res.status_code == 201, res.text
    corps = res.json()
    assert corps["result"] == "unknown"
    assert corps["moduleVersionId"] == version["id"]

    async with AsyncSessionLocal() as db:
        ligne = (
            await db.execute(
                select(ModuleCompatibilityEvaluation).where(
                    ModuleCompatibilityEvaluation.moduleVersionId == uuid.UUID(version["id"])
                )
            )
        ).scalar_one()
        assert ligne.result == "unknown"
        assert ligne.evaluatedAt is not None


async def test_evaluation_compatible_via_api(client: AsyncClient, registered_user: dict, monkeypatch):
    """Contrôle positif via l'API : manifeste supporté, sans prérequis -> `compatible`."""
    await _donner_droits(monkeypatch, registered_user, publish=True)
    module = await _creer_module(client, registered_user)
    version = await _creer_version(
        client, registered_user, module["id"], compatibility=COMPATIBILITE_OK, prerequisites=[]
    )

    res = await client.post(
        f"{URL_MODULES}/{module['id']}/versions/{version['id']}/compatibility-evaluations",
        headers=_entetes(registered_user),
    )

    assert res.status_code == 201, res.text
    assert res.json()["result"] == "compatible"


async def test_plan_api_forward_only_sans_rollback(client: AsyncClient, registered_user: dict, monkeypatch):
    """CA-5 via l'API : le plan est renvoyé, marqué `forwardOnly`, sans étape de retour arrière, et persisté."""
    await _donner_droits(monkeypatch, registered_user, publish=True)
    module = await _creer_module(client, registered_user)
    await _creer_version(client, registered_user, module["id"], version="1.0.0")
    await _creer_version(client, registered_user, module["id"], version="2.0.0")

    res = await client.post(
        f"{URL_MODULES}/{module['id']}/upgrade-plans",
        json={"fromVersion": "1.0.0", "toVersion": "2.0.0"},
        headers=_entetes(registered_user),
    )

    assert res.status_code == 201, res.text
    plan = res.json()
    assert plan["fromVersion"] == "1.0.0"
    assert plan["toVersion"] == "2.0.0"
    assert plan["rollbackPossible"] is False
    assert plan["forwardOnly"] is True
    assert all("rollback" not in etape["action"] for etape in plan["steps"])

    async with AsyncSessionLocal() as db:
        ligne = (
            await db.execute(select(ModuleUpgradePlan).where(ModuleUpgradePlan.id == uuid.UUID(plan["id"])))
        ).scalar_one()
        assert ligne.forwardOnly is True


async def test_plan_version_inconnue_donne_404(client: AsyncClient, registered_user: dict, monkeypatch):
    """Une version source ou cible absente du module ne produit pas de plan."""
    await _donner_droits(monkeypatch, registered_user, publish=True)
    module = await _creer_module(client, registered_user)
    await _creer_version(client, registered_user, module["id"], version="1.0.0")
    avant = await _compter("module_upgrade_plans")

    res = await client.post(
        f"{URL_MODULES}/{module['id']}/upgrade-plans",
        json={"fromVersion": "1.0.0", "toVersion": "9.9.9"},
        headers=_entetes(registered_user),
    )

    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "MODULE_VERSION_NOT_FOUND"
    assert await _compter("module_upgrade_plans") == avant


# --------------------------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------------------------


def test_migration_be044_cree_les_tables_et_reste_reversible():
    """Les deux tables existent après `upgrade head` et disparaissent après le downgrade de BE-044."""
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def tables_presentes() -> set[str]:
        engine = create_async_engine(os.environ["DATABASE_URL"])
        try:
            async with engine.connect() as conn:
                return set(
                    (
                        await conn.execute(
                            text(
                                "SELECT table_name FROM information_schema.tables "
                                "WHERE table_schema='public' AND table_name IN "
                                "('module_compatibility_evaluations', 'module_upgrade_plans')"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
        finally:
            await engine.dispose()

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    assert asyncio.run(tables_presentes()) == {"module_compatibility_evaluations", "module_upgrade_plans"}
    command.downgrade(cfg, REVISION_PRECEDENTE_BE044)
    try:
        assert asyncio.run(tables_presentes()) == set()
    finally:
        command.upgrade(cfg, "head")
    assert asyncio.run(tables_presentes()) == {"module_compatibility_evaluations", "module_upgrade_plans"}
