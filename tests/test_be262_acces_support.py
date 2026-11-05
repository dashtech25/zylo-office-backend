"""BE-262 : accès support/admin en lecture seule par défaut.

Tests écrits d'après la définition `### BE-262` de
implementation-backend/tasks-fondation-recensement.md, avant le code.

Périmètre : table `acces_support` (nouvelle), service `app.support.service`,
routes sous `/api/v1/organizations/{organization_id}/acces-support`. Les noms de
route, de permissions et de colonnes marqués NON DÉFINI dans la source sont ceux
de la recommandation appliquée.

Couverture :
- CA-1 : un accès créé sans `mode` est en `lecture` ;
- CA-2 : une écriture sous un accès en `lecture` renvoie 403 et ne modifie rien ;
- CA-3 : un accès sans justification est refusé en 422 sans ligne ;
- CA-4 : un accès accordé pour l'organisation A ne permet pas de lire B (403) ;
- CA-5 : création d'accès et action sous accès produisent une ligne `audit_event` ;
- CA-6 : un accès dont `finUtc` est dépassé est refusé.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import OrganizationUser, User
from app.rbac.models import UserPermissionGrant
from app.rbac.service import get_or_create_permission
from app.support.models import AccesSupport
from app.support.permissions import SUPPORT_READ, SUPPORT_WRITE_SENSIBLE
from app.support.seed import seed_known_permissions
from app.support.service import executer_sous_acces
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"


def _route(organization_id: uuid.UUID | str) -> str:
    return f"/api/v1/organizations/{organization_id}/acces-support"


def _route_courant(organization_id: uuid.UUID | str) -> str:
    return f"{_route(organization_id)}/courant"


def _entete(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _nom_organisation(organization_id: uuid.UUID) -> str:
    async with AsyncSessionLocal() as db:
        return await db.scalar(text("SELECT name FROM organization WHERE id = :id").bindparams(id=organization_id))


async def _nombre_audit(organization_id: uuid.UUID, action: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            text('SELECT count(*) FROM audit_event WHERE "organizationId" = :org AND action = :action').bindparams(
                org=organization_id, action=action
            )
        ) or 0


async def _nombre_acces(organization_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            text('SELECT count(*) FROM acces_support WHERE "organizationId" = :org').bindparams(org=organization_id)
        ) or 0


async def _creer_acces_direct(
    organization_id: uuid.UUID,
    support_user_id: uuid.UUID,
    granter_user_id: uuid.UUID,
    mode: str = "lecture",
    debut: datetime | None = None,
    fin: datetime | None = None,
) -> uuid.UUID:
    """Insère un accès en base, sans passer par la route (fixture de test)."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        acces = AccesSupport(
            organizationId=organization_id,
            supportUserId=support_user_id,
            creeParUserId=granter_user_id,
            mode=mode,
            justification="Test BE262 : accès direct",
            debutUtc=debut or maintenant - timedelta(hours=1),
            finUtc=fin or maintenant + timedelta(days=1),
        )
        db.add(acces)
        await db.commit()
        return acces.id


async def _organisation_autre(client: AsyncClient) -> uuid.UUID:
    """Organisation B, propre à un autre utilisateur, sans lien avec l'accès support."""
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Autre BE262"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Organisation B BE262", "slug": f"org-b-be262-{uuid.uuid4().hex[:8]}"},
        headers=_entete(token),
    )
    assert res.status_code == 201, res.text
    return uuid.UUID(res.json()["id"])


@pytest.fixture
async def contexte_support(client: AsyncClient, registered_user: dict, organization: dict):
    """Organisation A (propriétaire = registered_user) et un utilisateur support.

    Le support est membre de A et détient `support.read` et `support.write_sensible`
    par grant individuel `allow`. Le grant est inséré directement : aucun
    propriétaire n'a ces permissions par défaut (non-élévation de privilège)."""
    await seed_known_permissions()

    email_support = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email_support, "password": MOT_DE_PASSE, "fullName": "Support BE262"})
    login = await client.post("/api/v1/auth/login", json={"email": email_support, "password": MOT_DE_PASSE})
    token_support = login.json()["accessToken"]

    org_id = uuid.UUID(organization["id"])
    async with AsyncSessionLocal() as db:
        proprietaire = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        support = (await db.execute(select(User).where(User.email == email_support))).scalar_one()
        db.add(OrganizationUser(organizationId=org_id, userId=support.id))
        for code in (SUPPORT_READ, SUPPORT_WRITE_SENSIBLE):
            permission = await get_or_create_permission(db, code, "support", f"Permission de test {code} (BE262).")
            db.add(
                UserPermissionGrant(
                    organizationId=org_id,
                    userId=support.id,
                    permissionId=permission.id,
                    effect="allow",
                    grantedByUserId=proprietaire.id,
                    validFrom=datetime.now(timezone.utc) - timedelta(days=1),
                    origin="direct",
                )
            )
        await db.commit()
        support_id = support.id
        proprietaire_id = proprietaire.id

    return {
        "org_id": org_id,
        "owner_token": registered_user["accessToken"],
        "owner_id": proprietaire_id,
        "support_id": support_id,
        "support_token": token_support,
    }


# --- CA-1 : mode par défaut `lecture` ---------------------------------------------


async def test_be262_ca1_acces_sans_mode_est_en_lecture(client: AsyncClient, contexte_support: dict):
    """CA-1 : une création sans `mode` produit un accès en `lecture`, en réponse et en base."""
    org_id = contexte_support["org_id"]

    res = await client.post(
        _route(org_id),
        json={"supportUserId": str(contexte_support["support_id"]), "justification": "Ticket BE262 CA-1"},
        headers=_entete(contexte_support["owner_token"]),
    )

    assert res.status_code == 201, res.text
    assert res.json()["mode"] == "lecture"
    async with AsyncSessionLocal() as db:
        mode = await db.scalar(
            text("SELECT mode FROM acces_support WHERE id = :id").bindparams(id=uuid.UUID(res.json()["id"]))
        )
    assert mode == "lecture"


# --- CA-2 : écriture refusée sous un accès en lecture -----------------------------


async def test_be262_ca2_ecriture_sous_acces_lecture_refusee_sans_modification(client: AsyncClient, contexte_support: dict):
    """CA-2 : une action d'écriture sous un accès en `lecture` renvoie 403, ne
    modifie pas l'organisation et ne journalise aucune action réussie."""
    org_id = contexte_support["org_id"]
    await _creer_acces_direct(org_id, contexte_support["support_id"], contexte_support["owner_id"], mode="lecture")
    nom_avant = await _nom_organisation(org_id)
    action = "support.test.ecriture.be262"

    async def modifier(session):
        await session.execute(text("UPDATE organization SET name = 'Modifie BE262' WHERE id = :id").bindparams(id=org_id))

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await executer_sous_acces(
                db,
                org_id,
                contexte_support["support_id"],
                action=action,
                ecriture=True,
                entity_type="Organization",
                entity_id=org_id,
                summary="Tentative d'écriture BE262 CA-2",
                mutation=modifier,
            )
        await db.rollback()

    assert erreur.value.status_code == 403
    assert await _nom_organisation(org_id) == nom_avant
    assert await _nombre_audit(org_id, action) == 0


# --- CA-3 : justification obligatoire ---------------------------------------------


@pytest.mark.parametrize("justification", [None, "", "   "])
async def test_be262_ca3_sans_justification_refus_422_sans_ligne(client: AsyncClient, contexte_support: dict, justification):
    """CA-3 : sans justification (absente, vide ou blanche), la création est refusée
    en 422 et aucune ligne `acces_support` n'est écrite."""
    org_id = contexte_support["org_id"]
    avant = await _nombre_acces(org_id)

    res = await client.post(
        _route(org_id),
        json={"supportUserId": str(contexte_support["support_id"]), "mode": "lecture", "justification": justification},
        headers=_entete(contexte_support["owner_token"]),
    )

    assert res.status_code == 422, res.text
    assert await _nombre_acces(org_id) == avant


# --- CA-4 : isolation tenant ------------------------------------------------------


async def test_be262_ca4_acces_organisation_a_ne_lit_pas_organisation_b(client: AsyncClient, contexte_support: dict):
    """CA-4 : l'accès accordé pour A permet la lecture de A, jamais celle de B (403)."""
    org_a = contexte_support["org_id"]
    await _creer_acces_direct(org_a, contexte_support["support_id"], contexte_support["owner_id"], mode="lecture")
    org_b = await _organisation_autre(client)

    res_a = await client.get(_route_courant(org_a), headers=_entete(contexte_support["support_token"]))
    res_b = await client.get(_route_courant(org_b), headers=_entete(contexte_support["support_token"]))

    assert res_a.status_code == 200, res_a.text
    assert res_b.status_code == 403, res_b.text

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await executer_sous_acces(
                db,
                org_b,
                contexte_support["support_id"],
                action="support.test.lecture.be262",
                ecriture=False,
                entity_type="Organization",
                entity_id=org_b,
                summary="Lecture BE262 CA-4 sur B",
            )
    assert erreur.value.status_code == 403


# --- CA-5 : audit de l'accès et de chaque action ----------------------------------


async def test_be262_ca5_creation_et_actions_sous_acces_journalisees(client: AsyncClient, contexte_support: dict):
    """CA-5 : la création d'un accès, sa lecture et une action d'écriture sous accès
    produisent chacune exactement une ligne `audit_event`."""
    org_id = contexte_support["org_id"]

    res = await client.post(
        _route(org_id),
        json={"supportUserId": str(contexte_support["support_id"]), "justification": "Ticket BE262 CA-5"},
        headers=_entete(contexte_support["owner_token"]),
    )
    assert res.status_code == 201, res.text
    assert await _nombre_audit(org_id, "support.acces.cree") == 1

    res_lecture = await client.get(_route_courant(org_id), headers=_entete(contexte_support["support_token"]))
    assert res_lecture.status_code == 200, res_lecture.text
    assert await _nombre_audit(org_id, "support.acces.lecture") == 1

    await _creer_acces_direct(org_id, contexte_support["support_id"], contexte_support["owner_id"], mode="ecriture")
    action = "support.test.ecriture.ca5"

    async def renommer(session):
        await session.execute(text("UPDATE organization SET name = 'Renomme BE262 CA5' WHERE id = :id").bindparams(id=org_id))

    async with AsyncSessionLocal() as db:
        await executer_sous_acces(
            db,
            org_id,
            contexte_support["support_id"],
            action=action,
            ecriture=True,
            entity_type="Organization",
            entity_id=org_id,
            summary="Renommage BE262 CA-5",
            mutation=renommer,
        )
        await db.commit()

    assert await _nombre_audit(org_id, action) == 1
    assert await _nom_organisation(org_id) == "Renomme BE262 CA5"


# --- CA-6 : fin de l'accès --------------------------------------------------------


async def test_be262_ca6_acces_dont_fin_utc_est_depassee_refuse(client: AsyncClient, contexte_support: dict):
    """CA-6 : un accès actif est accepté ; le même accès, après `finUtc`, est refusé (403)."""
    org_id = contexte_support["org_id"]
    maintenant = datetime.now(timezone.utc)
    token = contexte_support["support_token"]

    await _creer_acces_direct(
        org_id,
        contexte_support["support_id"],
        contexte_support["owner_id"],
        mode="lecture",
        debut=maintenant - timedelta(hours=2),
        fin=maintenant + timedelta(hours=1),
    )
    actif = await client.get(_route_courant(org_id), headers=_entete(token))
    assert actif.status_code == 200, actif.text

    async with AsyncSessionLocal() as db:
        await db.execute(
            text('UPDATE acces_support SET "finUtc" = :fin WHERE "organizationId" = :org').bindparams(
                fin=maintenant - timedelta(minutes=1), org=org_id
            )
        )
        await db.commit()

    expire = await client.get(_route_courant(org_id), headers=_entete(token))
    assert expire.status_code == 403, expire.text
