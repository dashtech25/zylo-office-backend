"""BE-073 : journal d'audit append-only des gestes financiers et sensibles.

Tests écrits d'après la définition `### BE-073` de
implementation-backend/tasks-abonnements-facturation.md, avant le code.

Couverture :
- CA-1 : chaque geste sensible écrit exactement une entrée avant/après dans
  `audit_event` (via `record_audit_entry`, qui s'appuie sur BE-007) ;
- CA-2 : un UPDATE ou un DELETE sur une entrée financière (action `billing.*`)
  est refusé par la base ; la trace originelle reste intacte ;
- CA-3 : une entrée du tenant A n'apparaît pas dans la lecture du tenant B ;
- CA-4 : un geste sensible sans `reason` est refusé, et aucune ligne n'est écrite.

Les noms de tables sont en snake_case (décision du coordinateur) ; la table
`subscription` appartient à BE-023 et n'est pas utilisée ici.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.billing.audit import GESTES_SENSIBLES, record_audit_entry
from app.billing.errors import BillingErrorCode
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.identity.models import User

ROUTE_JOURNAL = "/api/v1/organizations/current/audit-logs"
GESTE_SENSIBLE = "billing.plan.change"


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User).where(User.email == email))).scalar_one().id


async def _entrees(organization_id: str, action: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        lignes = (await db.execute(text(
            'SELECT id, "organizationId", action, "entityType", "entityId", scope_resource_type, '
            '"approvalId", reason, changes, summary FROM audit_event '
            'WHERE "organizationId" = :org AND action = :action'
        ).bindparams(org=uuid.UUID(organization_id), action=action))).mappings().all()
        return [dict(ligne) for ligne in lignes]


async def _ecrire_geste(organization_id: str, actor_id: uuid.UUID, *, action: str = GESTE_SENSIBLE, reason: str | None = "Changement demandé par le payeur", approver_id: uuid.UUID | None = None, scope: str = "payeur"):
    async with AsyncSessionLocal() as db:
        entree = await record_audit_entry(
            db,
            uuid.UUID(organization_id),
            actor_id,
            action=action,
            scope=scope,
            target_type="Subscription",
            target_id=uuid.uuid4(),
            before_json={"planCode": "essentiel"},
            after_json={"planCode": "premium"},
            summary="Changement de plan (test BE-073)",
            reason=reason,
            approver_id=approver_id,
        )
        await db.commit()
        return entree.id


# --- CA-1 : une entrée avant/après par geste sensible -----------------------------


async def test_be073_ca1_geste_sensible_ecrit_exactement_une_entree(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-1 : un geste sensible produit exactement une ligne, avec before, after,
    la cible, l'acteur, le motif et l'approbateur."""
    acteur = await _id_utilisateur(registered_user["email"])
    approbateur = uuid.uuid4()

    await _ecrire_geste(organization["id"], acteur, reason="Montée en gamme", approver_id=approbateur)

    lignes = await _entrees(organization["id"], GESTE_SENSIBLE)
    assert len(lignes) == 1, "exactement une entrée par geste"
    ligne = lignes[0]
    assert ligne["entityType"] == "Subscription"
    assert ligne["entityId"] is not None
    assert ligne["scope_resource_type"] == "payeur"
    assert ligne["reason"] == "Montée en gamme"
    assert ligne["approvalId"] == str(approbateur)
    assert ligne["changes"]["before"] == {"planCode": "essentiel"}
    assert ligne["changes"]["after"] == {"planCode": "premium"}


async def test_be073_ca1_geste_non_sensible_reste_accepte_sans_motif(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-1 : seul un geste de GESTES_SENSIBLES exige un motif ; une autre action journalisée passe."""
    acteur = await _id_utilisateur(registered_user["email"])
    assert "billing.invoice.create" not in GESTES_SENSIBLES

    await _ecrire_geste(organization["id"], acteur, action="billing.invoice.create", reason=None)

    assert len(await _entrees(organization["id"], "billing.invoice.create")) == 1


def test_be073_ca1_gestes_sensibles_couvrent_remboursement_changement_resiliation_facture():
    """CA-1 : la liste des gestes sensibles couvre approbation de remboursement,
    changement de plan, résiliation et finalisation de facture."""
    assert {"billing.refund.approve", "billing.plan.change", "billing.subscription.terminate", "billing.invoice.finalize"} <= GESTES_SENSIBLES


# --- CA-2 : append-only sur les entrées financières -------------------------------


async def test_be073_ca2_update_refuse_sur_entree_financiere(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-2 : un UPDATE d'une entrée financière est refusé par la base ; le résumé d'origine reste intact."""
    acteur = await _id_utilisateur(registered_user["email"])
    entree_id = await _ecrire_geste(organization["id"], acteur)

    with pytest.raises(DBAPIError):
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE audit_event SET summary = 'falsifié' WHERE id = :id").bindparams(id=entree_id))

    ligne = (await _entrees(organization["id"], GESTE_SENSIBLE))[0]
    assert ligne["summary"] == "Changement de plan (test BE-073)"


async def test_be073_ca2_delete_refuse_sur_entree_financiere(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-2 : un DELETE d'une entrée financière est refusé par la base ; la ligne reste présente."""
    acteur = await _id_utilisateur(registered_user["email"])
    entree_id = await _ecrire_geste(organization["id"], acteur)

    with pytest.raises(DBAPIError):
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM audit_event WHERE id = :id").bindparams(id=entree_id))

    assert len(await _entrees(organization["id"], GESTE_SENSIBLE)) == 1


# --- CA-3 : isolation tenant ------------------------------------------------------


async def test_be073_ca3_entree_du_tenant_a_absente_de_la_lecture_du_tenant_b(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-3 : une entrée financière du tenant A n'apparaît jamais dans la lecture du tenant B."""
    headers_a = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    autre = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B BE073", "slug": f"tenant-b-be073-{uuid.uuid4().hex[:8]}"},
        headers=headers_a,
    )
    assert autre.status_code == 201, autre.text
    tenant_b = autre.json()["id"]

    acteur = await _id_utilisateur(registered_user["email"])
    await _ecrire_geste(organization["id"], acteur, reason="Entrée réservée au tenant A")
    await _ecrire_geste(tenant_b, acteur, reason="Entrée réservée au tenant B")

    res = await client.get(ROUTE_JOURNAL, headers={**headers_a, "X-Organization-Id": tenant_b})

    assert res.status_code == 200, res.text
    motifs = [ligne["summary"] for ligne in res.json()["data"]]
    assert motifs.count("Changement de plan (test BE-073)") == 1
    async with AsyncSessionLocal() as db:
        total_b = await db.scalar(text('SELECT count(*) FROM audit_event WHERE "organizationId" = :org AND reason = :motif').bindparams(
            org=uuid.UUID(tenant_b), motif="Entrée réservée au tenant A"))
    assert total_b == 0


# --- CA-4 : motif obligatoire pour un geste sensible ------------------------------


@pytest.mark.parametrize("motif", [None, "", "   "])
async def test_be073_ca4_geste_sensible_sans_motif_refuse_sans_ligne(client: AsyncClient, registered_user: dict, organization: dict, motif):
    """CA-4 : un geste sensible sans motif (absent, vide ou blanc) lève APPROVAL_REQUIRED et n'écrit aucune ligne."""
    acteur = await _id_utilisateur(registered_user["email"])

    with pytest.raises(AppError) as erreur:
        await _ecrire_geste(organization["id"], acteur, reason=motif)

    assert erreur.value.code == BillingErrorCode.APPROVAL_REQUIRED.value
    assert await _entrees(organization["id"], GESTE_SENSIBLE) == []
