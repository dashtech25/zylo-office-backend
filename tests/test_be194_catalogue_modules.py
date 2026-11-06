"""BE-194 : catalogue des modules et de leurs versions (lecture, droits, contraintes).

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-donnees-api-contrats.md,
section BE-194) avant le code. Routes :
`GET /api/v1/modules/{module_code}` et `GET /api/v1/modules/{module_code}/versions/{version}`.

Décisions de test :
- la lecture du catalogue est publique (comme BE-043) : pas d'authentification, aucun droit ;
- `module_code` désigne `module.code` ; l'état d'une version est `module_version.publicationState`
  (nom existant, pas de colonne `status` ajoutée) ; `deprecated` est ajouté à cet enum par la
  migration BE-194 ;
- les fixtures posent l'état et la visibilité directement en base ;
- les droits d'écriture du catalogue passent par les allowlists d'environnement de
  `platform_rights.py` (`PLATFORM_CATALOG_MANAGE_USER_IDS`), posées avec `monkeypatch`.
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.identity.models import User
from app.modules_registry.models import Module, ModuleVersion
from app.rbac.role_assignments import AdminRoleAssignment

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REVISION_PRECEDENTE_BE194 = "b189c0de0189"
URL_MODULES = "/api/v1/modules"
URL_MODULE = "/api/v1/modules/{code}"
URL_VERSION = "/api/v1/modules/{code}/versions/{version}"
URL_ADMIN_MODULES = "/api/v1/admin/modules"
COMPATIBLE = {"zylo_office": ">=1.0.0"}


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    from app.core.database import engine

    await engine.dispose()
    yield


async def _inserer_module(
    code: str,
    *,
    publication: str = "published",
    visibilite: str = "visible",
    versions: tuple = (),
) -> uuid.UUID:
    """Insère un module et ses versions `(numéro, état, compatibilité)` directement en base."""
    async with AsyncSessionLocal() as db:
        module = Module(
            code=code,
            name=f"Module {code}",
            description=f"Description {code}",
            publicationState=publication,
            visibility=visibilite,
        )
        db.add(module)
        await db.flush()
        for numero, etat, compatibilite in versions:
            db.add(
                ModuleVersion(
                    moduleId=module.id,
                    version=numero,
                    digest="sha256:abc",
                    provenance="registre-test",
                    compatibility=compatibilite,
                    publicationState=etat,
                    publishedAt=datetime.now(timezone.utc) if etat in ("published", "deprecated") else None,
                )
            )
        await db.commit()
        return module.id


def _code_unique() -> str:
    return f"mod-be194-{uuid.uuid4().hex[:10]}"


async def _utilisateur_sans_grant(client: AsyncClient) -> dict:
    """Crée un compte sans organisation ni droit plateforme, et renvoie ses jetons."""
    email = f"test-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Sans grant"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return {"email": email, "accessToken": login.json()["accessToken"]}


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _accorder_autorite_plateforme(user_id: uuid.UUID) -> None:
    """Affectation active `operateur_plateforme` en portée `platform` : passe la garde des routes admin (BE-121).

    Sans elle, la route admin répond 403 `admin_scope_denied` avant tout contrôle de droit catalogue.
    """
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


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


# CA-1 : version dépréciée ou inconnue -> erreur explicite (422 ou 404 selon le cas).


async def test_ca1_version_inconnue_renvoie_404(client: AsyncClient):
    code = _code_unique()
    await _inserer_module(code, versions=(("1.0.0", "published", COMPATIBLE),))
    res = await client.get(URL_VERSION.format(code=code, version="9.9.9"))
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "MODULE_VERSION_NOT_FOUND"


async def test_ca1_version_deprecated_renvoie_422(client: AsyncClient):
    code = _code_unique()
    await _inserer_module(code, versions=(("1.0.0", "deprecated", COMPATIBLE),))
    res = await client.get(URL_VERSION.format(code=code, version="1.0.0"))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "MODULE_VERSION_DEPRECATED"


async def test_ca1_version_en_brouillon_est_introuvable(client: AsyncClient):
    """Une version non publiée n'est jamais exposée par le catalogue : elle est traitée comme inconnue."""
    code = _code_unique()
    await _inserer_module(code, versions=(("1.0.0", "draft", COMPATIBLE),))
    res = await client.get(URL_VERSION.format(code=code, version="1.0.0"))
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "MODULE_VERSION_NOT_FOUND"


async def test_ca1_module_inconnu_renvoie_404(client: AsyncClient):
    res = await client.get(URL_VERSION.format(code=_code_unique(), version="1.0.0"))
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "MODULE_NOT_FOUND"


async def test_module_masque_est_introuvable_sur_fiche_et_version(client: AsyncClient):
    code = _code_unique()
    await _inserer_module(code, visibilite="hidden", versions=(("1.0.0", "published", COMPATIBLE),))
    assert (await client.get(URL_MODULE.format(code=code))).status_code == 404
    assert (await client.get(URL_VERSION.format(code=code, version="1.0.0"))).status_code == 404


async def test_version_publiee_compatible_est_lisible(client: AsyncClient):
    code = _code_unique()
    await _inserer_module(code, versions=(("1.0.0", "published", COMPATIBLE),))
    res = await client.get(URL_VERSION.format(code=code, version="1.0.0"))
    assert res.status_code == 200
    corps = res.json()
    assert corps["version"] == "1.0.0"
    assert corps["compatibility"] == COMPATIBLE


# CA-2 : après un listing, une action sans grant reste refusée 403 (non-inférence de droit).


async def test_ca2_listage_du_catalogue_n_accorde_aucun_droit(client: AsyncClient, monkeypatch):
    """Après listage et lecture publics, le compte sans grant reste refusé sur une action d'écriture."""
    code = _code_unique()
    await _inserer_module(code, versions=(("1.0.0", "published", COMPATIBLE),))
    sans_grant = await _utilisateur_sans_grant(client)
    monkeypatch.setenv("PLATFORM_MODULE_WRITE_USER_IDS", "")
    monkeypatch.setenv("PLATFORM_CATALOG_MANAGE_USER_IDS", "")

    assert (await client.get(URL_MODULES, headers=_entetes(sans_grant))).status_code == 200
    assert (await client.get(URL_MODULE.format(code=code), headers=_entetes(sans_grant))).status_code == 200

    action = await client.post(
        URL_ADMIN_MODULES,
        json={"code": _code_unique(), "name": "Sans grant", "description": None},
        headers=_entetes(sans_grant),
    )
    assert action.status_code == 403


# CA-3 : écriture du catalogue sans `platform.catalog.manage` -> 403.


async def test_ca3_ecriture_du_catalogue_sans_droit_renvoie_403(client: AsyncClient, registered_user: dict, monkeypatch):
    await _accorder_autorite_plateforme(await _id_utilisateur(registered_user["email"]))
    monkeypatch.setenv("PLATFORM_MODULE_WRITE_USER_IDS", "")
    monkeypatch.setenv("PLATFORM_CATALOG_MANAGE_USER_IDS", "")
    res = await client.post(
        URL_ADMIN_MODULES,
        json={"code": _code_unique(), "name": "Refus", "description": None},
        headers=_entetes(registered_user),
    )
    assert res.status_code == 403


async def test_ca3_ecriture_du_catalogue_avec_platform_catalog_manage_reussit(
    client: AsyncClient, registered_user: dict, monkeypatch
):
    user_id = await _id_utilisateur(registered_user["email"])
    await _accorder_autorite_plateforme(user_id)
    monkeypatch.setenv("PLATFORM_MODULE_WRITE_USER_IDS", "")
    monkeypatch.setenv("PLATFORM_CATALOG_MANAGE_USER_IDS", str(user_id))
    res = await client.post(
        URL_ADMIN_MODULES,
        json={"code": _code_unique(), "name": "Autorisé", "description": None},
        headers=_entetes(registered_user),
    )
    assert res.status_code == 201
    assert res.json()["publicationState"] == "draft"


# CA-4 : seules les versions `published` et compatibles sont proposées à l'installation.


async def test_ca4_fiche_ne_propose_que_les_versions_publiees_et_compatibles(client: AsyncClient):
    code = _code_unique()
    await _inserer_module(
        code,
        versions=(
            ("1.0.0", "published", COMPATIBLE),
            ("1.1.0", "published", None),
            ("1.2.0", "draft", COMPATIBLE),
            ("0.9.0", "deprecated", COMPATIBLE),
        ),
    )
    res = await client.get(URL_MODULE.format(code=code))
    assert res.status_code == 200
    assert [v["version"] for v in res.json()["versions"]] == ["1.0.0"]


# CA-5 : deux modules de même code ne peuvent pas coexister (contrainte).


async def test_ca5_deux_modules_de_meme_code_refuses_par_la_base():
    code = _code_unique()
    await _inserer_module(code)
    with pytest.raises(IntegrityError):
        await _inserer_module(code)


# Transverse : la migration BE-194 ajoute `deprecated` à l'état de version et reste réversible.


def test_migration_be194_ajoute_deprecated_et_reste_reversible():
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def etats_version() -> list[str]:
        engine = create_async_engine(os.environ["DATABASE_URL"])
        try:
            async with engine.connect() as conn:
                return (
                    (
                        await conn.execute(
                            text("SELECT unnest(enum_range(NULL::module_version_publication_state))::text")
                        )
                    )
                    .scalars()
                    .all()
                )
        finally:
            await engine.dispose()

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    assert "deprecated" in asyncio.run(etats_version())
    command.downgrade(cfg, REVISION_PRECEDENTE_BE194)
    try:
        assert "deprecated" not in asyncio.run(etats_version())
    finally:
        command.upgrade(cfg, "head")
    assert "deprecated" in asyncio.run(etats_version())
