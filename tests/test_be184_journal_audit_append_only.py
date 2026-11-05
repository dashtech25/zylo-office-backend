"""BE-184 : journal d'audit append-only et route de lecture `GET /api/v1/audit/records`.

Tests écrits d'après la définition `### BE-184` de
implementation-backend/tasks-donnees-api-contrats.md, avant le code de la route.

Périmètre : aucune table créée ; la table unique `audit_event` (BE-007, immuable
par le trigger de BE-260) est consommée. Organisation désignée par l'en-tête
`X-Organization-Id`.

Écarts avec la définition, signalés ici et dans app/audit/router.py :
- la définition cite la permission `audit.read` ; le code existant (BE-033, BE-172)
  porte `audit.log.view`. Le code réutilise `audit.log.view` (aucun doublon) ;
- les paramètres de recherche de `/records` ne sont pas définis : ils sont ceux de
  `GET /api/v1/audit/evenements` (BE-172) ; `dateDebut`, `dateFin`, `sujetType` obligatoires.

Couverture :
- CA-1 : une insertion réussit ; une mise à jour et une suppression sont rejetées par le moteur ;
- CA-2 : lecture sans `audit.log.view` renvoie 403 ;
- CA-3 : lecture du journal d'un autre tenant renvoie 404, sans fuite de contenu ;
- CA-4 : mot de passe, jeton et clé API présents dans un diff sont absents de l'enregistrement ;
- CA-5 : chaque lecture du journal produit elle-même une entrée d'audit ;
- CA-6 : une mutation échoue si son entrée d'audit ne peut être écrite (fail-closed).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.audit.ecriture import IdentiteEmettrice, executer_mutation_sensible
from app.audit.models import AuditEvent
from app.audit.service import REDACTION, record_audit_event
from app.core.database import AsyncSessionLocal
from app.core.erreurs.codes import CodeErreur
from app.core.errors import AppError
from app.identity.models import OrganizationUser, User
from app.rbac.models import Permission, RolePermission, UserRole
from app.rbac.service import get_or_create_permission
from tests.conftest import unique_email

ROUTE = "/api/v1/audit/records"
MOT_DE_PASSE = "TestPassword123!"
ACTION_LECTURE = "audit.journal.consulte"
SECRET_MOT_DE_PASSE = "MotDePasseSecret-BE184"
SECRET_JETON = "jeton-acces-BE184-xyz"
SECRET_CLE_API = "cle-api-BE184-abc"


def _entetes(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _periode() -> dict:
    """Fenêtre encadrant l'instant présent : contient les entrées créées par les tests."""
    maintenant = datetime.now(timezone.utc)
    return {
        "dateDebut": (maintenant - timedelta(hours=1)).isoformat(),
        "dateFin": (maintenant + timedelta(hours=1)).isoformat(),
    }


async def _id_de(utilisateur: dict) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User).where(User.email == utilisateur["email"]))).scalar_one().id


async def _inscrire_et_connecter(client: AsyncClient) -> dict:
    """Crée un compte et renvoie son courriel et son jeton d'accès."""
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE184"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    return {"email": email, "accessToken": login.json()["accessToken"]}


async def _ajouter_membre_sans_permission(client: AsyncClient, organization_id: str) -> dict:
    """Membre actif de l'organisation, sans aucun rôle ni grant."""
    membre = await _inscrire_et_connecter(client)
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == membre["email"]))).scalar_one()
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=user.id))
        await db.commit()
    return membre


async def _nouvel_utilisateur_avec_organisation(client: AsyncClient) -> dict:
    """Utilisateur propriétaire d'une organisation qui lui est propre (tenant B)."""
    utilisateur = await _inscrire_et_connecter(client)
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Organisation B BE184", "slug": f"org-b-be184-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {utilisateur['accessToken']}"},
    )
    assert res.status_code == 201, res.text
    utilisateur["organizationId"] = res.json()["id"]
    return utilisateur


async def _enregistrer(
    organization_id: str,
    actor_user_id: uuid.UUID,
    entity_type: str,
    summary: str,
    changes: dict | None = None,
) -> uuid.UUID:
    """Écrit une entrée réelle via le service d'écriture (BE-007) et renvoie son identifiant."""
    async with AsyncSessionLocal() as db:
        entree = await record_audit_event(
            db,
            uuid.UUID(organization_id),
            actor_user_id,
            "test.be184.action",
            entity_type,
            None,
            summary,
            changes=changes,
        )
        await db.commit()
        return entree.id


async def _nombre_de_lectures(organization_id: str) -> int:
    """Nombre d'entrées de lecture du journal dans l'organisation."""
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            text('SELECT count(*) FROM audit_event WHERE "organizationId" = :org AND action = :action').bindparams(
                org=uuid.UUID(organization_id), action=ACTION_LECTURE
            )
        ) or 0


async def test_be184_ca1_insertion_reussit_et_mise_a_jour_suppression_rejetees(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : une insertion réussit ; un UPDATE et un DELETE sur `audit_event` sont rejetés
    par le moteur, et la ligne reste inchangée."""
    user_id = await _id_de(registered_user)
    entree_id = await _enregistrer(organization["id"], user_id, "TestBe184Ca1", "Résumé original BE184")

    with pytest.raises(DBAPIError):
        async with AsyncSessionLocal() as db:
            await db.execute(text("UPDATE audit_event SET summary = 'modifié BE184' WHERE id = :id").bindparams(id=entree_id))
            await db.commit()

    with pytest.raises(DBAPIError):
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM audit_event WHERE id = :id").bindparams(id=entree_id))
            await db.commit()

    async with AsyncSessionLocal() as db:
        resume = await db.scalar(text("SELECT summary FROM audit_event WHERE id = :id").bindparams(id=entree_id))
    assert resume == "Résumé original BE184"


async def test_be184_ca2_lecture_sans_audit_log_view_renvoie_403(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-2 : un membre sans `audit.log.view` reçoit 403 `permission_denied`."""
    membre = await _ajouter_membre_sans_permission(client, organization["id"])

    res = await client.get(
        ROUTE,
        params={**_periode(), "sujetType": "TestBe184Ca2"},
        headers=_entetes(membre["accessToken"], organization["id"]),
    )

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "permission_denied"


async def test_be184_ca3_journal_d_un_autre_tenant_renvoie_404(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-3 : un utilisateur de l'organisation B qui lit le journal de A reçoit 404,
    et aucune entrée de A n'apparaît dans la réponse."""
    user_a = await _id_de(registered_user)
    await _enregistrer(organization["id"], user_a, "TestBe184Ca3", "Entrée confidentielle de A BE184")
    autre = await _nouvel_utilisateur_avec_organisation(client)

    res = await client.get(
        ROUTE,
        params={**_periode(), "sujetType": "TestBe184Ca3"},
        headers=_entetes(autre["accessToken"], organization["id"]),
    )

    assert res.status_code == 404, res.text
    assert "Entrée confidentielle de A BE184" not in res.text


async def test_be184_ca4_secrets_absents_de_l_enregistrement(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-4 : mot de passe, jeton et clé API présents dans le diff n'apparaissent pas dans
    l'entrée d'audit ; les champs non sensibles du diff sont conservés."""
    user_id = await _id_de(registered_user)
    await _enregistrer(
        organization["id"],
        user_id,
        "TestBe184Ca4",
        "Diff avec secrets BE184",
        changes={
            "password": SECRET_MOT_DE_PASSE,
            "diff": {"accessToken": SECRET_JETON, "apiKey": SECRET_CLE_API, "nom": "valeur-publique-BE184"},
        },
    )

    res = await client.get(
        ROUTE,
        params={**_periode(), "sujetType": "TestBe184Ca4"},
        headers=_entetes(registered_user["accessToken"], organization["id"]),
    )

    assert res.status_code == 200, res.text
    corps = res.text
    for secret in (SECRET_MOT_DE_PASSE, SECRET_JETON, SECRET_CLE_API):
        assert secret not in corps
    assert REDACTION in corps
    assert "valeur-publique-BE184" in corps


async def test_be184_ca5_chaque_lecture_produit_une_entree_d_audit(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-5 : chaque lecture de `/records` ajoute exactement une entrée de lecture
    dans le journal de l'organisation, portée par l'acteur qui lit."""
    entetes = _entetes(registered_user["accessToken"], organization["id"])
    avant = await _nombre_de_lectures(organization["id"])

    premiere = await client.get(ROUTE, params={**_periode(), "sujetType": "TestBe184Ca5"}, headers=entetes)
    assert premiere.status_code == 200, premiere.text
    apres_une = await _nombre_de_lectures(organization["id"])
    assert apres_une == avant + 1

    deuxieme = await client.get(ROUTE, params={**_periode(), "sujetType": "TestBe184Ca5"}, headers=entetes)
    assert deuxieme.status_code == 200, deuxieme.text
    assert await _nombre_de_lectures(organization["id"]) == avant + 2

    async with AsyncSessionLocal() as db:
        acteur = await db.scalar(
            select(AuditEvent.actorUserId).where(
                AuditEvent.organizationId == uuid.UUID(organization["id"]), AuditEvent.action == ACTION_LECTURE
            ).limit(1)
        )
    assert acteur == await _id_de(registered_user)


async def test_be184_ca6_mutation_annulee_si_son_entree_d_audit_echoue(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-6 : si l'entrée d'audit d'une mutation ne peut être écrite, la mutation est annulée
    et l'erreur `AUDIT_WRITE_FAILED` est levée. L'action est trop longue pour `audit_event.action`
    (150 caractères) : l'écriture d'audit échoue à l'insertion."""
    user_id = await _id_de(registered_user)
    org_id = uuid.UUID(organization["id"])
    code_permission = f"test.be184.ca6.{uuid.uuid4().hex[:8]}"
    action_trop_longue = "a" * 151

    async def mutation(db):
        return await get_or_create_permission(db, code_permission, "test", "Mutation BE184 CA-6")

    with pytest.raises(AppError) as erreur:
        async with AsyncSessionLocal() as db:
            await executer_mutation_sensible(
                db,
                IdentiteEmettrice(user_id=user_id, organization_id=org_id),
                org_id,
                action_trop_longue,
                "TestBe184Ca6",
                None,
                "Mutation BE184",
                mutation,
            )
            await db.commit()

    assert erreur.value.code == CodeErreur.AUDIT_WRITE_FAILED.value

    async with AsyncSessionLocal() as db:
        cree = await db.scalar(select(Permission.id).where(Permission.code == code_permission))
    assert cree is None
