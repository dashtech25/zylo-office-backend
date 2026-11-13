"""BE-162 : routes API des connecteurs.

Tests écrits d'après la définition `### BE-162` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : `POST /api/v1/connecteurs` crée un connecteur à l'état `création` et renvoie `201` ;
- CA-2 : `POST /api/v1/connecteurs/{id}/transitions` renvoie `200` pour une transition valide,
  `409` pour une transition interdite (et n'écrit rien) ;
- CA-3 : sans `integrations.manage`, `POST` renvoie `403` PERMISSION_DENIED et ne crée rien ;
- CA-4 : la réponse `GET` ne contient aucun champ de secret ;
- CA-5 : `GET` pour le tenant A n'expose aucun connecteur du tenant B, et une transition sur un
  connecteur d'un autre tenant renvoie `404`.

Permissions : `integrations.read` pour le `GET`, `integrations.manage` pour les écritures
(déclarées par `app/integrations/permissions.py`).
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.audit.ecriture import IdentiteEmettrice
from app.core.database import AsyncSessionLocal
from app.identity.models import Organization, OrganizationUser, User
from app.integrations.models import Connecteur
from app.integrations.registre import creer_connecteur
from app.rbac.models import Permission, Role, RolePermission, UserRole

INTEGRATIONS_READ = "integrations.read"
INTEGRATIONS_MANAGE = "integrations.manage"
CHAMPS_SECRETS = ("secret", "token", "motdepasse", "mot_de_passe", "password", "cle", "clé", "valeur")


def _entete(utilisateur: dict, organization_id: str) -> dict:
    return {
        "Authorization": f"Bearer {utilisateur['accessToken']}",
        "X-Organization-Id": organization_id,
    }


async def _accorder(user_id: uuid.UUID, org_id: uuid.UUID, codes: list[str]) -> None:
    """Attribue à l'utilisateur un rôle de test portant `codes` dans `org_id` (comme BE-164)."""
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=org_id, code=f"be162-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-162")
        db.add(role)
        await db.flush()
        for code in codes:
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(code=code, moduleCode="integrations", description="Permission de test BE-162")
                db.add(permission)
                await db.flush()
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        db.add(UserRole(userId=user_id, organizationId=org_id, roleId=role.id))
        await db.commit()


async def _utilisateur_id(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _membre_sans_droit(client, organization_id: str) -> dict:
    """Inscrit un utilisateur, le rattache à l'organisation, sans aucun rôle (refus `403`)."""
    from tests.conftest import unique_email

    email = unique_email()
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Sans droit"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=user.id))
        await db.commit()
    return {"email": email, "accessToken": login.json()["accessToken"], "id": str(user.id)}


async def _autre_organisation(user_id: uuid.UUID) -> uuid.UUID:
    """Crée un tenant B et un connecteur qui lui appartient (seed par le registre, BE-160)."""
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="Tenant B BE-162", slug=f"be162-b-{uuid.uuid4().hex[:10]}")
        db.add(organisation)
        await db.flush()
        org_id = organisation.id
        await db.commit()
    async with AsyncSessionLocal() as db:
        connecteur = await creer_connecteur(
            db,
            IdentiteEmettrice(user_id=user_id, organization_id=org_id),
            portee="tenant",
            nom="Connecteur du tenant B",
            organization_id=org_id,
        )
        await db.commit()
        return connecteur.id


async def _nombre_connecteurs(organization_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count()).select_from(Connecteur).where(Connecteur.organizationId == uuid.UUID(organization_id))
        )


async def _etat_en_base(connecteur_id: str) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(Connecteur.etat).where(Connecteur.id == uuid.UUID(connecteur_id)))).scalar_one()


async def _creer_via_route(client, proprietaire: dict, organization: dict) -> str:
    res = await client.post(
        "/api/v1/connecteurs",
        json={"nom": f"Connecteur {uuid.uuid4().hex[:8]}"},
        headers=_entete(proprietaire, organization["id"]),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest.fixture
async def gestionnaire(client, registered_user: dict, organization: dict) -> dict:
    """Propriétaire de test avec les permissions de lecture et d'écriture des connecteurs."""
    await _accorder(await _utilisateur_id(registered_user["email"]), uuid.UUID(organization["id"]),
                    [INTEGRATIONS_READ, INTEGRATIONS_MANAGE])
    return registered_user


async def test_ca1_post_cree_connecteur_en_etat_creation(client, gestionnaire, organization):
    res = await client.post(
        "/api/v1/connecteurs",
        json={"nom": "Connecteur CA-1"},
        headers=_entete(gestionnaire, organization["id"]),
    )

    assert res.status_code == 201, res.text
    corps = res.json()
    assert corps["etat"] == "création"
    assert await _etat_en_base(corps["id"]) == "création"


async def test_ca2_transition_valide_200_et_interdite_409_sans_ecriture(client, gestionnaire, organization):
    entete = _entete(gestionnaire, organization["id"])
    connecteur_id = await _creer_via_route(client, gestionnaire, organization)
    url = f"/api/v1/connecteurs/{connecteur_id}/transitions"

    valide = await client.post(url, json={"cible": "activé"}, headers=entete)
    assert valide.status_code == 200, valide.text
    assert valide.json()["etat"] == "activé"

    await client.post(url, json={"cible": "révoqué"}, headers=entete)
    interdite = await client.post(url, json={"cible": "activé"}, headers=entete)

    assert interdite.status_code == 409, interdite.text
    assert interdite.json()["error"]["code"] == "CONNECTEUR_TRANSITION_INTERDITE"
    assert await _etat_en_base(connecteur_id) == "révoqué"


async def test_ca3_post_sans_permission_manage_renvoie_403_et_ne_cree_rien(client, gestionnaire, organization):
    organisation_id = organization["id"]
    sans_droit = await _membre_sans_droit(client, organisation_id)
    avant = await _nombre_connecteurs(organisation_id)

    res = await client.post(
        "/api/v1/connecteurs",
        json={"nom": "Connecteur refusé"},
        headers=_entete(sans_droit, organisation_id),
    )

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"
    assert await _nombre_connecteurs(organisation_id) == avant


async def test_ca4_get_ne_contient_aucun_champ_de_secret(client, gestionnaire, organization):
    await _creer_via_route(client, gestionnaire, organization)

    res = await client.get("/api/v1/connecteurs", headers=_entete(gestionnaire, organization["id"]))

    assert res.status_code == 200, res.text
    assert res.json(), "la liste doit contenir au moins le connecteur créé"
    for connecteur in res.json():
        for cle in connecteur:
            assert not any(motif in cle.lower() for motif in CHAMPS_SECRETS), f"champ sensible exposé : {cle}"


async def test_ca5_isolation_tenant_liste_et_transition(client, gestionnaire, organization):
    connecteur_b = await _autre_organisation(await _utilisateur_id(gestionnaire["email"]))
    entete = _entete(gestionnaire, organization["id"])

    liste = await client.get("/api/v1/connecteurs", headers=entete)
    assert liste.status_code == 200, liste.text
    assert str(connecteur_b) not in [c["id"] for c in liste.json()]

    transition = await client.post(
        f"/api/v1/connecteurs/{connecteur_b}/transitions", json={"cible": "activé"}, headers=entete
    )
    assert transition.status_code == 404, transition.text
    assert await _etat_en_base(str(connecteur_b)) == "création"
