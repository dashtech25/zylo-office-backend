"""BE-260 : journal d'audit des actions sensibles.

Tests écrits d'après la définition `### BE-260` de
implementation-backend/tasks-fondation-recensement.md, avant le code.

Périmètre : aucune table créée ; la table unique `audit_event` (BE-007) est
consommée. Route cible de lecture : `GET /api/v1/organizations/{organization_id}/audit`
(nommage recommandé, NON DÉFINI dans les sources, QE-FON-16). Fonction d'écriture
attendue : `app.audit.service.record_sensitive_action`, qui exige une justification.

Couverture :
- CA-1 : une action sensible crée exactement une ligne `audit_event`, dans la
  même transaction que l'action (annulée avec elle) ;
- CA-2 : une action sensible sans justification est refusée (422) sans ligne ;
- CA-3 : `GET .../audit` sans `audit.log.view` renvoie 403 ;
- CA-4 : un utilisateur de l'organisation B ne lit pas l'organisation A ;
- CA-5 : UPDATE et DELETE sur `audit_event` échouent.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.audit.service import record_audit_event
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import OrganizationUser, User
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"


def _route_audit(organization_id: str) -> str:
    return f"/api/v1/organizations/{organization_id}/audit"


async def _utilisateur_et_organisation(registered_user: dict, organization: dict) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        return user.id, uuid.UUID(organization["id"])


async def _nombre_d_entrees(organization_id: uuid.UUID, action: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(text(
            'SELECT count(*) FROM audit_event WHERE "organizationId" = :org AND action = :action'
        ).bindparams(org=organization_id, action=action)) or 0


async def _nom_de_l_organisation(organization_id: uuid.UUID) -> str:
    async with AsyncSessionLocal() as db:
        return await db.scalar(text("SELECT name FROM organization WHERE id = :id").bindparams(id=organization_id))


async def _enregistrer_entree_test(organization_id: uuid.UUID, actor_user_id: uuid.UUID, action: str, summary: str) -> uuid.UUID:
    """Écrit une entrée via le service existant et renvoie son identifiant."""
    async with AsyncSessionLocal() as db:
        entree = await record_audit_event(db, organization_id, actor_user_id, action, "TestBe260", None, summary)
        await db.commit()
        return entree.id


async def _nouvel_utilisateur_avec_organisation(client: AsyncClient) -> dict:
    """Crée un utilisateur qui est propriétaire d'une organisation qui lui est propre."""
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Autre Membre"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Organisation B BE260", "slug": f"org-b-be260-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201, res.text
    return {"email": email, "accessToken": token, "organizationId": res.json()["id"]}


# --- CA-1 : une ligne, dans la transaction de l'action ----------------------------


async def test_be260_ca1_action_sensible_cree_exactement_une_ligne(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-1 : une action sensible (changement réel du nom d'organisation) et son
    audit, dans une même transaction, produisent exactement une ligne `audit_event`."""
    from app.audit.service import record_sensitive_action

    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be260.ca1.{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE organization SET name = :nom WHERE id = :id").bindparams(nom="Nom BE260 CA1", id=org_id))
        await record_sensitive_action(
            db, org_id, user_id, action, "Organization", org_id, "Renommage de l'organisation (BE260)",
            justification="Test BE260 CA-1",
        )
        await db.commit()

    assert await _nombre_d_entrees(org_id, action) == 1


async def test_be260_ca1_echec_de_l_action_annule_aussi_l_audit(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-1 (réciproque) : si l'action échoue et la transaction est annulée, il
    n'existe ni modification de l'action ni ligne d'audit."""
    from app.audit.service import record_sensitive_action

    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be260.ca1b.{uuid.uuid4().hex[:8]}"
    nom_initial = await _nom_de_l_organisation(org_id)

    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text("UPDATE organization SET name = :nom WHERE id = :id").bindparams(nom="Nom BE260 annulé", id=org_id))
            await record_sensitive_action(
                db, org_id, user_id, action, "Organization", org_id, "Renommage annulé (BE260)",
                justification="Test BE260 CA-1 réciproque",
            )
            raise RuntimeError("échec simulé de l'action")
        except RuntimeError:
            await db.rollback()

    assert await _nombre_d_entrees(org_id, action) == 0
    assert await _nom_de_l_organisation(org_id) == nom_initial


# --- CA-2 : justification obligatoire --------------------------------------------


@pytest.mark.parametrize("justification", [None, "", "   "])
async def test_be260_ca2_sans_justification_refus_422_sans_ligne(
    client: AsyncClient, registered_user: dict, organization: dict, justification: str | None
):
    """CA-2 : sans justification (absente, vide ou blanche), l'action sensible est
    refusée en 422 et aucune ligne `audit_event` n'est créée."""
    from app.audit.service import record_sensitive_action

    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be260.ca2.{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await record_sensitive_action(
                db, org_id, user_id, action, "Organization", org_id, "Action sans justification (BE260)",
                justification=justification,
            )

    assert erreur.value.status_code == 422
    assert erreur.value.code == "justification_requise"
    assert await _nombre_d_entrees(org_id, action) == 0


async def test_be260_ca2_avec_justification_la_justification_est_conservee(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 (complément) : avec une justification, la ligne est écrite et porte la
    justification fournie (colonne `reason` de BE-007, QE-FON-15)."""
    from app.audit.service import record_sensitive_action

    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be260.ca2b.{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        await record_sensitive_action(
            db, org_id, user_id, action, "Organization", org_id, "Action justifiée (BE260)",
            justification="Motif BE260 explicite",
        )
        await db.commit()
        motif = await db.scalar(text("SELECT reason FROM audit_event WHERE action = :a").bindparams(a=action))

    assert await _nombre_d_entrees(org_id, action) == 1
    assert motif == "Motif BE260 explicite"


# --- CA-3 : refus de lecture sans audit.log.view ----------------------------------


async def test_be260_ca3_lecture_sans_permission_renvoie_403(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-3 : un membre de l'organisation sans `audit.log.view` reçoit 403."""
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Membre Simple"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        membre = (await db.execute(select(User).where(User.email == email))).scalar_one()
        db.add(OrganizationUser(organizationId=uuid.UUID(organization["id"]), userId=membre.id))
        await db.commit()

    headers = {"Authorization": f"Bearer {login.json()['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get(_route_audit(organization["id"]), headers=headers)

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "permission_denied"


async def test_be260_ca3_lecture_par_le_proprietaire_renvoie_les_entrees(client: AsyncClient, registered_user: dict, organization: dict):
    """Complément CA-3 : le propriétaire (porteur de `audit.log.view`) obtient 200
    et voit l'entrée écrite pour son organisation."""
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be260.lecture.{uuid.uuid4().hex[:8]}"
    await _enregistrer_entree_test(org_id, user_id, action, "Entrée lue BE260")
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}

    res = await client.get(_route_audit(organization["id"]), headers=headers)

    assert res.status_code == 200, res.text
    assert any(ligne["summary"] == "Entrée lue BE260" for ligne in res.json()["data"])


# --- CA-4 : isolation entre organisations -------------------------------------------


async def test_be260_ca4_membre_de_b_ne_lit_pas_l_organisation_a(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-4 : un utilisateur de l'organisation B qui appelle
    `GET /api/v1/organizations/{A}/audit` reçoit 404 et aucune ligne de A.

    Décision T-010 : hors portée = 404 (QE-FON-19)."""
    user_a, org_a = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be260.ca4.{uuid.uuid4().hex[:8]}"
    await _enregistrer_entree_test(org_a, user_a, action, "Entrée confidentielle de A BE260")
    autre = await _nouvel_utilisateur_avec_organisation(client)

    res = await client.get(
        _route_audit(organization["id"]),
        headers={"Authorization": f"Bearer {autre['accessToken']}"},
    )

    assert res.status_code == 404, res.text
    assert "Entrée confidentielle de A BE260" not in res.text


# --- CA-5 : immuabilité d'audit_event --------------------------------------------------


async def test_be260_ca5_update_sur_audit_event_echoue(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-5 : une tentative de UPDATE sur une ligne `audit_event` échoue et la
    ligne reste inchangée (contrainte ou trigger)."""
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    entree_id = await _enregistrer_entree_test(org_id, user_id, f"test.be260.ca5u.{uuid.uuid4().hex[:8]}", "Résumé original BE260")

    with pytest.raises(DBAPIError):
        async with AsyncSessionLocal() as db:
            await db.execute(text("UPDATE audit_event SET summary = 'modifié BE260' WHERE id = :id").bindparams(id=entree_id))
            await db.commit()

    async with AsyncSessionLocal() as db:
        resume = await db.scalar(text("SELECT summary FROM audit_event WHERE id = :id").bindparams(id=entree_id))
    assert resume == "Résumé original BE260"


async def test_be260_ca5_delete_sur_audit_event_echoue(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-5 : une tentative de DELETE sur une ligne `audit_event` échoue et la
    ligne existe toujours (contrainte ou trigger)."""
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    entree_id = await _enregistrer_entree_test(org_id, user_id, f"test.be260.ca5d.{uuid.uuid4().hex[:8]}", "Résumé à garder BE260")

    with pytest.raises(DBAPIError):
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM audit_event WHERE id = :id").bindparams(id=entree_id))
            await db.commit()

    async with AsyncSessionLocal() as db:
        restant = await db.scalar(text("SELECT count(*) FROM audit_event WHERE id = :id").bindparams(id=entree_id))
    assert restant == 1
