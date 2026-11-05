"""BE-093 : remboursement (RequestRefund) avec approbation humaine.

Intention : prouver les critères d'acceptation de BE-093
(implementation-backend/tasks-abonnements-facturation.md, section BE-093) :
- CA-1 : aucun remboursement n'est exécuté sans approbation enregistrée ; l'approbation est
  écrite (ligne `refund` en `pending` + entrée d'audit) AVANT tout appel fournisseur ;
- CA-2 : même paiement + même clé de requête rejoue le résultat, sans second envoi fournisseur ;
- CA-3 : sans permission finance, `FORBIDDEN` ; l'approbateur ne peut pas être le demandeur ;
- CA-4 : rembourser un paiement d'un autre tenant renvoie la réponse de l'inexistant.

Décisions testées (QE-FAC-02, QE-FAC-09, recommandations appliquées) : refus de l'approbateur
identique au demandeur par `APPROVAL_REQUIRED` ; seuil implicite à zéro (approbation toujours
requise) ; plafond = montant du paiement moins les remboursements non échoués.

Route testée : `POST /api/v1/billing/payments/{paymentId}/refunds`. En-tête `Idempotency-Key`
(16 à 120 caractères) et `X-Organization-Id`. Corps : `{"amount", "reason", "approverId"}`.

Le fournisseur est remplacé par un double (`FournisseurRemboursementFictif`) via
`app.dependency_overrides`, pour ne jamais toucher au réseau. Les montants attendus sont des
constantes écrites à la main.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.billing.models import PaymentAttempt, Refund
from app.billing.payment_provider import PaymentProvider
from app.core.database import AsyncSessionLocal
from app.main import app
from tests.test_be027_factures_lecture import ajouter_membre_sans_role, creer_organisation, utilisateur_connecte
from tests.test_be086_facture_brouillon_finalisation import _creer_facture_brouillon, _entetes

# Paiement réussi de 9 000 unités mineures ; premier remboursement 4 000 ; second 6 000 dépasse le reliquat 5 000.
MONTANT_PAIEMENT = 9_000
MONTANT_REMBOURSEMENT = 4_000
MONTANT_AU_DELA_DU_RELIQUAT = 6_000
MOTIF_REMBOURSEMENT = "Remboursement de test BE-093"


class FournisseurRemboursementFictif(PaymentProvider):
    """Double du fournisseur : enregistre chaque appel et renvoie un résultat fixé par le test.

    `statut_au_moment_de_l_appel` relit la ligne `refund` dans une session distincte, au moment où
    le fournisseur est appelé : c'est la preuve de la séquence (approbation écrite avant l'envoi).
    """

    provider = "fictif"
    mode = "test"

    def __init__(self, resultat: bool = True, exception: BaseException | None = None):
        self.resultat = resultat
        self.exception = exception
        self.appels: list[tuple[int, str, str]] = []
        self.statut_au_moment_de_l_appel: list[tuple[str | None, uuid.UUID | None]] = []

    async def charge(self, amount_cents: int, currency: str, reference: str) -> bool:
        raise NotImplementedError

    async def rembourser(self, amount_minor: int, currency: str, reference: str) -> bool:
        self.appels.append((amount_minor, currency, reference))
        async with AsyncSessionLocal() as db:
            ligne = await db.get(Refund, uuid.UUID(reference), populate_existing=True)
            self.statut_au_moment_de_l_appel.append((ligne.status, ligne.approverId) if ligne else (None, None))
        if self.exception is not None:
            raise self.exception
        return self.resultat


@pytest.fixture
def fournisseur_fictif():
    """Installe le double pour la route de remboursement et le retire après le test."""
    from app.billing.refunds.router import obtenir_fournisseur_remboursement

    fournisseur = FournisseurRemboursementFictif()
    app.dependency_overrides[obtenir_fournisseur_remboursement] = lambda: fournisseur
    yield fournisseur
    app.dependency_overrides.pop(obtenir_fournisseur_remboursement, None)


async def _creer_paiement(client: AsyncClient, token: str, organization_id: str, statut: str = "succeeded") -> str:
    """Crée une facture de l'organisation (BE-086) puis un paiement rattaché, au statut donné."""
    facture_id = await _creer_facture_brouillon(client, token, organization_id)
    async with AsyncSessionLocal() as db:
        paiement = PaymentAttempt(
            invoiceId=uuid.UUID(facture_id), provider="fictif", mode="test",
            idempotencyKey=uuid.uuid4().hex, amountMinor=MONTANT_PAIEMENT, currency="XAF",
            status=statut, requestedAt=datetime.now(timezone.utc), providerReference=uuid.uuid4().hex,
        )
        db.add(paiement)
        await db.commit()
        return str(paiement.id)


def _corps(montant: int = MONTANT_REMBOURSEMENT, approbateur: str | None = None, motif: str = MOTIF_REMBOURSEMENT) -> dict:
    return {"amount": montant, "reason": motif, "approverId": approbateur}


def _cle_requete() -> str:
    return uuid.uuid4().hex


async def _approbateur_membre(client: AsyncClient, organization_id: str) -> str:
    """Un second utilisateur rattaché à l'organisation, distinct du demandeur."""
    approbateur = await utilisateur_connecte(client)
    await ajouter_membre_sans_role(organization_id, approbateur["id"])
    return approbateur["id"]


async def _nombre_de_remboursements(paiement_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return len((await db.scalars(select(Refund).where(Refund.paymentAttemptId == uuid.UUID(paiement_id)))).all())


async def test_ca1_sans_approbation_aucun_envoi_fournisseur(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """CA-1 : sans approbateur, APPROVAL_REQUIRED ; le fournisseur n'est jamais appelé et rien n'est écrit."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement(client, token, org)

    reponse = await client.post(
        f"/api/v1/billing/payments/{paiement}/refunds", json=_corps(approbateur=None),
        headers={**_entetes(token, org), "Idempotency-Key": _cle_requete()},
    )

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["error"]["code"] == "APPROVAL_REQUIRED"
    assert fournisseur_fictif.appels == []
    assert await _nombre_de_remboursements(paiement) == 0


async def test_ca1_approbation_enregistree_avant_tout_envoi_fournisseur(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """CA-1 : au moment de l'appel fournisseur, la ligne est `pending` avec l'approbateur ; l'audit existe ; issue `succeeded`."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement(client, token, org)
    approbateur = await _approbateur_membre(client, org)

    reponse = await client.post(
        f"/api/v1/billing/payments/{paiement}/refunds", json=_corps(approbateur=approbateur),
        headers={**_entetes(token, org), "Idempotency-Key": _cle_requete()},
    )

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert corps["status"] == "succeeded"
    assert corps["amount"] == MONTANT_REMBOURSEMENT
    assert corps["currency"] == "XAF"
    assert corps["approverId"] == approbateur
    assert len(fournisseur_fictif.appels) == 1
    assert fournisseur_fictif.statut_au_moment_de_l_appel == [("pending", uuid.UUID(approbateur))]
    async with AsyncSessionLocal() as db:
        audit = await db.scalar(select(AuditEvent).where(
            AuditEvent.action == "billing.refund.approve", AuditEvent.entityId == uuid.UUID(corps["id"]),
        ))
    assert audit is not None


async def test_ca2_meme_cle_rejoue_le_resultat_sans_second_envoi(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """CA-2 : même paiement, même clé, même commande : même remboursement, un seul appel fournisseur.
    Même clé avec un montant différent : DUPLICATE, rien de modifié."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement(client, token, org)
    approbateur = await _approbateur_membre(client, org)
    entetes = {**_entetes(token, org), "Idempotency-Key": _cle_requete()}

    premiere = await client.post(f"/api/v1/billing/payments/{paiement}/refunds", json=_corps(approbateur=approbateur), headers=entetes)
    rejouee = await client.post(f"/api/v1/billing/payments/{paiement}/refunds", json=_corps(approbateur=approbateur), headers=entetes)
    differente = await client.post(
        f"/api/v1/billing/payments/{paiement}/refunds", json=_corps(MONTANT_AU_DELA_DU_RELIQUAT - 1000, approbateur=approbateur), headers=entetes,
    )

    assert premiere.status_code == 201, premiere.text
    assert rejouee.status_code == 201, rejouee.text
    assert rejouee.json()["id"] == premiere.json()["id"]
    assert len(fournisseur_fictif.appels) == 1
    assert differente.status_code == 409
    assert differente.json()["error"]["code"] == "DUPLICATE"
    assert await _nombre_de_remboursements(paiement) == 1


async def test_ca3_sans_permission_finance_renvoie_forbidden(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """CA-3 : un membre sans permission `billing.refund.request` reçoit FORBIDDEN ; aucun appel fournisseur."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement(client, token, org)
    approbateur = await _approbateur_membre(client, org)
    membre = await utilisateur_connecte(client)
    await ajouter_membre_sans_role(org, membre["id"])

    reponse = await client.post(
        f"/api/v1/billing/payments/{paiement}/refunds", json=_corps(approbateur=approbateur),
        headers={**_entetes(membre["accessToken"], org), "Idempotency-Key": _cle_requete()},
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "FORBIDDEN"
    assert fournisseur_fictif.appels == []
    assert await _nombre_de_remboursements(paiement) == 0


async def test_ca3_approbateur_identique_au_demandeur_est_refuse(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """CA-3 : l'approbateur ne peut pas être le demandeur (APPROVAL_REQUIRED, QE-FAC-02) ; aucun appel fournisseur."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement(client, token, org)

    reponse = await client.post(
        f"/api/v1/billing/payments/{paiement}/refunds", json=_corps(approbateur=registered_user["id"]),
        headers={**_entetes(token, org), "Idempotency-Key": _cle_requete()},
    )

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["error"]["code"] == "APPROVAL_REQUIRED"
    assert fournisseur_fictif.appels == []


async def test_ca4_paiement_d_un_autre_tenant_repond_comme_l_inexistant(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """CA-4 : rembourser un paiement d'un autre tenant renvoie la même réponse qu'un identifiant inexistant."""
    token, org = registered_user["accessToken"], organization["id"]
    autre_tenant = await creer_organisation(client, token)
    paiement_autre = await _creer_paiement(client, token, autre_tenant)
    approbateur = await _approbateur_membre(client, org)
    entetes = _entetes(token, org)

    hors_perimetre = await client.post(
        f"/api/v1/billing/payments/{paiement_autre}/refunds", json=_corps(approbateur=approbateur),
        headers={**entetes, "Idempotency-Key": _cle_requete()},
    )
    inexistant = await client.post(
        f"/api/v1/billing/payments/{uuid.uuid4()}/refunds", json=_corps(approbateur=approbateur),
        headers={**entetes, "Idempotency-Key": _cle_requete()},
    )

    assert hors_perimetre.status_code == 404
    assert hors_perimetre.status_code == inexistant.status_code
    assert hors_perimetre.json()["error"]["code"] == inexistant.json()["error"]["code"] == "payment_not_found"
    assert fournisseur_fictif.appels == []
    assert autre_tenant != org


async def test_plafond_le_reliquat_refuse_au_dela_du_paiement(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """Au-delà du reliquat remboursable (paiement moins remboursements non échoués) : REFUND_LIMIT_EXCEEDED."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement(client, token, org)
    approbateur = await _approbateur_membre(client, org)
    premier = await client.post(
        f"/api/v1/billing/payments/{paiement}/refunds", json=_corps(approbateur=approbateur),
        headers={**_entetes(token, org), "Idempotency-Key": _cle_requete()},
    )
    assert premier.status_code == 201, premier.text

    depassement = await client.post(
        f"/api/v1/billing/payments/{paiement}/refunds", json=_corps(MONTANT_AU_DELA_DU_RELIQUAT, approbateur=approbateur),
        headers={**_entetes(token, org), "Idempotency-Key": _cle_requete()},
    )

    assert depassement.status_code == 422, depassement.text
    assert depassement.json()["error"]["code"] == "REFUND_LIMIT_EXCEEDED"
    assert len(fournisseur_fictif.appels) == 1


async def test_paiement_non_reussi_ne_se_rembourse_pas(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """Seul un paiement `succeeded` peut être remboursé ; un paiement `pending` renvoie INVALID_TRANSITION."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement(client, token, org, statut="pending")
    approbateur = await _approbateur_membre(client, org)

    reponse = await client.post(
        f"/api/v1/billing/payments/{paiement}/refunds", json=_corps(approbateur=approbateur),
        headers={**_entetes(token, org), "Idempotency-Key": _cle_requete()},
    )

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["error"]["code"] == "INVALID_TRANSITION"
    assert fournisseur_fictif.appels == []


async def test_refus_du_fournisseur_marque_le_remboursement_failed(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """Le fournisseur refuse : le remboursement passe `failed` et la réponse le dit (pas de statut succeeded)."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement(client, token, org)
    approbateur = await _approbateur_membre(client, org)
    fournisseur_fictif.resultat = False

    reponse = await client.post(
        f"/api/v1/billing/payments/{paiement}/refunds", json=_corps(approbateur=approbateur),
        headers={**_entetes(token, org), "Idempotency-Key": _cle_requete()},
    )

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["status"] == "failed"


async def test_delai_fournisseur_reste_pending_et_repond_202(client: AsyncClient, registered_user: dict, organization: dict, fournisseur_fictif):
    """Délai dépassé : issue inconnue, jamais un échec. Le remboursement reste `pending` (BE-095) et la réponse est 202."""
    token, org = registered_user["accessToken"], organization["id"]
    paiement = await _creer_paiement(client, token, org)
    approbateur = await _approbateur_membre(client, org)
    fournisseur_fictif.exception = TimeoutError()

    reponse = await client.post(
        f"/api/v1/billing/payments/{paiement}/refunds", json=_corps(approbateur=approbateur),
        headers={**_entetes(token, org), "Idempotency-Key": _cle_requete()},
    )

    assert reponse.status_code == 202, reponse.text
    assert reponse.json()["status"] == "pending"
