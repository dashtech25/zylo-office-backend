"""BE-122 : journal d'audit append-only, lecture administrative.

Tests écrits d'après la définition `### BE-122` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Couverture :
- CA-1 : une écriture sans `correlationId` ou sans `action` est refusée (422),
  aucune ligne créée ;
- CA-2 (refus de droit) : un sujet hors autorité plateforme reçoit 403 sur
  `GET /api/v1/admin/audit-events` ;
- CA-3 : modification ou suppression refusée ; un événement correctif référence
  l'original ; entrée financière `billing.*` immuable en base (trigger BE-073) ;
- CA-4 (isolation tenant) : un auditeur sans affectation au tenant B ne reçoit
  aucun événement de B ;
- CA-5 : un champ secret ou PAN/CVV est rejeté (422) et n'apparaît dans aucune
  réponse.

Hors périmètre de ce fichier (voir QE dans app/audit/admin_audit.py) : immutabilité
des entrées non financières (PH-13 non décidé, QE-ADM-10) ; rôle auditeur distinct
(BE-121 absent : l'autorité plateforme BE-120 tient lieu de droit de lecture).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.audit.admin_audit import enregistrer_correction, ecrire_evenement_admin
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.audit.models import AuditEvent

CHEMIN_AUDIT = "/api/v1/admin/audit-events"
PAN_FICTIF = "4111111111111111"


def _entetes(utilisateur: dict, portee: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['accessToken']}"}
    if portee is not None:
        entetes["X-Admin-Scope"] = portee
    return entetes


async def _moi(client: AsyncClient, utilisateur: dict) -> str:
    return (await client.get("/api/v1/auth/me", headers=_entetes(utilisateur))).json()["id"]


async def _autre_organisation(client: AsyncClient) -> tuple[dict, str]:
    """Second tenant (B), créé par un autre compte : l'auditeur n'y est pas affecté."""
    email = f"be122-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    mot_de_passe = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": mot_de_passe, "fullName": "Tenant B"})
    login = (await client.post("/api/v1/auth/login", json={"email": email, "password": mot_de_passe})).json()
    proprietaire = {"accessToken": login["accessToken"]}
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"tenant-b-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(proprietaire),
    )
    return res.json(), await _moi(client, proprietaire)


async def _ecrire(organization_id: str, actor_id: str, action: str, correlation_id: str | None = "be122-corr",
                  changes: dict | None = None) -> AuditEvent:
    async with AsyncSessionLocal() as db:
        evenement = await ecrire_evenement_admin(
            db,
            organization_id=uuid.UUID(organization_id),
            actor_user_id=uuid.UUID(actor_id),
            action=action,
            entity_type="Intervention",
            entity_id=uuid.uuid4(),
            summary="Résumé de test BE-122",
            correlation_id=correlation_id,
            changes=changes,
        )
        await db.commit()
        return evenement


async def _nombre_d_entrees(action: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(text("SELECT count(*) FROM audit_event WHERE action = :action").bindparams(action=action)) or 0


async def test_be122_ca1_ecriture_sans_correlation_refusee_422(client: AsyncClient, registered_user: dict, organization: dict):
    acteur = await _moi(client, registered_user)
    action = "be122.ca1.sans_correlation"

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as info:
            await ecrire_evenement_admin(
                db,
                organization_id=uuid.UUID(organization["id"]),
                actor_user_id=uuid.UUID(acteur),
                action=action,
                entity_type="Intervention",
                entity_id=None,
                summary="sans correlation",
                correlation_id=None,
            )

    assert info.value.status_code == 422
    assert await _nombre_d_entrees(action) == 0


async def test_be122_ca1_ecriture_sans_action_refusee_422(client: AsyncClient, registered_user: dict, organization: dict):
    acteur = await _moi(client, registered_user)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as info:
            await ecrire_evenement_admin(
                db,
                organization_id=uuid.UUID(organization["id"]),
                actor_user_id=uuid.UUID(acteur),
                action="   ",
                entity_type="Intervention",
                entity_id=None,
                summary="sans action",
                correlation_id="be122-corr",
            )

    assert info.value.status_code == 422
    assert await _nombre_d_entrees("   ") == 0


async def test_be122_ca2_support_l2_recoit_403_sur_journal_admin(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    # Le support L2 n'a pas l'autorité plateforme : la liste d'exploitation ne le contient pas.
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(uuid.uuid4()))

    res = await client.get(CHEMIN_AUDIT, headers=_entetes(registered_user))

    assert res.status_code == 403


async def test_be122_ca3_modification_et_suppression_par_api_refusees(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", await _moi(client, registered_user))

    codes = [
        (await client.put(CHEMIN_AUDIT, headers=_entetes(registered_user), json={})).status_code,
        (await client.patch(CHEMIN_AUDIT, headers=_entetes(registered_user), json={})).status_code,
        (await client.delete(CHEMIN_AUDIT, headers=_entetes(registered_user))).status_code,
    ]

    assert codes == [405, 405, 405]


async def test_be122_ca3_evenement_correctif_reference_l_original(client: AsyncClient, registered_user: dict, organization: dict):
    acteur = await _moi(client, registered_user)
    original = await _ecrire(organization["id"], acteur, "be122.ca3.original")

    async with AsyncSessionLocal() as db:
        correctif = await enregistrer_correction(
            db,
            evenement_original=original,
            organization_id=uuid.UUID(organization["id"]),
            actor_user_id=uuid.UUID(acteur),
            correlation_id="be122-correctif",
            summary="Correction de l'entrée originale",
        )
        await db.commit()
        correctif_id = correctif.id

    async with AsyncSessionLocal() as db:
        relu_correctif = await db.get(AuditEvent, correctif_id)
        relu_original = await db.get(AuditEvent, original.id)

    assert relu_correctif.changes["corrigeEventId"] == original.eventId
    assert relu_original.summary == "Résumé de test BE-122"
    assert relu_original.action == "be122.ca3.original"


async def test_be122_ca3_entree_financiere_billing_immuable_en_base(client: AsyncClient, registered_user: dict, organization: dict):
    acteur = await _moi(client, registered_user)
    entree = await _ecrire(organization["id"], acteur, "billing.be122.immuable")

    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE audit_event SET summary = 'modifie' WHERE id = :id").bindparams(id=entree.id))
            await db.commit()
    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("DELETE FROM audit_event WHERE id = :id").bindparams(id=entree.id))
            await db.commit()


async def test_be122_ca4_auditeur_sans_affectation_tenant_b_ne_voit_aucun_evenement_de_b(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    auditeur = await _moi(client, registered_user)
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", auditeur)
    tenant_b, proprietaire_b = await _autre_organisation(client)
    evenement_b = await _ecrire(tenant_b["id"], proprietaire_b, "be122.ca4.tenant_b")

    res_b = await client.get(CHEMIN_AUDIT, headers=_entetes(registered_user, f"tenant:{tenant_b['id']}"))
    res_plateforme = await client.get(CHEMIN_AUDIT, headers=_entetes(registered_user))

    assert res_b.status_code == 403
    assert str(evenement_b.eventId) not in res_b.text
    assert res_plateforme.status_code == 200
    assert str(evenement_b.eventId) not in res_plateforme.text
    assert str(evenement_b.id) not in res_plateforme.text


async def test_be122_ca4_auditeur_affecte_voit_les_evenements_de_son_tenant(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    auditeur = await _moi(client, registered_user)
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", auditeur)
    evenement_a = await _ecrire(organization["id"], auditeur, "be122.ca4.tenant_a")

    res = await client.get(CHEMIN_AUDIT, headers=_entetes(registered_user, f"tenant:{organization['id']}"))

    assert res.status_code == 200
    ids = [ligne["id"] for ligne in res.json()["data"]]
    assert str(evenement_a.id) in ids


async def test_be122_ca5_champ_secret_ou_pan_cvv_rejete_422_et_absent_des_reponses(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    acteur = await _moi(client, registered_user)
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", acteur)

    for changes in ({"password": "motdepasse-secret"}, {"cvv": "123"}, {"pan": PAN_FICTIF}):
        async with AsyncSessionLocal() as db:
            with pytest.raises(AppError) as info:
                await ecrire_evenement_admin(
                    db,
                    organization_id=uuid.UUID(organization["id"]),
                    actor_user_id=uuid.UUID(acteur),
                    action="be122.ca5.refus",
                    entity_type="Paiement",
                    entity_id=None,
                    summary="champ interdit",
                    correlation_id="be122-corr",
                    changes=changes,
                )
        assert info.value.status_code == 422

    assert await _nombre_d_entrees("be122.ca5.refus") == 0
    res = await client.get(CHEMIN_AUDIT, headers=_entetes(registered_user, f"tenant:{organization['id']}"))
    assert "motdepasse-secret" not in res.text
    assert PAN_FICTIF not in res.text
