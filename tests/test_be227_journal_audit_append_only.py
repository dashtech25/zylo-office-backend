"""BE-227 : journal d'audit append-only.

Tests écrits d'après la définition `### BE-227` de
implementation-backend/tasks-exploitation-architecture.md, avant le code.
La table est `audit_event` (BE-007) ; ces tests ne créent aucune table.

Couverture :
- CA-1 : une action privilégiée produit exactement une entrée contenant acteur,
  action, cible, tenant, motif et résultat ;
- CA-2 : UPDATE et DELETE sur une entrée sont refusés par la base ;
- CA-3 : une entrée du tenant A n'apparaît jamais dans la liste du tenant B ;
- CA-4 : aucun secret (mot de passe, jeton) dans `changes` ;
- CA-5 : si l'écriture d'audit échoue, l'action auditée échoue aussi.

Le droit de lecture est celui du module audit (`audit.log.view`, BE-007/BE-033) :
la définition le laisse à nommer (NON DÉFINI), on ne crée pas de permission doublon.
"""

import json
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.audit.ecriture import IdentiteEmettrice, executer_mutation_sensible
from app.audit.models import AuditEvent
from app.audit.service import record_audit_event, record_sensitive_action
from app.core.database import AsyncSessionLocal
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.identity.models import Organization, User
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"


def _route_audit(organization_id: str) -> str:
    return f"/api/v1/audit/organizations/{organization_id}"


async def _utilisateur_et_organisation(registered_user: dict, organization: dict) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        return user.id, uuid.UUID(organization["id"])


async def _nouvel_utilisateur_avec_organisation(client: AsyncClient) -> dict:
    """Crée un utilisateur propriétaire de sa propre organisation (tenant B)."""
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Autre"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    headers = {"Authorization": f"Bearer {token}"}
    org = await client.post(
        "/api/v1/organizations", json={"name": "Org B BE227", "slug": f"org-b-{uuid.uuid4().hex[:8]}"}, headers=headers
    )
    return {"accessToken": token, "organization": org.json()}


async def _nom_de_l_organisation(organization_id: uuid.UUID) -> str:
    async with AsyncSessionLocal() as db:
        return await db.scalar(text("SELECT name FROM organization WHERE id = :id").bindparams(id=organization_id))


def _renommer(org_id: uuid.UUID, nouveau_nom: str):
    async def mutation(db):
        organisation = await db.get(Organization, org_id)
        organisation.name = nouveau_nom
        await db.flush()
        return nouveau_nom

    return mutation


# --- CA-1 : une action privilégiée = exactement une entrée complète ---------------


async def test_be227_ca1_action_privilegiee_produit_une_entree_complete(registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be227.ca1.{uuid.uuid4().hex[:8]}"
    motif = "Renommage demandé par le support BE227"

    async with AsyncSessionLocal() as db:
        await record_sensitive_action(
            db, org_id, user_id, action, "Organization", org_id, "Renommage BE227", motif, changes={"name": "Nouveau"}
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        entrees = list((await db.execute(select(AuditEvent).where(AuditEvent.action == action))).scalars().all())

    assert len(entrees) == 1, "une action privilégiée produit exactement une entrée"
    entree = entrees[0]
    assert entree.actorUserId == user_id
    assert entree.organizationId == org_id
    assert entree.entityType == "Organization"
    assert entree.entityId == org_id
    assert entree.reason == motif
    assert entree.result == "success"
    assert entree.request_id and entree.eventId


async def test_be227_ca1_mutation_executee_porte_le_motif(registered_user: dict, organization: dict):
    """Une mutation sensible exécutée par `executer_mutation_sensible` porte le motif fourni."""
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)
    action = f"test.be227.ca1.motif.{uuid.uuid4().hex[:8]}"
    motif = "Changement validé par le propriétaire BE227"

    async with AsyncSessionLocal() as db:
        await executer_mutation_sensible(
            db, identite, org_id, action, "Organization", org_id, "Renommage BE227",
            _renommer(org_id, f"Renommée {uuid.uuid4().hex[:8]}"), motif=motif,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        motif_stocke = await db.scalar(select(AuditEvent.reason).where(AuditEvent.action == action))
    assert motif_stocke == motif


# --- CA-2 : aucune modification ni suppression d'entrée ---------------------------


async def test_be227_ca2_modification_et_suppression_refusees(registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    async with AsyncSessionLocal() as db:
        entree = await record_audit_event(db, org_id, user_id, f"test.be227.ca2.{uuid.uuid4().hex[:8]}", "Organization", org_id, "Résumé BE227 original")
        entree_id = entree.id
        await db.commit()

    for requete in (
        "UPDATE audit_event SET summary = 'modifié BE227' WHERE id = :id",
        "DELETE FROM audit_event WHERE id = :id",
    ):
        with pytest.raises(SQLAlchemyError):
            async with AsyncSessionLocal() as db:
                await db.execute(text(requete).bindparams(id=entree_id))
                await db.commit()

    async with AsyncSessionLocal() as db:
        resume = await db.scalar(text("SELECT summary FROM audit_event WHERE id = :id").bindparams(id=entree_id))
    assert resume == "Résumé BE227 original"


# --- CA-3 : isolation entre tenants ------------------------------------------------


async def test_be227_ca3_entree_de_a_absente_de_la_liste_de_b(client: AsyncClient, registered_user: dict, organization: dict):
    user_a, org_a = await _utilisateur_et_organisation(registered_user, organization)
    marqueur = f"Entrée confidentielle A BE227 {uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        await record_audit_event(db, org_a, user_a, f"test.be227.ca3.{uuid.uuid4().hex[:8]}", "Organization", org_a, marqueur)
        await db.commit()

    b = await _nouvel_utilisateur_avec_organisation(client)
    org_b = b["organization"]["id"]
    res = await client.get(
        _route_audit(org_b), headers={"Authorization": f"Bearer {b['accessToken']}"}
    )

    assert res.status_code == 200, res.text
    assert marqueur not in res.text

    res_a = await client.get(
        _route_audit(organization["id"]), headers={"Authorization": f"Bearer {b['accessToken']}"}
    )
    assert res_a.status_code == 404, "hors tenant : 404 (définition BE-227)"
    assert marqueur not in res_a.text


# --- CA-4 : redaction des secrets --------------------------------------------------


async def test_be227_ca4_aucun_secret_dans_l_entree(registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    secrets = ["secret-mdp-BE227-1", "jeton-BE227-2", "cookie-BE227-3"]
    changes = {
        "password": secrets[0],
        "nom": "valeur non sensible BE227",
        "session": {"accessToken": secrets[1], "cookie": secrets[2]},
    }
    entree_id = None
    async with AsyncSessionLocal() as db:
        entree = await record_audit_event(
            db, org_id, user_id, f"test.be227.ca4.{uuid.uuid4().hex[:8]}", "User", user_id, "Action BE227", changes=changes
        )
        entree_id = entree.id
        await db.commit()

    async with AsyncSessionLocal() as db:
        contenu = await db.scalar(text("SELECT (changes)::text FROM audit_event WHERE id = :id").bindparams(id=entree_id))
    for secret in secrets:
        assert secret not in contenu, "une valeur sensible ne doit jamais être stockée"
    assert json.loads(contenu)["nom"] == "valeur non sensible BE227"


# --- CA-5 : échec de stockage => échec de l'action ---------------------------------


async def test_be227_ca5_echec_de_stockage_fait_echouer_l_action(registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    identite = IdentiteEmettrice(user_id=user_id, organization_id=org_id)
    nom_avant = await _nom_de_l_organisation(org_id)
    nouveau_nom = f"Injection BE227 {uuid.uuid4().hex[:8]}"

    with patch("app.audit.ecriture.record_audit_event", side_effect=SQLAlchemyError("stockage indisponible")):
        with pytest.raises(ErreurCatalogue) as erreur:
            async with AsyncSessionLocal() as db:
                await executer_mutation_sensible(
                    db, identite, org_id, f"test.be227.ca5.{uuid.uuid4().hex[:8]}", "Organization", org_id,
                    "Renommage BE227", _renommer(org_id, nouveau_nom),
                )
                await db.commit()

    assert erreur.value.code == CodeErreur.AUDIT_WRITE_FAILED
    assert await _nom_de_l_organisation(org_id) == nom_avant, "pas d'action silencieuse : la mutation est annulée"
