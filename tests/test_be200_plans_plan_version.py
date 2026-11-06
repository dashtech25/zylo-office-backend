"""BE-200 : plans et versions de plan (lecture, droits, immutabilité, montants).

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-donnees-api-contrats.md,
section BE-200) avant le code. Routes :
- `GET /api/v1/plans` et `GET /api/v1/plans/{plan_code}/versions/{version}` (lecture publique) ;
- `POST /api/v1/admin/plans/{plan_code}/versions` (droit `platform.catalog.manage`, QE-API-27).

Décisions de test (écarts consignés dans le rapport BE-200) :
- les tables existent déjà (BE-023) : `plan` et `planVersion`, camelCase conservé, aucune migration ;
- le montant est la colonne existante `amountMinor` (pas de `priceAmount`) ;
- l'état d'une version est `active` (courante) ou `archived` (remplacée), comme BE-023 ;
- le droit `platform.catalog.manage` passe par l'allowlist `PLATFORM_CATALOG_MANAGE_USER_IDS`
  (`platform_rights.py`, comme BE-194), posée avec `monkeypatch` ;
- aucun montant ne figure dans les réponses de lecture ; le montant n'existe que dans la requête
  d'écriture, sans valeur par défaut ni exemple (CA-5).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.billing.models import Plan, PlanVersion
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.identity.models import User
from app.modules_registry.models import Module
from app.rbac.role_assignments import AdminRoleAssignment

URL_PLANS = "/api/v1/plans"
URL_PLAN_VERSION = "/api/v1/plans/{code}/versions/{version}"
URL_ADMIN_VERSIONS = "/api/v1/admin/plans/{code}/versions"


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    await engine.dispose()
    yield


def _code_unique() -> str:
    return f"plan-be200-{uuid.uuid4().hex[:10]}"


async def _inserer_plan(code: str, *, montant: int = 1000, devise: str = "XAF") -> None:
    """Insère un module, un plan et sa version 1 (active) directement en base."""
    module_code = f"mod-{code}"
    async with AsyncSessionLocal() as db:
        db.add(Module(
            code=module_code, name=f"Module {code}", description="Module de test BE-200",
            publicationState="published", visibility="visible",
        ))
        await db.flush()
        plan = Plan(
            moduleCode=module_code, code=code, name=f"Plan {code}",
            priceCents=montant, currency=devise, periodDays=30,
        )
        db.add(plan)
        await db.flush()
        db.add(PlanVersion(
            planId=plan.id, version=1, amountMinor=montant, currency=devise, periodDays=30,
            entitlementCodes=[], status="active", effectiveAt=datetime.now(timezone.utc) - timedelta(days=1),
        ))
        await db.commit()


async def _versions(code: str) -> list[PlanVersion]:
    """Versions du plan `code`, ordonnées par numéro (lecture directe en base)."""
    async with AsyncSessionLocal() as db:
        plan = (await db.execute(select(Plan).where(Plan.code == code))).scalar_one()
        resultat = await db.execute(
            select(PlanVersion).where(PlanVersion.planId == plan.id).order_by(PlanVersion.version)
        )
        return list(resultat.scalars().all())


async def _utilisateur_admin(client: AsyncClient) -> dict:
    """Crée un compte avec une affectation `operateur_plateforme` (passe la garde des routes /admin)."""
    email = f"test-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Admin BE-200"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    async with AsyncSessionLocal() as db:
        user_id = (await db.execute(select(User.id).where(User.email == email))).scalar_one()
        db.add(AdminRoleAssignment(
            actorId=user_id, roleCode="operateur_plateforme", scope="platform", grantedBy=user_id,
            grantedAt=datetime.now(timezone.utc), expiresAt=None, revokedAt=None,
        ))
        await db.commit()
    return {"id": user_id, "accessToken": login.json()["accessToken"]}


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


def _autoriser_catalogue(monkeypatch, utilisateur: dict) -> None:
    """Accorde `platform.catalog.manage` à ce compte via l'allowlist d'environnement."""
    monkeypatch.setenv("PLATFORM_CATALOG_MANAGE_USER_IDS", str(utilisateur["id"]))


def _schema_resolu(openapi: dict, schema: dict) -> dict:
    """Suit une référence `$ref` du document OpenAPI jusqu'au schéma réel."""
    if "$ref" in schema:
        return openapi["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


# CA-1 : une version publiée n'est jamais modifiée (409).


async def test_ca1_modification_d_une_version_publiee_refusee_409():
    code = _code_unique()
    await _inserer_plan(code, montant=1000)
    async with AsyncSessionLocal() as db:
        plan = (await db.execute(select(Plan).where(Plan.code == code))).scalar_one()
        version = (await db.execute(select(PlanVersion).where(PlanVersion.planId == plan.id))).scalar_one()
        version.amountMinor = 999999
        with pytest.raises(AppError) as erreur:
            await db.commit()
        await db.rollback()
    assert erreur.value.status_code == 409
    assert erreur.value.code == "PLAN_VERSION_PUBLISHED"
    assert (await _versions(code))[0].amountMinor == 1000


# CA-2 : un changement de prix crée une nouvelle version et n'écrase pas l'ancienne.


async def test_ca2_changement_de_prix_cree_une_nouvelle_version(client: AsyncClient, monkeypatch):
    code = _code_unique()
    await _inserer_plan(code, montant=1000)
    admin = await _utilisateur_admin(client)
    _autoriser_catalogue(monkeypatch, admin)

    res = await client.post(
        URL_ADMIN_VERSIONS.format(code=code),
        json={"amountMinor": 2000, "currency": "XAF", "periodDays": 30, "entitlementCodes": []},
        headers=_entetes(admin),
    )
    assert res.status_code == 201, res.text
    assert res.json()["version"] == 2

    versions = await _versions(code)
    assert [v.version for v in versions] == [1, 2]
    assert versions[0].amountMinor == 1000
    assert versions[0].status == "archived"
    assert versions[1].amountMinor == 2000
    assert versions[1].status == "active"


# CA-3 : création sans `platform.catalog.manage` -> 403.


async def test_ca3_creation_sans_droit_catalogue_renvoie_403(client: AsyncClient, monkeypatch):
    code = _code_unique()
    await _inserer_plan(code, montant=1000)
    admin = await _utilisateur_admin(client)
    # Allowlist vide : le compte a l'autorité d'administration mais pas le droit catalogue.
    monkeypatch.setenv("PLATFORM_CATALOG_MANAGE_USER_IDS", "")

    res = await client.post(
        URL_ADMIN_VERSIONS.format(code=code),
        json={"amountMinor": 2000, "currency": "XAF", "periodDays": 30, "entitlementCodes": []},
        headers=_entetes(admin),
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"
    assert len(await _versions(code)) == 1


# CA-4 : un montant sans devise est refusé 422.


async def test_ca4_montant_sans_devise_refuse_422(client: AsyncClient, monkeypatch):
    code = _code_unique()
    await _inserer_plan(code, montant=1000)
    admin = await _utilisateur_admin(client)
    _autoriser_catalogue(monkeypatch, admin)

    res = await client.post(
        URL_ADMIN_VERSIONS.format(code=code),
        json={"amountMinor": 2000, "periodDays": 30, "entitlementCodes": []},
        headers=_entetes(admin),
    )
    assert res.status_code == 422
    assert len(await _versions(code)) == 1


# CA-5 : aucun montant dans les contrats d'interface tant que la valeur n'est pas validée (QE-API-24).


async def test_ca5_aucun_montant_dans_les_reponses_et_aucune_valeur_par_defaut(client: AsyncClient):
    res = await client.get("/openapi.json")
    assert res.status_code == 200
    openapi = res.json()
    chemins = [
        openapi["paths"][URL_PLANS]["get"],
        openapi["paths"][URL_PLAN_VERSION]["get"],
    ]
    for operation in chemins:
        reponse = operation["responses"]["200"]["content"]["application/json"]["schema"]
        texte = str(reponse)
        assert "amountMinor" not in texte and "priceAmount" not in texte, operation

    corps = openapi["paths"][URL_ADMIN_VERSIONS]["post"]["requestBody"]["content"]["application/json"]["schema"]
    proprietes = _schema_resolu(openapi, corps)["properties"]
    assert "amountMinor" in proprietes
    assert "default" not in proprietes["amountMinor"]
    assert "example" not in proprietes["amountMinor"]


# Lecture publique des plans et des versions (sans montant).


async def test_lecture_liste_des_plans_sans_montant(client: AsyncClient):
    code = _code_unique()
    await _inserer_plan(code, montant=1000)
    res = await client.get(URL_PLANS)
    assert res.status_code == 200
    trouve = [p for p in res.json() if p["code"] == code]
    assert len(trouve) == 1
    assert trouve[0]["version"] == 1
    assert trouve[0]["status"] == "active"
    assert "amountMinor" not in trouve[0]


async def test_lecture_version_inconnue_renvoie_404(client: AsyncClient):
    code = _code_unique()
    await _inserer_plan(code)
    res = await client.get(URL_PLAN_VERSION.format(code=code, version=99))
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "PLAN_VERSION_NOT_FOUND"


async def test_lecture_version_existante(client: AsyncClient):
    code = _code_unique()
    await _inserer_plan(code)
    res = await client.get(URL_PLAN_VERSION.format(code=code, version=1))
    assert res.status_code == 200
    assert res.json()["version"] == 1
    assert res.json()["status"] == "active"
