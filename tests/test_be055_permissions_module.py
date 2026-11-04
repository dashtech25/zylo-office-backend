"""BE-055 : permissions déclarées par module (table `module_permissions`).

Tests écrits d'après la définition (implementation-backend/tasks-modules-droits.md, section BE-055)
avant le code. Critères :
- CA-1 : deux versions d'un même module déclarent des permissions distinctes sans collision
  (unicité du code par version, pas globale) ; un doublon dans une même version est refusé (409) ;
- CA-2 : un code de permission non déclaré par la version installée ne peut pas être accordé (422) ;
- CA-3 : un membre sans `organization.module.read` reçoit 403 ;
- CA-4 : organisation d'un autre tenant : 404, sans donnée.

Décisions de test (voir QE-BE055-01 et QE-BE055-02 dans le compte rendu de la tâche) :
- « version installée » = dernière version `published` du module (BE-043 `module_installations`
  n'existe pas encore) ;
- le droit `organization.module.read` est accordé au propriétaire à la création de l'organisation ;
- la garde CA-2 est testée au niveau service ; son branchement sur les routes de grant n'est pas
  fait par cette tâche.

Route testée : GET /api/v1/organizations/{organization_id}/modules/{module_id}/permissions.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.identity.models import OrganizationUser
from app.modules_registry.declarations import (
    DeclarationPermission,
    declarer_permissions,
    exiger_permissions_declarees,
    lister_permissions_installees,
)
from app.modules_registry.models import ModulePermission, ModuleVersion
from app.modules_registry.service import get_or_create_module

MOT_DE_PASSE = "TestPassword123!"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _code_module() -> str:
    return f"be055_{uuid.uuid4().hex[:10]}"


async def _module_avec_version(code: str, publiee: bool = True) -> tuple[uuid.UUID, uuid.UUID]:
    """Crée un module du catalogue et une version (publiée par défaut) ; retourne (module, version)."""
    async with AsyncSessionLocal() as db:
        module = await get_or_create_module(db, code, f"Module {code}", "Module de test BE-055")
        maintenant = datetime.now(timezone.utc)
        version = ModuleVersion(
            moduleId=module.id,
            version="1.0.0",
            publicationState="published" if publiee else "draft",
            publishedAt=maintenant if publiee else None,
        )
        db.add(version)
        await db.commit()
        return module.id, version.id


async def _declarer(version_id: uuid.UUID, *codes: str) -> None:
    async with AsyncSessionLocal() as db:
        await declarer_permissions(
            db,
            version_id,
            [DeclarationPermission(code=c, description=f"Permission {c}", scope="organization") for c in codes],
        )
        await db.commit()


async def _membre_sans_droit(client: AsyncClient, organization_id: uuid.UUID) -> str:
    """Crée un utilisateur rattaché à l'organisation, sans rôle ; retourne son jeton d'accès."""
    email = f"be055-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    membre = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Membre BE-055"}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=uuid.UUID(membre.json()["id"])))
        await db.commit()
    return login.json()["accessToken"]


def _url(organization_id: str, module_id: uuid.UUID) -> str:
    return f"/api/v1/organizations/{organization_id}/modules/{module_id}/permissions"


async def test_ca1_deux_versions_declarent_des_permissions_sans_collision():
    """CA-1 : chaque version porte ses propres permissions ; le même code peut reparaître dans une
    autre version (unicité par version), mais jamais deux fois dans la même version (409)."""
    code = _code_module()
    _, version_1 = await _module_avec_version(code)
    _, version_2 = await _module_avec_version(code, publiee=False)
    await _declarer(version_1, f"{code}.station.read", f"{code}.station.manage")
    await _declarer(version_2, f"{code}.station.read", f"{code}.station.close")

    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(select(ModulePermission).where(ModulePermission.moduleVersionId.in_([version_1, version_2])))
        ).scalars().all()
        codes_par_version = {
            vid: sorted(l.code for l in lignes if l.moduleVersionId == vid) for vid in (version_1, version_2)
        }
    assert codes_par_version[version_1] == sorted([f"{code}.station.read", f"{code}.station.manage"])
    assert codes_par_version[version_2] == sorted([f"{code}.station.read", f"{code}.station.close"])

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await declarer_permissions(
                db, version_1, [DeclarationPermission(code=f"{code}.station.read", description="doublon", scope="organization")]
            )
        assert erreur.value.status_code == 409
        await db.rollback()


async def test_ca1_contrainte_base_refuse_un_doublon_dans_une_version():
    """CA-1 (niveau base) : la contrainte (moduleVersionId, code) refuse une seconde ligne identique."""
    code = _code_module()
    _, version_id = await _module_avec_version(code)
    await _declarer(version_id, f"{code}.station.read")

    async with AsyncSessionLocal() as db:
        db.add(ModulePermission(moduleVersionId=version_id, code=f"{code}.station.read", scope="organization"))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def test_ca2_code_non_declare_par_la_version_installee_est_refuse_en_422():
    """CA-2 : un code déclaré seulement par une version non publiée n'est pas accordable (422) ;
    un code déclaré par la version installée passe."""
    code = _code_module()
    _, version_installee = await _module_avec_version(code)
    _, version_brouillon = await _module_avec_version(code, publiee=False)
    await _declarer(version_installee, f"{code}.station.read")
    await _declarer(version_brouillon, f"{code}.station.brouillon")

    async with AsyncSessionLocal() as db:
        await exiger_permissions_declarees(db, code, [f"{code}.station.read"])
        with pytest.raises(AppError) as hors_version:
            await exiger_permissions_declarees(db, code, [f"{code}.station.brouillon"])
        assert hors_version.value.status_code == 422
        with pytest.raises(AppError) as inconnu:
            await exiger_permissions_declarees(db, code, [f"{code}.station.inconnu"])
        assert inconnu.value.status_code == 422


async def test_ca3_membre_sans_organization_module_read_recoit_403(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-3 : un membre sans `organization.module.read` est refusé et ne voit aucune permission."""
    code = _code_module()
    module_id, version_id = await _module_avec_version(code)
    secret = f"{code}.secret.read"
    await _declarer(version_id, secret)
    token = await _membre_sans_droit(client, uuid.UUID(organization["id"]))

    reponse = await client.get(_url(organization["id"], module_id), headers=_entete(token, organization["id"]))

    assert reponse.status_code == 403
    assert secret not in reponse.text


async def test_ca3_proprietaire_lit_les_permissions_de_la_version_installee_seulement(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """Lecture nominale : le propriétaire voit les codes de la version installée, pas ceux d'un brouillon."""
    code = _code_module()
    module_id, version_installee = await _module_avec_version(code)
    _, version_brouillon = await _module_avec_version(code, publiee=False)
    await _declarer(version_installee, f"{code}.station.read")
    await _declarer(version_brouillon, f"{code}.station.brouillon")

    reponse = await client.get(
        _url(organization["id"], module_id),
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 200, reponse.text
    assert [p["code"] for p in reponse.json()] == [f"{code}.station.read"]


async def test_ca4_organisation_d_un_autre_tenant_repond_404_sans_donnee(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : le membre de A appelant /organizations/B/modules/{id}/permissions reçoit 404, en chemin
    comme en en-tête, et rien de B n'est renvoyé."""
    code = _code_module()
    module_id, version_id = await _module_avec_version(code)
    await _declarer(version_id, f"{code}.donnee.b")
    autre = await client.post(
        "/api/v1/auth/register",
        json={"email": f"be055-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com", "password": MOT_DE_PASSE, "fullName": "Proprio B"},
    )
    login_autre = await client.post("/api/v1/auth/login", json={"email": autre.json()["email"], "password": MOT_DE_PASSE})
    res_b = await client.post(
        "/api/v1/organizations",
        json={"name": "Org B BE-055", "slug": f"be055-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {login_autre.json()['accessToken']}"},
    )
    org_b = res_b.json()["id"]
    token_a = registered_user["accessToken"]

    reponse_chemin = await client.get(_url(org_b, module_id), headers=_entete(token_a, organization["id"]))
    reponse_entete = await client.get(_url(org_b, module_id), headers=_entete(token_a, org_b))

    assert reponse_chemin.status_code == 404
    assert reponse_entete.status_code == 404
    assert f"{code}.donnee.b" not in reponse_chemin.text
    assert f"{code}.donnee.b" not in reponse_entete.text


async def test_lister_permissions_installees_module_absent_ou_sans_version_installee_404():
    """Une version installée absente (module sans version publiée) donne une erreur 404 explicite."""
    code = _code_module()
    module_id, _ = await _module_avec_version(code, publiee=False)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await lister_permissions_installees(db, module_id)
        assert erreur.value.status_code == 404
