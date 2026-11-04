"""BE-023 : plans, versions de plan et abonnement (modèle et migrations).

Intention : prouver par des tests les critères d'acceptation de BE-023
(implementation-backend/tasks-socle-tenant-identite.md, section BE-023) :
- CA-1 : la migration c0b7d9a2e511 remplit `invoice.amountMinor` depuis
  `invoice.amountCents` sans perte (test sur la base de test jetable) ;
- CA-2 : upgrade puis downgrade jusqu'à d8e9f0a1b2c3 réussissent, et la
  chaîne Alembic n'a qu'une seule tête ;
- CA-3 (isolation) : un abonnement de l'organisation O1 n'est jamais lu
  depuis l'organisation O2 ;
- CA-4 (refus) : un abonnement sans organisation est refusé à l'écriture.

Les noms de tables suivent les migrations existantes (camelCase : `planVersion`,
`subscriptionEntitlement`) ; la définition écrit `plan_version`, la convention
du dépôt prime. La table `subscription` est créée ici (BE-023) et seulement
utilisée ailleurs.

La base de test est celle de tests/conftest.py (zylo_t<NNN>_test). Les tests de
migration rétrogradent puis remontent le schéma : ils restaurent la tête à la fin.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.billing import service
from app.billing.models import Subscription
from app.core import migrations
from app.core.database import AsyncSessionLocal, engine
from app.core.migrations import config_alembic, revisions_attendues
from app.identity.models import Organization

REVISION_AVANT_C0B7 = "d0c526c8656e"
REVISION_C0B7 = "c0b7d9a2e511"
REVISION_D8E9 = "d8e9f0a1b2c3"


def _tete_unique() -> str:
    tetes = migrations.script_directory().get_heads()
    assert len(tetes) == 1, f"plusieurs têtes Alembic : {tetes}"
    return tetes[0]


async def _execute(sql: str, parametres: dict | None = None) -> list:
    async with engine.begin() as conn:
        resultat = await conn.execute(text(sql), parametres or {})
        return list(resultat.fetchall()) if resultat.returns_rows else []


# --- CA-1 : remplissage sans perte de amountMinor -------------------------------------


@pytest.mark.asyncio
async def test_ca1_migration_c0b7_remplit_amount_minor_sans_perte():
    """CA-1 : les montants legacy `amountCents` sont recopiés à l'identique dans `amountMinor`."""
    cfg = config_alembic()
    command.downgrade(cfg, REVISION_AVANT_C0B7)
    try:
        org_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        sub_id = uuid.uuid4()
        montants = [0, 1, 2500, 999_999_999_999]
        await _execute(
            'INSERT INTO organization (id, name, slug, status, "createdAt", "updatedAt") '
            "VALUES (:id, 'Org CA1', :slug, 'active', now(), now())",
            {"id": org_id, "slug": f"ca1-{org_id.hex[:8]}"},
        )
        await _execute(
            'INSERT INTO plan (id, "moduleCode", code, name, "priceCents", currency, "periodDays", "createdAt", "updatedAt") '
            "VALUES (:id, 'zylo_liquid', :code, 'Plan CA1', 0, 'XAF', 30, now(), now())",
            {"id": plan_id, "code": f"ca1-{plan_id.hex[:8]}"},
        )
        await _execute(
            'INSERT INTO subscription (id, "organizationId", "planId", status, "startDate", "endDate", version, "createdAt", "updatedAt") '
            "VALUES (:id, :org, :plan, 'trial', now(), now() + interval '30 days', 1, now(), now())",
            {"id": sub_id, "org": org_id, "plan": plan_id},
        )
        for montant in montants:
            await _execute(
                'INSERT INTO invoice (id, "subscriptionId", "amountCents", currency, status, "issuedAt", version, "createdAt", "updatedAt") '
                "VALUES (:id, :sub, :montant, 'XAF', 'pending', now(), 1, now(), now())",
                {"id": uuid.uuid4(), "sub": sub_id, "montant": montant},
            )

        command.upgrade(cfg, REVISION_C0B7)

        lignes = await _execute(
            'SELECT "amountCents", "amountMinor" FROM invoice WHERE "subscriptionId" = :sub',
            {"sub": sub_id},
        )
        assert sorted((int(c), int(m)) for c, m in lignes) == sorted((m, m) for m in montants)
    finally:
        command.upgrade(cfg, "head")


# --- CA-2 : aller-retour de migrations et tête unique ---------------------------------


def test_ca2_chaine_a_une_seule_tete():
    """CA-2 : une seule tête Alembic dans le dépôt."""
    assert len(migrations.script_directory().get_heads()) == 1


def test_ca2_upgrade_puis_downgrade_jusqu_a_d8e9_puis_retour_tete():
    """CA-2 : downgrade jusqu'à d8e9f0a1b2c3 puis upgrade de retour à la tête réussissent."""
    cfg = config_alembic()
    tete = _tete_unique()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, REVISION_D8E9)
    command.upgrade(cfg, "head")
    assert revisions_attendues() == {tete}


# --- CA-3 : isolation des abonnements entre organisations -----------------------------


@pytest.mark.asyncio
async def test_ca3_abonnement_de_o1_jamais_lisible_depuis_o2():
    """CA-3 : le dépôt d'abonnement filtre par organisation ; O2 ne voit pas l'abonnement de O1."""
    code_plan = f"ca3-{uuid.uuid4().hex[:8]}"
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(db, "zylo_liquid", code_plan, "Plan CA3", 1000, "XAF", 30)
        o1 = Organization(name="Org O1", slug=f"o1-{uuid.uuid4().hex[:8]}", status="active")
        o2 = Organization(name="Org O2", slug=f"o2-{uuid.uuid4().hex[:8]}", status="active")
        db.add_all([o1, o2])
        await db.flush()
        abonnement = Subscription(
            organizationId=o1.id, planId=plan.id, status="active",
            startDate=maintenant, endDate=maintenant + timedelta(days=30),
        )
        db.add(abonnement)
        await db.commit()

        o1_id, o2_id, abonnement_id = o1.id, o2.id, abonnement.id

    async with AsyncSessionLocal() as db:
        vu_par_o1 = await service.current_subscription(db, o1_id)
        assert vu_par_o1 is not None and vu_par_o1[0].id == abonnement_id
        assert await service.current_subscription(db, o2_id) is None
        from sqlalchemy import select
        lignes_o2 = (await db.scalars(select(Subscription).where(Subscription.organizationId == o2_id))).all()
        assert lignes_o2 == []


# --- CA-4 : refus d'un abonnement sans organisation -----------------------------------


@pytest.mark.asyncio
async def test_ca4_abonnement_sans_organisation_refuse_a_l_ecriture():
    """CA-4 : organizationId est NOT NULL ; l'écriture d'un abonnement orphelin échoue."""
    assert Subscription.__table__.c.organizationId.nullable is False
    code_plan = f"ca4-{uuid.uuid4().hex[:8]}"
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(db, "zylo_liquid", code_plan, "Plan CA4", 1000, "XAF", 30)
        db.add(Subscription(
            organizationId=None, planId=plan.id, status="trial",
            startDate=maintenant, endDate=maintenant + timedelta(days=30),
        ))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
