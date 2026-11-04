"""BE-088 : changement de plan, aperçu et application.

Intention : prouver les critères d'acceptation de BE-088
(implementation-backend/tasks-abonnements-facturation.md, section BE-088) :
- CA-1 : un downgrade est appliqué à échéance, jamais immédiatement : l'abonnement
  garde son plan, sa date de fin et son axe lifecycle ; la demande est planifiée à `endDate` ;
- CA-2 : l'aperçu d'upgrade renvoie les effets financiers sans formule de prorata ; le
  prorata est absent et signalé par un code (provisoire, QE-FAC-05) ; aucun montant n'est
  inventé : sans règle de prix (BE-078), le montant résolu est nul et le code d'erreur
  de la résolution est renvoyé ; avec une règle saisie, le montant est celui de la règle ;
  l'application d'un upgrade est refusée (QE-FAC-05 : changement en cours de période refusé) ;
- CA-3 : sans permission acheteur (`billing.subscription.manage`), `FORBIDDEN` ; aucune
  modification de l'abonnement, aucune demande créée ;
- CA-4 : un changement de plan sur un abonnement d'un autre tenant renvoie la même réponse
  qu'un abonnement inexistant ; un instantané de plan d'un autre tenant est refusé.

Hors périmètre de ces tests : le périmètre payeur (ACTF-04, QE-FAC-03) et le prorata
(QE-FAC-05) ne sont pas tranchés ; seule la permission de gestion sur le tenant
bénéficiaire est testée, comme pour BE-090.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.billing import service
from app.billing.catalog_snapshot import capturer_version_offre
from app.billing.models import PlanChange, PriceRule, Subscription
from app.billing.plan_changes.service import SCENARIO_CHANGEMENT_PLAN
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import Organization, OrganizationUser, User


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


async def _creer_organisation_isolee() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="be088", slug=f"be088-{uuid.uuid4().hex[:10]}", status="active")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _creer_plan_et_instantane(tenant_id: uuid.UUID, actor_id: uuid.UUID) -> tuple[str, uuid.UUID]:
    """Crée un plan du catalogue, puis fige sa version pour le tenant (BE-075).

    Renvoie le code du plan et l'identifiant de l'instantané capturé.
    """
    code = f"be088-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        await service.get_or_create_plan(db, "zylo_liquid", code, "Plan BE-088", 1000, "XAF", 30)
        snapshot = await capturer_version_offre(db, organization_id=tenant_id, plan_code=code, actor_user_id=actor_id)
        return code, snapshot.id


async def _creer_abonnement(tenant_id: uuid.UUID, lifecycle: str = "active") -> uuid.UUID:
    """Abonnement du tenant sur un plan de test, période de 30 jours."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be088-abo-{uuid.uuid4().hex[:8]}", "Plan abonnement BE-088", 1000, "XAF", 30
        )
        abonnement = Subscription(
            organizationId=tenant_id,
            planId=plan.id,
            status="active",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
            beneficiaryTenantId=tenant_id,
            lifecycleStatus=lifecycle,
        )
        db.add(abonnement)
        await db.commit()
        return abonnement.id


async def _lire_abonnement(subscription_id: uuid.UUID) -> Subscription:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Subscription).where(Subscription.id == subscription_id))


async def _demandes_de_changement(subscription_id: uuid.UUID) -> list[PlanChange]:
    async with AsyncSessionLocal() as db:
        resultat = await db.scalars(select(PlanChange).where(PlanChange.subscriptionId == subscription_id))
        return list(resultat)


async def _configurer_regle_prix(tenant_id: uuid.UUID, plan_code: str, montant_minor: int, devise: str, taux_bps: int) -> None:
    """Saisit la règle de prix du plan cible pour le tenant (BE-078). Valeurs de test explicites."""
    async with AsyncSessionLocal() as db:
        db.add(
            PriceRule(
                organizationId=tenant_id,
                objectCode=plan_code,
                scenario=SCENARIO_CHANGEMENT_PLAN,
                amountMinor=montant_minor,
                currency=devise,
                taxRateBps=taux_bps,
            )
        )
        await db.commit()


async def _inscrire_et_connecter(client, email: str) -> str:
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Membre"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return login.json()["accessToken"]


async def _ajouter_membre_sans_droit(organization_id: str, email: str) -> None:
    async with AsyncSessionLocal() as db:
        utilisateur = await db.scalar(select(User).where(User.email == email))
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=utilisateur.id))
        await db.commit()


def _entete(token: str, organization_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _url_apercu(subscription_id: uuid.UUID) -> str:
    return f"/api/v1/billing/subscriptions/{subscription_id}/plan-change/preview"


def _url_application(subscription_id: uuid.UUID) -> str:
    return f"/api/v1/billing/subscriptions/{subscription_id}/plan-change"


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.scalar(select(User).where(User.email == email))).id


# CA-1 : un downgrade est appliqué à échéance, jamais immédiatement.

async def test_ca1_downgrade_planifie_a_echeance_sans_effet_immediat(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    actor_id = await _id_utilisateur(registered_user["email"])
    code_cible, snapshot_id = await _creer_plan_et_instantane(tenant_id, actor_id)
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="active")
    avant = await _lire_abonnement(abonnement_id)

    reponse = await client.post(
        _url_application(abonnement_id),
        json={"targetPlanVersionSnapshotId": str(snapshot_id), "direction": "downgrade"},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code in (200, 201), reponse.text
    corps = reponse.json()
    assert corps["direction"] == "downgrade"
    assert corps["status"] == "scheduled"
    assert datetime.fromisoformat(corps["effectiveAt"]) == avant.endDate  # effet à l'échéance

    apres = await _lire_abonnement(abonnement_id)
    assert apres.lifecycleStatus == avant.lifecycleStatus
    assert apres.planVersionId == avant.planVersionId
    assert apres.endDate == avant.endDate
    demandes = await _demandes_de_changement(abonnement_id)
    assert len(demandes) == 1
    assert demandes[0].effectiveAt == avant.endDate
    assert demandes[0].targetPlanVersionSnapshotId == snapshot_id


# CA-2 : aperçu d'upgrade sans prorata inventé ; upgrade non appliqué en cours de période.

async def test_ca2_apercu_upgrade_sans_prorata_ni_montant_invente(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    actor_id = await _id_utilisateur(registered_user["email"])
    _, snapshot_id = await _creer_plan_et_instantane(tenant_id, actor_id)
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="active")

    reponse = await client.post(
        _url_apercu(abonnement_id),
        json={"targetPlanVersionSnapshotId": str(snapshot_id), "direction": "upgrade"},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 200, reponse.text
    effets = reponse.json()["financialEffects"]
    assert effets["prorata"] is None
    assert effets["prorataStatus"] == "NON_DEFINI"  # code provisoire, QE-FAC-05
    # Aucune règle de prix saisie : pas de montant, le code de résolution BE-078 est renvoyé.
    assert effets["resolvedPrice"] is None
    assert effets["priceErrorCode"] == "PRICE_NOT_CONFIGURED"
    assert await _demandes_de_changement(abonnement_id) == []


async def test_ca2_apercu_upgrade_affiche_le_montant_de_la_regle_saisie(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    actor_id = await _id_utilisateur(registered_user["email"])
    code_cible, snapshot_id = await _creer_plan_et_instantane(tenant_id, actor_id)
    await _configurer_regle_prix(tenant_id, code_cible, montant_minor=2500, devise="XAF", taux_bps=1925)
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="active")

    reponse = await client.post(
        _url_apercu(abonnement_id),
        json={"targetPlanVersionSnapshotId": str(snapshot_id), "direction": "upgrade"},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 200, reponse.text
    effets = reponse.json()["financialEffects"]
    assert effets["prorata"] is None
    assert effets["resolvedPrice"]["amountMinor"] == 2500
    assert effets["resolvedPrice"]["currency"] == "XAF"
    assert effets["resolvedPrice"]["taxRateBps"] == 1925
    assert effets["priceErrorCode"] is None


async def test_ca2_application_upgrade_refusee_en_cours_de_periode(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    actor_id = await _id_utilisateur(registered_user["email"])
    _, snapshot_id = await _creer_plan_et_instantane(tenant_id, actor_id)
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="active")
    avant = await _lire_abonnement(abonnement_id)

    reponse = await client.post(
        _url_application(abonnement_id),
        json={"targetPlanVersionSnapshotId": str(snapshot_id), "direction": "upgrade"},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["error"]["code"] == "INVALID_TRANSITION"
    assert (await _lire_abonnement(abonnement_id)).planVersionId == avant.planVersionId
    assert await _demandes_de_changement(abonnement_id) == []


# CA-3 : refus FORBIDDEN sans permission acheteur, abonnement inchangé.

async def test_ca3_changement_de_plan_sans_permission_renvoie_forbidden(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    actor_id = await _id_utilisateur(registered_user["email"])
    _, snapshot_id = await _creer_plan_et_instantane(tenant_id, actor_id)
    email_membre = f"be088-membre-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token_membre = await _inscrire_et_connecter(client, email_membre)
    await _ajouter_membre_sans_droit(organization["id"], email_membre)
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="active")
    avant = await _lire_abonnement(abonnement_id)
    corps = {"targetPlanVersionSnapshotId": str(snapshot_id), "direction": "downgrade"}

    reponse_apercu = await client.post(_url_apercu(abonnement_id), json=corps, headers=_entete(token_membre, organization["id"]))
    reponse_application = await client.post(_url_application(abonnement_id), json=corps, headers=_entete(token_membre, organization["id"]))

    assert reponse_apercu.status_code == 403, reponse_apercu.text
    assert reponse_apercu.json()["error"]["code"] == "FORBIDDEN"
    assert reponse_application.status_code == 403, reponse_application.text
    assert reponse_application.json()["error"]["code"] == "FORBIDDEN"
    apres = await _lire_abonnement(abonnement_id)
    assert apres.planVersionId == avant.planVersionId
    assert apres.lifecycleStatus == avant.lifecycleStatus
    assert await _demandes_de_changement(abonnement_id) == []


# CA-4 : isolation tenant, réponse identique à l'inexistant.

async def test_ca4_changement_de_plan_hors_tenant_repond_comme_inexistant(client, registered_user, organization):
    headers_a = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    reponse_b = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"be088-b-{uuid.uuid4().hex[:8]}"},
        headers=headers_a,
    )
    tenant_b = reponse_b.json()["id"]
    tenant_a = uuid.UUID(organization["id"])
    actor_id = await _id_utilisateur(registered_user["email"])
    _, snapshot_a = await _creer_plan_et_instantane(tenant_a, actor_id)
    abonnement_a = await _creer_abonnement(tenant_a, lifecycle="active")
    corps = {"targetPlanVersionSnapshotId": str(snapshot_a), "direction": "downgrade"}

    reponse_hors_scope = await client.post(_url_application(abonnement_a), json=corps, headers=_entete(registered_user["accessToken"], tenant_b))
    reponse_inexistante = await client.post(_url_application(uuid.uuid4()), json=corps, headers=_entete(registered_user["accessToken"], tenant_b))

    assert reponse_hors_scope.status_code == 404, reponse_hors_scope.text
    assert reponse_hors_scope.status_code == reponse_inexistante.status_code
    assert reponse_hors_scope.json()["error"] == reponse_inexistante.json()["error"]
    assert await _demandes_de_changement(abonnement_a) == []


async def test_ca4_instantane_d_un_autre_tenant_est_refuse(client, registered_user, organization):
    headers_a = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    reponse_b = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B bis", "slug": f"be088-bb-{uuid.uuid4().hex[:8]}"},
        headers=headers_a,
    )
    tenant_b = uuid.UUID(reponse_b.json()["id"])
    tenant_a = uuid.UUID(organization["id"])
    actor_id = await _id_utilisateur(registered_user["email"])
    _, snapshot_de_b = await _creer_plan_et_instantane(tenant_b, actor_id)
    abonnement_a = await _creer_abonnement(tenant_a, lifecycle="active")

    reponse = await client.post(
        _url_application(abonnement_a),
        json={"targetPlanVersionSnapshotId": str(snapshot_de_b), "direction": "downgrade"},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )

    assert reponse.status_code == 404, reponse.text
    assert await _demandes_de_changement(abonnement_a) == []


# Garde-fou : une seule demande planifiée à la fois pour un abonnement.

async def test_une_seule_demande_de_changement_planifiee_par_abonnement(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    actor_id = await _id_utilisateur(registered_user["email"])
    _, snapshot_id = await _creer_plan_et_instantane(tenant_id, actor_id)
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="active")
    corps = {"targetPlanVersionSnapshotId": str(snapshot_id), "direction": "downgrade"}
    headers = _entete(registered_user["accessToken"], organization["id"])

    premiere = await client.post(_url_application(abonnement_id), json=corps, headers=headers)
    seconde = await client.post(_url_application(abonnement_id), json=corps, headers=headers)

    assert premiere.status_code in (200, 201), premiere.text
    assert seconde.status_code == 409, seconde.text
    assert seconde.json()["error"]["code"] == "INVALID_TRANSITION"
    assert len(await _demandes_de_changement(abonnement_id)) == 1
