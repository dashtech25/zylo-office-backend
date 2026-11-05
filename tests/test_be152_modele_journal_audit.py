"""BE-152 : modèle du journal d'audit append-only (table unique `audit_event`).

Tests écrits d'après la définition `### BE-152` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.
Les noms de colonnes suivent la règle de la définition : ceux de `audit_event`
(BE-007) quand ils existent (QE-PAR-26). Correspondance utilisée ici :
- `tenantId` -> `organizationId` ; `actor` -> `actorUserId` ;
- `targetType` / `targetId` -> `entityType` / `entityId` ;
- `occurredAt` -> `createdAt` ; `correlationId` -> `request_id`.

Couverture :
- CA-1 : colonnes clés présentes, `eventId` unique, aucune seconde table d'audit ;
- CA-2 : UPDATE et DELETE sur `audit_event` refusés par la base (trigger) ;
- CA-3 : ligne sans acteur, cible, action ou corrélation refusée par la base ;
- CA-4 : isolation tenant, lecture directe scopée à un autre tenant.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.audit.models import AuditEvent
from app.audit.service import record_audit_event
from app.core.database import AsyncSessionLocal
from app.core.logging import request_id_ctx
from app.identity.models import User

# Colonnes clés attendues par BE-152, sous les noms retenus (voir docstring).
COLONNES_CLES_BE152 = {
    "id",
    "eventId",
    "organizationId",
    "actorUserId",
    "entityType",
    "entityId",
    "action",
    "reason",
    "createdAt",
    "result",
    "request_id",
    "visibility",
    "dataClassification",
}


async def _utilisateur_et_organisation(registered_user: dict, organization: dict) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        return user.id, uuid.UUID(organization["id"])


async def _ecrire_entree(user_id: uuid.UUID, org_id: uuid.UUID, action: str, resume: str) -> None:
    request_id_ctx.set(f"req-{action}")
    async with AsyncSessionLocal() as db:
        await record_audit_event(db, org_id, user_id, action, "Test", None, resume)
        await db.commit()


async def test_be152_ca1_colonnes_cles_presentes(client: AsyncClient):
    async with AsyncSessionLocal() as db:
        colonnes = {
            nom: nullable
            for nom, nullable in (await db.execute(text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'audit_event'"
            ))).all()
        }
    manquantes = COLONNES_CLES_BE152 - set(colonnes)
    assert not manquantes, f"colonnes absentes de audit_event : {sorted(manquantes)}"


async def test_be152_ca1_event_id_unique_en_base(client: AsyncClient):
    async with AsyncSessionLocal() as db:
        uniques = (await db.execute(text(
            "SELECT i.indexdef FROM pg_indexes i "
            "WHERE i.schemaname = 'public' AND i.tablename = 'audit_event' AND i.indexdef ILIKE 'CREATE UNIQUE%'"
        ))).scalars().all()
        contraintes = (await db.execute(text(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = 'audit_event' AND c.contype = 'u'"
        ))).scalars().all()
    assert any('"eventId"' in definition for definition in uniques + contraintes), "eventId doit être unique en base"


async def test_be152_ca1_aucune_seconde_table_d_audit(client: AsyncClient):
    async with AsyncSessionLocal() as db:
        tables = set((await db.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name ILIKE '%audit%'"
        ))).scalars().all())
    assert tables == {"audit_event"}, f"tables d'audit inattendues : {sorted(tables)}"


async def test_be152_ca2_update_sur_audit_event_refuse(client: AsyncClient, registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be152.ca2.update.{uuid.uuid4().hex[:8]}"
    await _ecrire_entree(user_id, org_id, action, "Résumé original")

    with pytest.raises(DBAPIError):
        async with AsyncSessionLocal() as db:
            await db.execute(text("UPDATE audit_event SET summary = 'modifié' WHERE action = :a").bindparams(a=action))
            await db.commit()

    async with AsyncSessionLocal() as db:
        resume = await db.scalar(text("SELECT summary FROM audit_event WHERE action = :a").bindparams(a=action))
    assert resume == "Résumé original", "une entrée d'audit ne doit jamais être modifiée"


async def test_be152_ca2_delete_sur_audit_event_refuse(client: AsyncClient, registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    action = f"test.be152.ca2.delete.{uuid.uuid4().hex[:8]}"
    await _ecrire_entree(user_id, org_id, action, "Entrée à conserver")

    with pytest.raises(DBAPIError):
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM audit_event WHERE action = :a").bindparams(a=action))
            await db.commit()

    async with AsyncSessionLocal() as db:
        total = await db.scalar(text("SELECT count(*) FROM audit_event WHERE action = :a").bindparams(a=action))
    assert total == 1, "une entrée d'audit ne doit jamais être supprimée"


async def _tenter_insertion(**champs) -> None:
    valeurs = {
        "organizationId": None,
        "actorUserId": None,
        "action": "test.be152.ca3",
        "entityType": "Test",
        "entityId": None,
        "summary": "Résumé",
        "request_id": "req-be152-ca3",
        "eventId": str(uuid.uuid4()),
        "actorType": "humain",
        "schemaVersion": 1,
        "result": "success",
    }
    valeurs.update(champs)
    async with AsyncSessionLocal() as db:
        db.add(AuditEvent(**valeurs))
        await db.flush()
        await db.rollback()


async def test_be152_ca3_ligne_sans_acteur_refusee(client: AsyncClient, registered_user: dict, organization: dict):
    _, org_id = await _utilisateur_et_organisation(registered_user, organization)
    with pytest.raises(IntegrityError):
        await _tenter_insertion(organizationId=org_id, actorUserId=None)


async def test_be152_ca3_ligne_sans_action_refusee(client: AsyncClient, registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    with pytest.raises(IntegrityError):
        await _tenter_insertion(organizationId=org_id, actorUserId=user_id, action="   ")


async def test_be152_ca3_ligne_sans_cible_refusee(client: AsyncClient, registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    with pytest.raises(IntegrityError):
        await _tenter_insertion(organizationId=org_id, actorUserId=user_id, entityType="")


async def test_be152_ca3_ligne_sans_correlation_refusee(client: AsyncClient, registered_user: dict, organization: dict):
    user_id, org_id = await _utilisateur_et_organisation(registered_user, organization)
    with pytest.raises(IntegrityError):
        await _tenter_insertion(organizationId=org_id, actorUserId=user_id, request_id=None)
    with pytest.raises(IntegrityError):
        await _tenter_insertion(organizationId=org_id, actorUserId=user_id, request_id="")


async def test_be152_ca4_isolation_tenant_requete_directe(client: AsyncClient, registered_user: dict, organization: dict):
    user_id, org_a = await _utilisateur_et_organisation(registered_user, organization)
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Autre Org", "slug": f"autre-org-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    assert res.status_code in (200, 201), res.text
    org_b = uuid.UUID(res.json()["id"])

    action = f"test.be152.ca4.{uuid.uuid4().hex[:8]}"
    await _ecrire_entree(user_id, org_a, action, "Entrée du tenant A")

    async with AsyncSessionLocal() as db:
        vu_par_a = await db.scalar(text(
            'SELECT count(*) FROM audit_event WHERE action = :a AND "organizationId" = :o'
        ).bindparams(a=action, o=org_a))
        vu_par_b = await db.scalar(text(
            'SELECT count(*) FROM audit_event WHERE action = :a AND "organizationId" = :o'
        ).bindparams(a=action, o=org_b))
    assert vu_par_a == 1
    assert vu_par_b == 0, "une entrée du tenant A ne doit pas être visible par une requête scopée au tenant B"
