"""BE-007 : journal d'audit métier (écriture), table unique `audit_event`.

Tests écrits d'après la définition `### BE-007` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.

Couverture :
- table unique `audit_event` (l'ancienne `auditLog` n'existe plus) et colonnes
  ajoutées par la migration de renommage ;
- CA-1 : une mutation produit exactement une entrée ;
- CA-2 : chaque entrée porte le request ID de la requête ;
- CA-3 : écriture sans acteur ou sans organisation refusée, aucune ligne créée ;
- CA-4 : mot de passe, jetons et secrets jamais stockés dans une entrée ;
- CA-5 (isolation) : une entrée de O1 porte l'identifiant de O1 ;
- contraintes : `eventId` unique, `result` limité à success/refused/error.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.core.logging import request_id_ctx
from app.identity.models import User

COLONNES_BE007 = {
    "request_id",
    "result",
    "eventId",
    "actorType",
    "reason",
    "approvalId",
    "schemaVersion",
    "visibility",
    "dataClassification",
}


async def _colonnes_de_la_table() -> dict[str, str]:
    async with AsyncSessionLocal() as db:
        lignes = (await db.execute(text(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'audit_event'"
        ))).all()
    return {nom: nullable for nom, nullable in lignes}


async def _utilisateur_et_organisation(registered_user: dict, organization: dict) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        return user.id, uuid.UUID(organization["id"])


async def _nombre_d_entrees(organization_id: uuid.UUID, action: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(text(
            'SELECT count(*) FROM audit_event WHERE "organizationId" = :org AND action = :action'
        ).bindparams(org=organization_id, action=action)) or 0


async def test_be007_table_unique_audit_event_et_auditlog_absente(client: AsyncClient):
    colonnes = await _colonnes_de_la_table()
    assert colonnes, "la table audit_event doit exister après migration"

    async with AsyncSessionLocal() as db:
        ancienne = await db.scalar(text(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'auditLog'"
        ))
    assert ancienne == 0, "la table auditLog doit être renommée, jamais dupliquée"


async def test_be007_colonnes_ajoutees_par_la_migration_presentes(client: AsyncClient):
    colonnes = await _colonnes_de_la_table()
    manquantes = COLONNES_BE007 - set(colonnes)
    assert not manquantes, f"colonnes absentes : {sorted(manquantes)}"
    assert colonnes["request_id"] == "NO", "request_id est obligatoire"
    assert colonnes["eventId"] == "NO", "eventId est obligatoire"
    assert colonnes["organizationId"] == "YES", "organizationId devient nullable (portée plateforme)"


async def test_be007_ca1_une_mutation_produit_exactement_une_entree(client: AsyncClient, registered_user: dict, organization: dict):
    from app.audit.service import record_audit_event

    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be007.ca1.{uuid.uuid4().hex[:8]}"
    request_id_ctx.set("req-be007-ca1")

    async with AsyncSessionLocal() as db:
        await record_audit_event(db, org_id, user_id, action, "Test", None, "Mutation de test")
        await db.commit()

    assert await _nombre_d_entrees(org_id, action) == 1


async def test_be007_ca2_chaque_entree_porte_le_request_id_de_la_requete(client: AsyncClient, registered_user: dict, organization: dict):
    from app.audit.service import record_audit_event

    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be007.ca2.{uuid.uuid4().hex[:8]}"
    request_id_ctx.set("req-be007-ca2")

    async with AsyncSessionLocal() as db:
        await record_audit_event(db, org_id, user_id, action, "Test", None, "Résumé")
        await db.commit()
        ligne = (await db.execute(text(
            "SELECT request_id, \"eventId\", result FROM audit_event WHERE action = :a"
        ).bindparams(a=action))).one()

    assert ligne.request_id == "req-be007-ca2"
    assert ligne.eventId and ligne.result == "success"


async def test_be007_ca3_ecriture_sans_acteur_refusee_sans_ligne(client: AsyncClient, registered_user: dict, organization: dict):
    from app.audit.service import record_audit_event

    _, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be007.ca3a.{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError):
            await record_audit_event(db, org_id, None, action, "Test", None, "Sans acteur")
        await db.rollback()

    assert await _nombre_d_entrees(org_id, action) == 0


async def test_be007_ca3_ecriture_sans_organisation_refusee_sans_ligne(client: AsyncClient, registered_user: dict, organization: dict):
    from app.audit.service import record_audit_event

    user_id, _ = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be007.ca3b.{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError):
            await record_audit_event(db, None, user_id, action, "Test", None, "Sans organisation")
        await db.rollback()

    async with AsyncSessionLocal() as db:
        total = await db.scalar(text("SELECT count(*) FROM audit_event WHERE action = :a").bindparams(a=action))
    assert total == 0


async def test_be007_ca4_mot_de_passe_et_jetons_jamais_stockes(client: AsyncClient, registered_user: dict, organization: dict):
    from app.audit.service import record_audit_event

    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be007.ca4.{uuid.uuid4().hex[:8]}"
    secret = "Secret-BE007-" + uuid.uuid4().hex
    request_id_ctx.set("req-be007-ca4")

    async with AsyncSessionLocal() as db:
        await record_audit_event(
            db, org_id, user_id, action, "Test", None,
            "Changement de mot de passe",
            changes={"password": secret, "newPassword": secret, "accessToken": secret, "nom": "visible"},
        )
        await db.commit()
        brut = (await db.execute(text("SELECT changes::text FROM audit_event WHERE action = :a").bindparams(a=action))).scalar_one()

    assert secret not in brut, "un secret ne doit jamais être stocké dans une entrée d'audit"
    assert "visible" in brut, "les champs non sensibles restent journalisés"


async def test_be007_ca5_entree_porte_l_organisation_de_son_auteur(client: AsyncClient, registered_user: dict, organization: dict):
    from app.audit.service import record_audit_event

    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    autre_org = uuid.uuid4()
    action = f"test.be007.ca5.{uuid.uuid4().hex[:8]}"
    request_id_ctx.set("req-be007-ca5")

    async with AsyncSessionLocal() as db:
        await record_audit_event(db, org_id, user_id, action, "Test", None, "Isolation")
        await db.commit()
        org_ligne = await db.scalar(text("SELECT \"organizationId\" FROM audit_event WHERE action = :a").bindparams(a=action))
        autre = await db.scalar(text(
            "SELECT count(*) FROM audit_event WHERE action = :a AND \"organizationId\" = :o"
        ).bindparams(a=action, o=autre_org))

    assert org_ligne == org_id
    assert autre == 0


async def test_be007_eventid_unique_par_entree(client: AsyncClient, registered_user: dict, organization: dict):
    from app.audit.service import record_audit_event

    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be007.event.{uuid.uuid4().hex[:8]}"
    request_id_ctx.set("req-be007-event")

    async with AsyncSessionLocal() as db:
        premier = await record_audit_event(db, org_id, user_id, action, "Test", None, "Un")
        second = await record_audit_event(db, org_id, user_id, action, "Test", None, "Deux")
        await db.commit()

    assert premier.eventId and second.eventId and premier.eventId != second.eventId


async def test_be007_result_limite_a_success_refused_error(client: AsyncClient, registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)

    async with AsyncSessionLocal() as db:
        with pytest.raises(IntegrityError):
            await db.execute(text(
                "INSERT INTO audit_event (id, \"organizationId\", \"actorUserId\", action, \"entityType\", summary, "
                "request_id, result, \"eventId\", \"createdAt\", \"schemaVersion\", \"actorType\") "
                "VALUES (gen_random_uuid(), :o, :u, 'test.be007.result', 'Test', 'x', 'req', 'inconnu', :e, now(), 1, 'humain')"
            ).bindparams(o=org_id, u=user_id, e=uuid.uuid4().hex))
        await db.rollback()
