"""BE-158 : routes API des paramètres, sous `/api/v1/parametres`.

Tests écrits d'après la définition `### BE-158` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : `GET` renvoie la valeur résolue, sa source de niveau et sa version ;
- CA-2 : `PUT` valide renvoie `200` et la nouvelle version ; `PUT` sans `reason` renvoie `422` ;
- CA-3 : `PUT` avec une version attendue périmée renvoie `409` VERSION_CONFLICT sans rien modifier ;
- CA-4 (refus) : `PUT` sans permission d'écriture renvoie `403` ; `GET` sans `settings.read` renvoie `403` ;
- CA-5 : scope d'un autre tenant renvoie `404`, sans révéler l'existence du scope ;
- restauration : `POST .../restaurations` crée une nouvelle version recopiant une version antérieure.

Hypothèses de test (points NON DÉFINI ou contradictoires, à confirmer en QE) :
- lecture : permission `settings.read`, citée par la source (QE-PAR-03 pour l'écriture) ;
- écriture : permission `parametres.setting.apply`, déjà déclarée par BE-157, et non
  `settings.write` nommée dans la définition (contradiction signalée : voir QE) ;
- forme de réponse : liste d'objets `cle`, `valeur`, `source`, `version` ;
- en-tête de version attendue : `X-Expected-Version` (nom non tranché par la définition) ;
- organisation active désignée par l'en-tête `X-Organization-Id`, comme les autres routes tenant.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.identity.models import User
from app.parametres.models import SettingDefinition, SettingValue
from app.parametres.permissions import PARAMETRE_APPLIQUER
from app.parametres.service import ecrire_version
from app.rbac.models import Role, RolePermission
from app.rbac.service import get_or_create_permission

PERMISSION_LECTURE = "settings.read"
URL_BASE = "/api/v1/parametres"


async def _accorder(permission_code: str, org_id: uuid.UUID, description: str) -> None:
    """Accorde une permission au rôle propriétaire de l'organisation (helper local au test)."""
    async with AsyncSessionLocal() as db:
        role = (await db.execute(select(Role).where(Role.organizationId == org_id, Role.code == "owner"))).scalar_one()
        permission = await get_or_create_permission(db, permission_code, "parametres", description)
        db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        await db.commit()


async def _definition(defaut: str = "defaut") -> str:
    """Crée une définition de paramètre de portée organisation, avec une valeur par défaut."""
    cle = f"be158.{uuid.uuid4().hex[:12]}"
    async with AsyncSessionLocal() as db:
        db.add(
            SettingDefinition(
                key=cle, scopeKind="organisation", owner="test", valueType="texte", defaultValue=defaut, sensitive=False
            )
        )
        await db.commit()
    return cle


async def _version_appliquee(cle: str, org_id: uuid.UUID, user_id: uuid.UUID, valeur: str) -> None:
    """Insère la version 1 appliquée du paramètre pour l'organisation."""
    async with AsyncSessionLocal() as db:
        await ecrire_version(db, cle, "organisation", org_id, 1, valeur, user_id, "initial", applied=True)


async def _versions(cle: str, org_id: uuid.UUID) -> list[tuple[int, bool, object]]:
    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(
                select(SettingValue.version, SettingValue.applied, SettingValue.value)
                .where(SettingValue.definitionKey == cle, SettingValue.scopeId == org_id)
                .order_by(SettingValue.version)
            )
        ).all()
    return [tuple(ligne) for ligne in lignes]


async def _utilisateur_id(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


def _entetes(registered_user: dict, organization: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}


async def test_be158_ca1_get_renvoie_valeur_source_et_version(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = uuid.UUID(organization["id"])
    cle = await _definition()
    await _version_appliquee(cle, org_id, await _utilisateur_id(registered_user["email"]), "v1")
    await _accorder(PERMISSION_LECTURE, org_id, "Lire les paramètres (BE-158).")

    reponse = await client.get(f"{URL_BASE}/organisation/{org_id}", headers=_entetes(registered_user, organization))

    assert reponse.status_code == 200, reponse.text
    item = next(p for p in reponse.json() if p["cle"] == cle)
    assert item["valeur"] == "v1", "la valeur résolue est celle de l'organisation"
    assert item["source"] == "organisation", "la source de niveau est indiquée"
    assert item["version"] == 1, "la version de la valeur retenue est renvoyée"


async def test_be158_ca2_put_valide_renvoie_200_et_nouvelle_version(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = uuid.UUID(organization["id"])
    cle = await _definition()
    await _version_appliquee(cle, org_id, await _utilisateur_id(registered_user["email"]), "v1")
    await _accorder(PARAMETRE_APPLIQUER, org_id, "Appliquer une valeur (BE-158).")

    reponse = await client.put(
        f"{URL_BASE}/organisation/{org_id}/{cle}",
        json={"value": "v2", "reason": "essai"},
        headers={**_entetes(registered_user, organization), "X-Expected-Version": "1"},
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["version"] == 2, "la réponse porte la nouvelle version"
    assert await _versions(cle, org_id) == [(1, False, "v1"), (2, True, "v2")]


async def test_be158_ca2_put_sans_reason_renvoie_422(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = uuid.UUID(organization["id"])
    cle = await _definition()
    await _version_appliquee(cle, org_id, await _utilisateur_id(registered_user["email"]), "v1")
    await _accorder(PARAMETRE_APPLIQUER, org_id, "Appliquer une valeur (BE-158).")

    reponse = await client.put(
        f"{URL_BASE}/organisation/{org_id}/{cle}",
        json={"value": "v2"},
        headers={**_entetes(registered_user, organization), "X-Expected-Version": "1"},
    )

    assert reponse.status_code == 422, reponse.text
    assert await _versions(cle, org_id) == [(1, True, "v1")], "une requête invalide n'écrit rien"


async def test_be158_ca3_version_attendue_perimee_renvoie_409_sans_ecriture(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = uuid.UUID(organization["id"])
    cle = await _definition()
    await _version_appliquee(cle, org_id, await _utilisateur_id(registered_user["email"]), "v1")
    await _accorder(PARAMETRE_APPLIQUER, org_id, "Appliquer une valeur (BE-158).")

    reponse = await client.put(
        f"{URL_BASE}/organisation/{org_id}/{cle}",
        json={"value": "v2", "reason": "essai"},
        headers={**_entetes(registered_user, organization), "X-Expected-Version": "0"},
    )

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["error"]["code"] == "VERSION_CONFLICT"
    assert await _versions(cle, org_id) == [(1, True, "v1")], "un conflit de version ne modifie rien"


async def test_be158_ca4_put_sans_permission_renvoie_403(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = uuid.UUID(organization["id"])
    cle = await _definition()
    await _version_appliquee(cle, org_id, await _utilisateur_id(registered_user["email"]), "v1")
    # Aucune permission d'écriture accordée : le propriétaire ne l'a pas par défaut.

    reponse = await client.put(
        f"{URL_BASE}/organisation/{org_id}/{cle}",
        json={"value": "v2", "reason": "refus"},
        headers={**_entetes(registered_user, organization), "X-Expected-Version": "1"},
    )

    assert reponse.status_code == 403, reponse.text
    assert "PERMISSION_DENIED" in reponse.text
    assert await _versions(cle, org_id) == [(1, True, "v1")], "un refus n'écrit aucune version"


async def test_be158_ca4_get_sans_settings_read_renvoie_403(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = uuid.UUID(organization["id"])
    # Aucune permission `settings.read` accordée au propriétaire.

    reponse = await client.get(f"{URL_BASE}/organisation/{org_id}", headers=_entetes(registered_user, organization))

    assert reponse.status_code == 403, reponse.text


async def test_be158_ca5_scope_hors_tenant_renvoie_404_sans_fuite(client: AsyncClient, registered_user: dict, organization: dict):
    # Un second tenant, appartenant à un autre utilisateur.
    autre = {"email": f"be158-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com", "password": "TestPassword123!"}
    await client.post("/api/v1/auth/register", json={**autre, "fullName": "Autre"})
    login = await client.post("/api/v1/auth/login", json=autre)
    autre["accessToken"] = login.json()["accessToken"]
    autre_org = (
        await client.post(
            "/api/v1/organizations",
            json={"name": "Autre tenant", "slug": f"be158-{uuid.uuid4().hex[:8]}"},
            headers={"Authorization": f"Bearer {autre['accessToken']}"},
        )
    ).json()
    await _accorder(PERMISSION_LECTURE, uuid.UUID(autre_org["id"]), "Lire les paramètres (BE-158).")

    # L'utilisateur du tenant autre demande le scope du tenant `organization` avec son propre en-tête.
    entetes = {"Authorization": f"Bearer {autre['accessToken']}", "X-Organization-Id": autre_org["id"]}
    scope_vise = await client.get(f"{URL_BASE}/organisation/{organization['id']}", headers=entetes)
    scope_inexistant = await client.get(f"{URL_BASE}/organisation/{uuid.uuid4()}", headers=entetes)

    assert scope_vise.status_code == 404, scope_vise.text
    assert scope_inexistant.status_code == 404
    # Seule l'erreur est comparée : `request_id` est propre à chaque requête.
    assert scope_vise.json()["error"] == scope_inexistant.json()["error"], "la réponse ne révèle pas l'existence du scope"


async def test_be158_restauration_renvoie_nouvelle_version(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = uuid.UUID(organization["id"])
    cle = await _definition()
    await _version_appliquee(cle, org_id, await _utilisateur_id(registered_user["email"]), "v1")
    await _accorder(PARAMETRE_APPLIQUER, org_id, "Appliquer une valeur (BE-158).")
    await client.put(
        f"{URL_BASE}/organisation/{org_id}/{cle}",
        json={"value": "v2", "reason": "essai"},
        headers={**_entetes(registered_user, organization), "X-Expected-Version": "1"},
    )

    reponse = await client.post(
        f"{URL_BASE}/organisation/{org_id}/{cle}/restaurations",
        json={"version": 1, "reason": "retour"},
        headers={**_entetes(registered_user, organization), "X-Expected-Version": "2"},
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["version"] == 3
    assert await _versions(cle, org_id) == [(1, False, "v1"), (2, False, "v2"), (3, True, "v1")], "la version 1 n'est pas réécrite"
