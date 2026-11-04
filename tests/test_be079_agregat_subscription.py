"""BE-079 : agrégat Subscription et états indépendants.

Intention : prouver les critères d'acceptation de BE-079
(implementation-backend/tasks-abonnements-facturation.md, section BE-079) :
- CA-1 : les trois axes (`lifecycle`, `financial`, `incident`) sont persistés et lisibles
  séparément ; une transition sur un axe ne modifie pas les deux autres ;
- CA-2 : une transition non prévue par la machine d'état renvoie `INVALID_TRANSITION` ;
- CA-3 : `GET /api/v1/billing/subscriptions/{subscriptionId}` sans permission renvoie
  `FORBIDDEN` ; un état `active` seul n'accorde aucun droit (droits inchangés) ;
- CA-4 : un abonnement du tenant A est répondu comme inexistant au scope B.

La table `subscription` appartient à BE-023 (non redéfinie) ; les colonnes `payerId`,
`beneficiaryTenantId`, `adminUserId` viennent de BE-071 et `version` de BE-072.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.billing import service
from app.billing.models import Subscription
from app.billing.subscriptions.etats import transition_etat
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.identity.models import Organization, OrganizationUser, User
from app.rbac.service import list_effective_permission_codes


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après.

    Le module `zylo_liquid` est semé comme le fait la fixture `client` (plan.moduleCode).
    """
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    yield
    await engine.dispose()


async def _creer_organisation_isolee() -> uuid.UUID:
    """Organisation sans lien HTTP, pour les tests de service."""
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="be079", slug=f"be079-{uuid.uuid4().hex[:10]}", status="active")
        db.add(organisation)
        await db.commit()
        return organisation.id


async def _creer_abonnement(
    tenant_id: uuid.UUID, lifecycle: str = "trialing", financial: str = "none", incident: str = "none"
) -> uuid.UUID:
    """Abonnement du tenant avec ses trois axes posés explicitement ; renvoie son identifiant."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await service.get_or_create_plan(
            db, "zylo_liquid", f"be079-{uuid.uuid4().hex[:8]}", "Plan BE-079", 1000, "XAF", 30
        )
        abonnement = Subscription(
            organizationId=tenant_id,
            planId=plan.id,
            status="trial",
            startDate=maintenant,
            endDate=maintenant + timedelta(days=30),
            beneficiaryTenantId=tenant_id,
            lifecycleStatus=lifecycle,
            financialStatus=financial,
            incidentStatus=incident,
        )
        db.add(abonnement)
        await db.commit()
        return abonnement.id


async def _lire_axes(subscription_id: uuid.UUID) -> tuple[str, str, str]:
    """Relit les trois axes directement en base (pas de cache de session)."""
    async with AsyncSessionLocal() as db:
        abonnement = await db.scalar(select(Subscription).where(Subscription.id == subscription_id))
        return abonnement.lifecycleStatus, abonnement.financialStatus, abonnement.incidentStatus


async def _ajouter_membre_sans_droit(organization_id: str, email: str) -> uuid.UUID:
    """Rattache un utilisateur à l'organisation sans aucun rôle (aucune permission billing)."""
    async with AsyncSessionLocal() as db:
        utilisateur = await db.scalar(select(User).where(User.email == email))
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=utilisateur.id))
        await db.commit()
        return utilisateur.id


async def _inscrire_et_connecter(client, email: str) -> str:
    """Crée un utilisateur de test et renvoie son jeton d'accès."""
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Membre"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return login.json()["accessToken"]


def _entete(token: str, organization_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


# CA-1 : trois axes persistés et lisibles séparément, transitions isolées par axe.

async def test_ca1_trois_axes_persistes_et_lisibles_separement(client, registered_user, organization):
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="trialing")

    async with AsyncSessionLocal() as db:
        await transition_etat(db, abonnement_id, tenant_id, "lifecycle", "active")
    assert await _lire_axes(abonnement_id) == ("active", "none", "none")

    async with AsyncSessionLocal() as db:
        await transition_etat(db, abonnement_id, tenant_id, "incident", "past_due")
    assert await _lire_axes(abonnement_id) == ("active", "none", "past_due")

    async with AsyncSessionLocal() as db:
        await transition_etat(db, abonnement_id, tenant_id, "financial", "pending")
    assert await _lire_axes(abonnement_id) == ("active", "pending", "past_due")

    # La lecture HTTP restitue les trois axes séparément, sans fusion.
    reponse = await client.get(
        f"/api/v1/billing/subscriptions/{abonnement_id}",
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["lifecycleStatus"] == "active"
    assert corps["financialStatus"] == "pending"
    assert corps["incidentStatus"] == "past_due"


# CA-2 : transition non prévue par la machine d'état -> INVALID_TRANSITION, état intact.

@pytest.mark.parametrize(
    ("axe", "cible"),
    [
        ("lifecycle", "cancelled"),  # trialing -> cancelled n'est pas prévu
        ("incident", "grace"),  # none -> grace n'est pas prévu (il faut passer par past_due)
        ("financial", "settled"),  # none -> settled n'est pas prévu (il faut passer par pending)
        ("lifecycle", "valeur_inconnue"),  # valeur hors machine d'état
    ],
)
async def test_ca2_transition_non_prevue_renvoie_invalid_transition(axe, cible):
    tenant_id = await _creer_organisation_isolee()
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="trialing")

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await transition_etat(db, abonnement_id, tenant_id, axe, cible)

    assert erreur.value.code == "INVALID_TRANSITION"
    assert erreur.value.status_code == 409
    assert await _lire_axes(abonnement_id) == ("trialing", "none", "none")


# CA-3 : refus FORBIDDEN sans permission ; un état active n'accorde aucun droit.

async def test_ca3_get_sans_permission_renvoie_forbidden(client, registered_user, organization):
    email_membre = f"be079-membre-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token_membre = await _inscrire_et_connecter(client, email_membre)
    await _ajouter_membre_sans_droit(organization["id"], email_membre)
    abonnement_id = await _creer_abonnement(uuid.UUID(organization["id"]), lifecycle="active")

    reponse = await client.get(
        f"/api/v1/billing/subscriptions/{abonnement_id}",
        headers=_entete(token_membre, organization["id"]),
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"


async def test_ca3_etat_active_seul_n_accorde_aucun_droit(client, registered_user, organization):
    email_membre = f"be079-droits-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    token_membre = await _inscrire_et_connecter(client, email_membre)
    membre_id = await _ajouter_membre_sans_droit(organization["id"], email_membre)
    tenant_id = uuid.UUID(organization["id"])
    abonnement_id = await _creer_abonnement(tenant_id, lifecycle="trialing")

    async with AsyncSessionLocal() as db:
        droits_avant = await list_effective_permission_codes(db, tenant_id, membre_id)

    async with AsyncSessionLocal() as db:
        await transition_etat(db, abonnement_id, tenant_id, "lifecycle", "active")

    async with AsyncSessionLocal() as db:
        droits_apres = await list_effective_permission_codes(db, tenant_id, membre_id)
    assert droits_apres == droits_avant
    assert "billing.subscription.read" not in droits_apres

    reponse = await client.get(
        f"/api/v1/billing/subscriptions/{abonnement_id}",
        headers=_entete(token_membre, organization["id"]),
    )
    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"


# CA-4 : abonnement d'un autre tenant répondu comme un abonnement inexistant.

async def test_ca4_abonnement_d_un_autre_tenant_repond_comme_inexistant(client, registered_user, organization):
    headers_a = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    reponse_b = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B", "slug": f"be079-b-{uuid.uuid4().hex[:8]}"},
        headers=headers_a,
    )
    tenant_b = reponse_b.json()["id"]
    abonnement_a = await _creer_abonnement(uuid.UUID(organization["id"]), lifecycle="active")

    reponse_hors_scope = await client.get(
        f"/api/v1/billing/subscriptions/{abonnement_a}",
        headers=_entete(registered_user["accessToken"], tenant_b),
    )
    reponse_inexistante = await client.get(
        f"/api/v1/billing/subscriptions/{uuid.uuid4()}",
        headers=_entete(registered_user["accessToken"], tenant_b),
    )

    assert reponse_hors_scope.status_code == 404, reponse_hors_scope.text
    assert reponse_hors_scope.status_code == reponse_inexistante.status_code
    assert reponse_hors_scope.json()["error"]["code"] == "subscription_not_found"
    assert reponse_hors_scope.json()["error"] == reponse_inexistante.json()["error"]
