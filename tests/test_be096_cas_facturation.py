"""BE-096 : cas de facturation et d'assistance (billing case).

Intention : prouver les critères d'acceptation de BE-096
(implementation-backend/tasks-abonnements-facturation.md, section BE-096) :
- CA-1 : un cas `open` ou `assigned` n'empêche pas la clôture d'un abonnement et ne se
  ferme jamais en cascade (test de non-cascade) ;
- CA-2 : un cas ne peut être `resolved` sans motif et sans entrée d'audit (BE-073) ;
- CA-3 : sans permission d'action sensible, `FORBIDDEN` ; pas d'impersonation (test de routage) ;
- CA-4 : un cas d'un tenant n'est pas visible depuis un autre scope.

Routes testées : `POST /api/v1/billing/cases` et `POST /api/v1/billing/cases/{case_id}/resolve`.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.audit.models import AuditEvent
from app.billing import service
from app.billing.close.service import demander_cloture
from app.billing.models import Subscription
from app.billing.permissions import BILLING_CASE_OPEN, BILLING_CASE_RESOLVE
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser, User
from app.rbac.models import Permission, Role, RolePermission

ACTION_AUDIT_OUVERTURE = "billing.case.open"
ACTION_AUDIT_RESOLUTION = "billing.case.resolve"
ROUTE_CAS = "/api/v1/billing/cases"


@pytest.fixture(autouse=True)
async def _pool_propre():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


def _entete(token: str, organization_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def _inscrire_et_connecter(client, email: str) -> str:
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Membre"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return login.json()["accessToken"]


async def _ajouter_membre_sans_droit(organization_id: str, email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        utilisateur = await db.scalar(select(User).where(User.email == email))
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=utilisateur.id))
        await db.commit()
        return utilisateur.id


async def _identifiant_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.scalar(select(User).where(User.email == email))).id


async def _creer_autre_tenant(client) -> str:
    """Un second tenant (organisation) dont l'utilisateur est propriétaire."""
    email = f"be096-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token = await _inscrire_et_connecter(client, email)
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": "Autre Org", "slug": f"be096-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return reponse.json()["id"], token


async def _retirer_permission_au_proprietaire(organization_id: str, code: str) -> None:
    """Retire une permission du rôle `owner` de l'organisation (cas sans permission sensible)."""
    async with AsyncSessionLocal() as db:
        role = await db.scalar(
            select(Role).where(Role.organizationId == uuid.UUID(organization_id), Role.code == "owner")
        )
        permission = await db.scalar(select(Permission).where(Permission.code == code))
        await db.execute(
            delete(RolePermission).where(
                RolePermission.roleId == role.id, RolePermission.permissionId == permission.id
            )
        )
        await db.commit()


async def _creer_abonnement(tenant_id: uuid.UUID, lifecycle: str = "cancelled") -> uuid.UUID:
    """Abonnement du tenant, finances réglées, aucun incident."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be096-{uuid.uuid4().hex[:8]}", "Plan BE-096", 1000, "XAF", 30
        )
        abonnement = Subscription(
            organizationId=tenant_id,
            planId=plan.id,
            status="active",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
            beneficiaryTenantId=tenant_id,
            lifecycleStatus=lifecycle,
            financialStatus="settled",
            incidentStatus="none",
        )
        db.add(abonnement)
        await db.commit()
        return abonnement.id


async def _lire_abonnement(subscription_id: uuid.UUID) -> Subscription:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Subscription).where(Subscription.id == subscription_id))


async def _ajouter_synchronisation_appliquee(subscription_id: uuid.UUID) -> None:
    """Droits PH-09 confirmés : prérequis « droits » de la clôture satisfait (BE-085)."""
    from app.billing.models import EntitlementSync

    async with AsyncSessionLocal() as db:
        db.add(
            EntitlementSync(
                subscriptionId=subscription_id,
                status="applied",
                attempts=1,
                lastErrorCode=None,
                requestedAt=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def _lire_cas(case_id: str):
    from app.billing.models import BillingCase

    async with AsyncSessionLocal() as db:
        return await db.scalar(select(BillingCase).where(BillingCase.id == uuid.UUID(case_id)))


async def _cas_par_sujet(subject_ref: str) -> list:
    from app.billing.models import BillingCase

    async with AsyncSessionLocal() as db:
        return list(await db.scalars(select(BillingCase).where(BillingCase.subjectRef == subject_ref)))


async def _creer_cas_direct(tenant_id: uuid.UUID, subject_ref: str, statut: str) -> uuid.UUID:
    """Cas posé directement au statut donné, pour les tests de transition et de clôture."""
    from app.billing.models import BillingCase

    async with AsyncSessionLocal() as db:
        cas = BillingCase(
            organizationId=tenant_id,
            scope="tenant",
            subjectRef=subject_ref,
            status=statut,
            reason="Cas posé par le test",
            openedAt=datetime.now(timezone.utc),
        )
        db.add(cas)
        await db.commit()
        return cas.id


async def _entrees_audit(action: str, entite_id: str) -> list[AuditEvent]:
    async with AsyncSessionLocal() as db:
        resultat = await db.scalars(
            select(AuditEvent).where(AuditEvent.entityId == uuid.UUID(entite_id), AuditEvent.action == action)
        )
        return list(resultat)


async def _ouvrir_cas(client, token: str, organization_id: str, subject_ref: str, **extra) -> dict:
    corps = {"scope": "tenant", "subjectRef": subject_ref, "reason": "Demande client à traiter"}
    corps.update(extra)
    return await client.post(ROUTE_CAS, json=corps, headers=_entete(token, organization_id))


def _url_resolution(case_id: str) -> str:
    return f"{ROUTE_CAS}/{case_id}/resolve"


# CA-1 : un cas ouvert ou assigné n'empêche pas la clôture et ne se ferme jamais en cascade.

async def test_ca1_cas_ouvert_ne_bloque_pas_la_cloture_et_reste_ouvert(client, registered_user, organization):
    tenant_id = organization["id"]
    abonnement_id = await _creer_abonnement(uuid.UUID(tenant_id))
    await _ajouter_synchronisation_appliquee(abonnement_id)
    entete = _entete(registered_user["accessToken"], tenant_id)
    ouverture = await _ouvrir_cas(client, registered_user["accessToken"], tenant_id, f"subscription:{abonnement_id}")
    assert ouverture.status_code == 201, ouverture.text
    cas_id = ouverture.json()["id"]

    reponse = await client.post(f"/api/v1/billing/subscriptions/{abonnement_id}/close", headers=entete)

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["status"] == "completed"
    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "subscription_closed"
    assert (await _lire_cas(cas_id)).status == "open"


async def test_ca1_cas_assigne_non_cascade_lors_de_la_cloture(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id)
    await _ajouter_synchronisation_appliquee(abonnement_id)
    cas_id = await _creer_cas_direct(tenant_id, f"subscription:{abonnement_id}", "assigned")

    async with AsyncSessionLocal() as db:
        await demander_cloture(db, abonnement_id, tenant_id, await _identifiant_utilisateur(registered_user["email"]))

    assert (await _lire_abonnement(abonnement_id)).lifecycleStatus == "subscription_closed"
    assert (await _lire_cas(str(cas_id))).status == "assigned"


# CA-2 : pas de résolution sans motif ni entrée d'audit.

async def test_ca2_ouverture_sans_motif_est_refusee(client, registered_user, organization):
    tenant_id = organization["id"]
    sujet = f"subscription:{uuid.uuid4()}"

    reponse = await _ouvrir_cas(client, registered_user["accessToken"], tenant_id, sujet, reason="   ")

    assert reponse.status_code == 422, reponse.text
    assert await _cas_par_sujet(sujet) == []


async def test_ca2_resolution_sans_motif_est_refusee(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    cas_id = await _creer_cas_direct(tenant_id, f"subscription:{uuid.uuid4()}", "investigating")

    reponse = await client.post(
        _url_resolution(str(cas_id)),
        json={"reason": ""},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 422, reponse.text
    assert (await _lire_cas(str(cas_id))).status == "investigating"
    assert await _entrees_audit(ACTION_AUDIT_RESOLUTION, str(cas_id)) == []


async def test_ca2_resolution_avec_motif_ecrit_une_entree_d_audit(client, registered_user, organization):
    tenant_id = organization["id"]
    ouverture = await _ouvrir_cas(client, registered_user["accessToken"], tenant_id, f"subscription:{uuid.uuid4()}")
    cas_id = ouverture.json()["id"]

    reponse = await client.post(
        _url_resolution(cas_id),
        json={"reason": "Client recontacté, facture régularisée"},
        headers=_entete(registered_user["accessToken"], tenant_id),
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["status"] == "resolved"
    cas = await _lire_cas(cas_id)
    assert cas.status == "resolved"
    assert cas.resolutionReason == "Client recontacté, facture régularisée"
    entrees = await _entrees_audit(ACTION_AUDIT_RESOLUTION, cas_id)
    assert len(entrees) == 1
    assert entrees[0].reason == "Client recontacté, facture régularisée"


# CA-3 : refus sans permission, pas d'impersonation, approbation indépendante pour l'action sensible.

async def test_ca3_ouverture_sans_permission_renvoie_forbidden(client, registered_user, organization):
    tenant_id = organization["id"]
    email = f"be096-m-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token = await _inscrire_et_connecter(client, email)
    await _ajouter_membre_sans_droit(tenant_id, email)
    sujet = f"subscription:{uuid.uuid4()}"

    reponse = await _ouvrir_cas(client, token, tenant_id, sujet)

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"
    assert await _cas_par_sujet(sujet) == []


async def test_ca3_resolution_sans_permission_sensible_renvoie_forbidden(client, registered_user, organization):
    tenant_id = organization["id"]
    ouverture = await _ouvrir_cas(client, registered_user["accessToken"], tenant_id, f"subscription:{uuid.uuid4()}")
    cas_id = ouverture.json()["id"]
    await _retirer_permission_au_proprietaire(tenant_id, BILLING_CASE_RESOLVE)

    reponse = await client.post(
        _url_resolution(cas_id),
        json={"reason": "Tentative sans droit"},
        headers=_entete(registered_user["accessToken"], tenant_id),
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"
    assert (await _lire_cas(cas_id)).status == "open"
    assert await _entrees_audit(ACTION_AUDIT_RESOLUTION, cas_id) == []


async def test_ca3_action_pending_exige_une_approbation_independante(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    acteur_id = await _identifiant_utilisateur(registered_user["email"])
    cas_id = str(await _creer_cas_direct(tenant_id, f"subscription:{uuid.uuid4()}", "action_pending"))
    entete = _entete(registered_user["accessToken"], organization["id"])
    corps = {"reason": "Action sensible validée"}

    sans_approbateur = await client.post(_url_resolution(cas_id), json=corps, headers=entete)
    auto_approbation = await client.post(
        _url_resolution(cas_id), json={**corps, "approverId": str(acteur_id)}, headers=entete
    )

    assert sans_approbateur.status_code == 409, sans_approbateur.text
    assert sans_approbateur.json()["error"]["code"] == "APPROVAL_REQUIRED"
    assert auto_approbation.status_code == 409, auto_approbation.text
    assert auto_approbation.json()["error"]["code"] == "APPROVAL_REQUIRED"
    assert (await _lire_cas(cas_id)).status == "action_pending"

    email_approbateur = f"be096-a-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    await _inscrire_et_connecter(client, email_approbateur)
    approbateur_id = await _ajouter_membre_sans_droit(organization["id"], email_approbateur)
    approuvee = await client.post(
        _url_resolution(cas_id), json={**corps, "approverId": str(approbateur_id)}, headers=entete
    )

    assert approuvee.status_code == 200, approuvee.text
    assert (await _lire_cas(cas_id)).status == "resolved"


async def test_ca3_pas_d_impersonation_routage_et_acteur_issu_du_jeton(client, registered_user, organization):
    from app.main import app

    # Les routeurs sont imbriqués (FastAPI `_IncludedRouter`) : le schéma OpenAPI donne la liste à plat.
    chemins = {
        (methode.upper(), chemin)
        for chemin, operations in app.openapi()["paths"].items()
        if chemin.startswith(ROUTE_CAS)
        for methode in operations
    }
    assert chemins == {
        ("POST", ROUTE_CAS),
        ("POST", "/api/v1/billing/cases/{case_id}/resolve"),
    }
    assert not [chemin for _, chemin in chemins if "impersonat" in chemin or "act-as" in chemin]

    tenant_id = organization["id"]
    acteur_id = await _identifiant_utilisateur(registered_user["email"])
    usurpe_id = uuid.uuid4()
    reponse = await _ouvrir_cas(
        client, registered_user["accessToken"], tenant_id, f"subscription:{uuid.uuid4()}",
        actorId=str(usurpe_id), assigneeId=str(usurpe_id),
    )

    assert reponse.status_code == 201, reponse.text
    cas_id = reponse.json()["id"]
    cas = await _lire_cas(cas_id)
    assert cas.assigneeId is None
    entrees = await _entrees_audit(ACTION_AUDIT_OUVERTURE, cas_id)
    assert len(entrees) == 1
    assert entrees[0].actorUserId == acteur_id


# CA-4 : un cas d'un tenant n'est pas visible depuis un autre scope.

async def test_ca4_cas_d_un_tenant_invisible_depuis_un_autre_tenant(client, registered_user, organization):
    tenant_a = organization["id"]
    tenant_b, token_b = await _creer_autre_tenant(client)
    ouverture = await _ouvrir_cas(client, registered_user["accessToken"], tenant_a, f"subscription:{uuid.uuid4()}")
    cas_id = ouverture.json()["id"]

    reponse = await client.post(
        _url_resolution(cas_id),
        json={"reason": "Tentative depuis un autre tenant"},
        headers=_entete(token_b, tenant_b),
    )

    assert reponse.status_code == 404, reponse.text
    assert reponse.json()["error"]["code"] == "case_not_found"
    assert (await _lire_cas(cas_id)).status == "open"
    assert await _entrees_audit(ACTION_AUDIT_RESOLUTION, cas_id) == []


async def test_ca4_ouverture_rattachee_au_tenant_de_l_en_tete(client, registered_user, organization):
    tenant_a = organization["id"]
    tenant_b, token_b = await _creer_autre_tenant(client)
    sujet = f"subscription:{uuid.uuid4()}"

    reponse = await _ouvrir_cas(
        client, registered_user["accessToken"], tenant_a, sujet, organizationId=tenant_b
    )

    assert reponse.status_code == 201, reponse.text
    cas = (await _cas_par_sujet(sujet))[0]
    assert str(cas.organizationId) == tenant_a
