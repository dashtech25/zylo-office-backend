"""BE-195 : manifeste de module et publication par code de module (registre).

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-donnees-api-contrats.md,
section BE-195) avant le code. Route : `POST /api/v1/admin/modules/by-code/{module_code}/versions`.

Décisions de test :
- le chemin `/api/v1/admin/modules/{module_code}/versions` est déjà occupé par la route BE-042 qui
  prend un `module_id` (UUID) ; la route BE-195 vit sous `/by-code/` pour ne pas la masquer (QE-API-01) ;
- la garde d'administration (BE-121) est passée par une affectation `operateur_plateforme`, comme en BE-194 ;
- le droit d'écriture est `platform.catalog.manage`, attribué par `PLATFORM_CATALOG_MANAGE_USER_IDS` ;
- une permission est connue si elle figure dans le registre des permissions (table `permission`) ;
- une dépendance est connue si son code figure dans le catalogue (table `module`) ;
- chaque rejet de manifeste (422) écrit une entrée d'audit `refused`, committée avant la réponse.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.identity.models import User
from app.modules_registry.models import Module, ModuleVersion
from app.rbac.models import UserPermissionGrant
from app.rbac.role_assignments import AdminRoleAssignment
from app.rbac.service import get_or_create_permission

URL_PUBLICATION = "/api/v1/admin/modules/by-code/{code}/versions"
ACTION_REJET_AUDIT = "modules.manifest.rejected"

CHAMPS_REQUIS = (
    "id",
    "code",
    "release",
    "contractVersions",
    "dependencies",
    "configSchema",
    "permissions",
    "routes",
    "migrations",
    "compatibility",
)


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    from app.core.database import engine

    await engine.dispose()
    yield


def _code_unique() -> str:
    return f"mod-be195-{uuid.uuid4().hex[:10]}"


def _permission_unique() -> str:
    return f"be195x{uuid.uuid4().hex[:10]}.station.read"


def _manifeste(code: str, *, dependances: list | None = None, permissions: list | None = None) -> dict:
    """Manifeste complet et valide pour `code`."""
    return {
        "id": f"{code}-manifest",
        "code": code,
        "release": "1.0.0",
        "contractVersions": {"api": ["v1"], "events": ["v1"]},
        "dependencies": dependances or [],
        "configSchema": {"type": "object"},
        "permissions": permissions or [],
        "routes": ["/api/v1/stations"],
        "migrations": ["0001_init"],
        "compatibility": {"zylo_office": ">=1.0.0"},
    }


async def _inserer_module(code: str) -> uuid.UUID:
    """Insère un module au catalogue directement en base."""
    async with AsyncSessionLocal() as db:
        module = Module(code=code, name=f"Module {code}", publicationState="published", visibility="visible")
        db.add(module)
        await db.commit()
        return module.id


async def _inserer_permission(code: str) -> None:
    """Déclare une permission connue du registre des permissions."""
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(db, code, "be195", "Permission de test BE-195.")
        await db.commit()


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _accorder_autorite_plateforme(user_id: uuid.UUID) -> None:
    """Affectation active `operateur_plateforme` en portée `platform` : passe la garde des routes admin (BE-121)."""
    async with AsyncSessionLocal() as db:
        db.add(
            AdminRoleAssignment(
                actorId=user_id,
                roleCode="operateur_plateforme",
                scope="platform",
                grantedBy=user_id,
                grantedAt=datetime.now(timezone.utc),
                expiresAt=None,
                revokedAt=None,
            )
        )
        await db.commit()


async def _compter_grants() -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(func.count()).select_from(UserPermissionGrant))).scalar_one()


async def _compter_rejets_audit() -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == ACTION_REJET_AUDIT, AuditEvent.result == "refused")
            )
        ).scalar_one()


async def _version(code: str, numero: str) -> ModuleVersion | None:
    async with AsyncSessionLocal() as db:
        module_id = (await db.execute(select(Module.id).where(Module.code == code))).scalar_one()
        return (
            await db.execute(
                select(ModuleVersion).where(ModuleVersion.moduleId == module_id, ModuleVersion.version == numero)
            )
        ).scalar_one_or_none()


@pytest.fixture
async def acteur_plateforme(client: AsyncClient, registered_user: dict, monkeypatch) -> dict:
    """Compte administrateur de plateforme autorisé à écrire le catalogue (`platform.catalog.manage`)."""
    user_id = await _id_utilisateur(registered_user["email"])
    await _accorder_autorite_plateforme(user_id)
    monkeypatch.setenv("PLATFORM_MODULE_WRITE_USER_IDS", "")
    monkeypatch.setenv("PLATFORM_CATALOG_MANAGE_USER_IDS", str(user_id))
    return registered_user


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


# CA-1 : un manifeste incomplet (champ requis absent) est refusé 422.


@pytest.mark.parametrize("champ", CHAMPS_REQUIS)
async def test_ca1_manifeste_incomplet_renvoie_422(client: AsyncClient, acteur_plateforme: dict, champ: str):
    code = _code_unique()
    await _inserer_module(code)
    manifeste = _manifeste(code)
    del manifeste[champ]
    res = await client.post(
        URL_PUBLICATION.format(code=code), json=manifeste, headers=_entetes(acteur_plateforme)
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "MANIFEST_INCOMPLETE"
    assert champ in res.json()["error"]["field_errors"]


async def test_ca1_manifeste_complet_est_accepte_en_brouillon(client: AsyncClient, acteur_plateforme: dict):
    code = _code_unique()
    await _inserer_module(code)
    res = await client.post(
        URL_PUBLICATION.format(code=code), json=_manifeste(code), headers=_entetes(acteur_plateforme)
    )
    assert res.status_code == 201
    corps = res.json()
    assert corps["version"] == "1.0.0"
    assert corps["publicationState"] == "draft"
    ligne = await _version(code, "1.0.0")
    assert ligne is not None
    assert ligne.manifest["release"] == "1.0.0"
    assert ligne.manifest["contractVersions"] == {"api": ["v1"], "events": ["v1"]}


async def test_ca1_code_du_manifeste_different_de_l_url_est_refuse(client: AsyncClient, acteur_plateforme: dict):
    code = _code_unique()
    await _inserer_module(code)
    res = await client.post(
        URL_PUBLICATION.format(code=code),
        json=_manifeste(_code_unique()),
        headers=_entetes(acteur_plateforme),
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "MANIFEST_CODE_MISMATCH"


async def test_module_inconnu_renvoie_404(client: AsyncClient, acteur_plateforme: dict):
    code = _code_unique()
    res = await client.post(
        URL_PUBLICATION.format(code=code), json=_manifeste(code), headers=_entetes(acteur_plateforme)
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "MODULE_NOT_FOUND"


async def test_version_deja_publiee_au_catalogue_renvoie_409(client: AsyncClient, acteur_plateforme: dict):
    code = _code_unique()
    await _inserer_module(code)
    entetes = _entetes(acteur_plateforme)
    assert (await client.post(URL_PUBLICATION.format(code=code), json=_manifeste(code), headers=entetes)).status_code == 201
    res = await client.post(URL_PUBLICATION.format(code=code), json=_manifeste(code), headers=entetes)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "MODULE_VERSION_EXISTS"


# CA-2 : une dépendance absente du catalogue est refusée 422.


async def test_ca2_dependance_absente_du_catalogue_renvoie_422(client: AsyncClient, acteur_plateforme: dict):
    code = _code_unique()
    await _inserer_module(code)
    res = await client.post(
        URL_PUBLICATION.format(code=code),
        json=_manifeste(code, dependances=[_code_unique()]),
        headers=_entetes(acteur_plateforme),
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "MANIFEST_DEPENDENCY_UNKNOWN"


async def test_ca2_dependance_presente_au_catalogue_est_acceptee(client: AsyncClient, acteur_plateforme: dict):
    code = _code_unique()
    dependance = _code_unique()
    await _inserer_module(code)
    await _inserer_module(dependance)
    res = await client.post(
        URL_PUBLICATION.format(code=code),
        json=_manifeste(code, dependances=[dependance]),
        headers=_entetes(acteur_plateforme),
    )
    assert res.status_code == 201


# CA-3 : une permission inconnue est refusée 422.


async def test_ca3_permission_inconnue_renvoie_422(client: AsyncClient, acteur_plateforme: dict):
    code = _code_unique()
    await _inserer_module(code)
    res = await client.post(
        URL_PUBLICATION.format(code=code),
        json=_manifeste(code, permissions=[_permission_unique()]),
        headers=_entetes(acteur_plateforme),
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "MANIFEST_PERMISSION_UNKNOWN"


async def test_ca3_permission_connue_est_acceptee(client: AsyncClient, acteur_plateforme: dict):
    code = _code_unique()
    permission = _permission_unique()
    await _inserer_module(code)
    await _inserer_permission(permission)
    res = await client.post(
        URL_PUBLICATION.format(code=code),
        json=_manifeste(code, permissions=[permission]),
        headers=_entetes(acteur_plateforme),
    )
    assert res.status_code == 201


# CA-4 : la publication d'un manifeste ne crée aucun grant.


async def test_ca4_publication_ne_cree_aucun_grant(client: AsyncClient, acteur_plateforme: dict):
    code = _code_unique()
    permission = _permission_unique()
    await _inserer_module(code)
    await _inserer_permission(permission)
    avant = await _compter_grants()
    res = await client.post(
        URL_PUBLICATION.format(code=code),
        json=_manifeste(code, permissions=[permission]),
        headers=_entetes(acteur_plateforme),
    )
    assert res.status_code == 201
    assert await _compter_grants() == avant


# CA-5 : une publication sans `platform.catalog.manage` renvoie 403.


async def test_ca5_publication_sans_droit_renvoie_403(client: AsyncClient, registered_user: dict, monkeypatch):
    code = _code_unique()
    await _inserer_module(code)
    await _accorder_autorite_plateforme(await _id_utilisateur(registered_user["email"]))
    monkeypatch.setenv("PLATFORM_MODULE_WRITE_USER_IDS", "")
    monkeypatch.setenv("PLATFORM_CATALOG_MANAGE_USER_IDS", "")
    res = await client.post(
        URL_PUBLICATION.format(code=code), json=_manifeste(code), headers=_entetes(registered_user)
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"
    assert await _version(code, "1.0.0") is None


# CA-6 : chaque rejet de manifeste écrit une entrée d'audit.


@pytest.mark.parametrize(
    "construire",
    [
        pytest.param(lambda code: {k: v for k, v in _manifeste(code).items() if k != "release"}, id="incomplet"),
        pytest.param(lambda code: _manifeste(code, dependances=[_code_unique()]), id="dependance"),
        pytest.param(lambda code: _manifeste(code, permissions=[_permission_unique()]), id="permission"),
    ],
)
async def test_ca6_chaque_rejet_ecrit_une_entree_d_audit(client: AsyncClient, acteur_plateforme: dict, construire):
    code = _code_unique()
    await _inserer_module(code)
    avant = await _compter_rejets_audit()
    res = await client.post(
        URL_PUBLICATION.format(code=code), json=construire(code), headers=_entetes(acteur_plateforme)
    )
    assert res.status_code == 422
    assert await _compter_rejets_audit() == avant + 1
