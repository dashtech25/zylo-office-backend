"""BE-089 : renouvellement d'abonnement (job rejouable).

Intention : prouver les critères d'acceptation de BE-089
(implementation-backend/tasks-abonnements-facturation.md, section BE-089) :
- CA-1 : rejouer le job pour la même période ne crée ni deuxième facture ni deuxième tentative ;
- CA-2 : un renouvellement sur un abonnement `cancelled` ou `expired` ne s'exécute pas,
  et le refus est journalisé (`INVALID_TRANSITION`) ;
- CA-3 : le job ne peut pas être déclenché par un utilisateur sans rôle système (`FORBIDDEN`) ;
- CA-4 : isolation tenant : un job traite un abonnement à la fois, sans écriture sur un autre scope.

Le job est testé au niveau service (`app/billing/renewal_job.py`) : BE-089 n'a aucune route
(« Routes : aucune (job système) »). Les abonnements sont créés par la route existante.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.billing import service
from app.billing.models import Invoice, RenewalRun, Subscription
from app.billing.renewal_job import DECLENCHEUR_SYSTEME, renouveler_abonnement
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from tests.test_be027_factures_lecture import creer_organisation, utilisateur_connecte

# Période de facturation de test (clé de période, format libre et opaque pour le job).
PERIODE = "2026-12"
PERIODE_SUIVANTE = "2027-01"


async def _abonnement(client: AsyncClient, token: str, organization_id: str) -> str:
    """Crée un plan de catalogue et un abonnement via la route existante ; renvoie l'identifiant."""
    code = f"plan-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        await service.get_or_create_plan(db, "zylo_liquid", code, "Plan BE-089", 10_000, "XAF", 30)
    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}
    res = await client.post(
        f"/api/v1/billing/organizations/{organization_id}/subscriptions", json={"planCode": code}, headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _etat(subscription_id: str) -> dict:
    """Lit l'abonnement, son nombre de factures et son nombre de passages du job, en base."""
    identifiant = uuid.UUID(subscription_id)
    async with AsyncSessionLocal() as db:
        abonnement = await db.get(Subscription, identifiant)
        factures = await db.scalar(select(func.count()).select_from(Invoice).where(Invoice.subscriptionId == identifiant))
        passages = await db.scalar(select(func.count()).select_from(RenewalRun).where(RenewalRun.subscriptionId == identifiant))
        return {
            "version": abonnement.version,
            "renewedAt": abonnement.renewedAt,
            "lifecycleStatus": abonnement.lifecycleStatus,
            "factures": factures,
            "passages": passages,
        }


async def _poser_cycle_de_vie(subscription_id: str, cycle: str) -> None:
    """Pose l'axe cycle de vie de l'abonnement (écriture de test, hors machine d'état)."""
    async with AsyncSessionLocal() as db:
        await db.execute(update(Subscription).where(Subscription.id == uuid.UUID(subscription_id)).values(lifecycleStatus=cycle))
        await db.commit()


async def _renouveler(subscription_id: str, tenant_id: str, periode: str = PERIODE, declencheur: str = DECLENCHEUR_SYSTEME):
    """Lance le job dans une session propre, comme le ferait le planificateur."""
    async with AsyncSessionLocal() as db:
        return await renouveler_abonnement(
            db, subscription_id=uuid.UUID(subscription_id), tenant_id=uuid.UUID(tenant_id),
            period_key=periode, declencheur=declencheur,
        )


async def test_ca1_rejeu_de_la_meme_periode_ne_cree_ni_seconde_facture_ni_seconde_tentative(client: AsyncClient):
    utilisateur = await utilisateur_connecte(client)
    organisation = await creer_organisation(client, utilisateur["accessToken"])
    abonnement = await _abonnement(client, utilisateur["accessToken"], organisation)

    premier = await _renouveler(abonnement, organisation)
    apres_premier = await _etat(abonnement)
    second = await _renouveler(abonnement, organisation)
    apres_second = await _etat(abonnement)

    assert apres_premier["factures"] == 1
    assert apres_premier["passages"] == 1
    assert second.id == premier.id
    assert apres_second == apres_premier, "le rejeu ne doit toucher ni la facture, ni le passage, ni l'abonnement"

    # Une autre période, elle, renouvelle bien : la clé est bien la période.
    await _renouveler(abonnement, organisation, periode=PERIODE_SUIVANTE)
    assert (await _etat(abonnement))["factures"] == 2


@pytest.mark.parametrize("cycle", ["cancelled", "expired"])
async def test_ca2_renouvellement_sur_abonnement_termine_refuse_et_journalise(client: AsyncClient, cycle: str):
    utilisateur = await utilisateur_connecte(client)
    organisation = await creer_organisation(client, utilisateur["accessToken"])
    abonnement = await _abonnement(client, utilisateur["accessToken"], organisation)
    await _poser_cycle_de_vie(abonnement, cycle)
    avant = await _etat(abonnement)

    with pytest.raises(AppError) as erreur:
        await _renouveler(abonnement, organisation)

    assert erreur.value.code == "INVALID_TRANSITION"
    apres = await _etat(abonnement)
    assert apres["factures"] == 0, "aucune facture ne doit être émise pour un abonnement terminé"
    assert apres["passages"] == 1, "le refus est journalisé par un passage au statut refused"
    assert apres["version"] == avant["version"]
    assert apres["renewedAt"] is None

    async with AsyncSessionLocal() as db:
        passage = await db.scalar(select(RenewalRun).where(RenewalRun.subscriptionId == uuid.UUID(abonnement)))
        assert passage.status == "refused"


async def test_ca3_declenchement_sans_role_systeme_refuse_forbidden(client: AsyncClient):
    utilisateur = await utilisateur_connecte(client)
    organisation = await creer_organisation(client, utilisateur["accessToken"])
    abonnement = await _abonnement(client, utilisateur["accessToken"], organisation)
    avant = await _etat(abonnement)

    with pytest.raises(AppError) as erreur:
        await _renouveler(abonnement, organisation, declencheur=utilisateur["id"])

    assert erreur.value.code == "FORBIDDEN"
    assert await _etat(abonnement) == avant, "un déclenchement refusé n'écrit rien"


async def test_ca4_isolation_tenant_un_abonnement_a_la_fois_sans_ecriture_ailleurs(client: AsyncClient):
    utilisateur = await utilisateur_connecte(client)
    organisation_a = await creer_organisation(client, utilisateur["accessToken"])
    organisation_b = await creer_organisation(client, utilisateur["accessToken"])
    abonnement_a = await _abonnement(client, utilisateur["accessToken"], organisation_a)
    abonnement_b = await _abonnement(client, utilisateur["accessToken"], organisation_a)
    avant_b = await _etat(abonnement_b)

    # Un job du tenant B ne voit pas l'abonnement du tenant A : réponse de l'inexistant.
    with pytest.raises(AppError) as hors_scope:
        await _renouveler(abonnement_a, organisation_b)
    assert hors_scope.value.code == "subscription_not_found"
    assert hors_scope.value.status_code == 404
    assert (await _etat(abonnement_a))["factures"] == 0

    # Le job du bon tenant ne traite que l'abonnement désigné ; le frère reste intact.
    await _renouveler(abonnement_a, organisation_a)
    assert (await _etat(abonnement_a))["factures"] == 1
    assert await _etat(abonnement_b) == avant_b
