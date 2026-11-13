"""Préparation d'opérations financières sans exécution PSP (BE-136).

Une préparation est une **intention** `admin_command` de classe
`facturation.operation`, visant une facture (`targetObjectType = "Invoice"`). Elle ne
déclenche aucun appel au prestataire de paiement : l'exécution reste interdite tant
que la politique financière et le PSP ne sont pas décidés (PH-10, QE-ADM-08). Ce
module ne contient donc aucun import ni aucun appel vers `app.billing.payment_provider`.

Droits :
- seul le rôle `finance_support` (autorité finance, PH-10 : hypothèse consignée), sur
  la portée `tenant:<uuid>` du tenant de la facture, peut préparer ;
- le tenant d'une facture est celui de son abonnement (`beneficiaryTenantId`, à défaut
  `organizationId`) : un rôle finance sur un autre tenant ne vaut rien (CA-4) ;
- tout refus par absence d'autorité ouvre un cas d'intervention de qualification
  « Escalade finance » (CA-5), tracé par une entrée d'audit d'ouverture de cas, puis
  renvoie 403. Le cas est commis avant la levée, pour survivre à la réponse d'erreur.

Données : aucune table propre (BE-136). L'intention réutilise `admin_command` (BE-124),
la garde de portée et les rôles de BE-123, l'idempotence de BE-124. Aucune donnée de
carte n'est acceptée : le schéma de corps refuse les champs inconnus (422, voir
`finance_commands_router.py`).

Hors périmètre, consigné : le type précis d'opération (remboursement, avoir, etc.),
la permission `admin.finance.prepare` (NON DÉFINIE) et la prévisualisation d'une facture
(BE-125 ne sait prévisualiser qu'un tenant). Aucun de ces points n'est inventé ici.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.admin_audit import ecrire_evenement_admin
from app.billing.models import Invoice, Subscription
from app.core.errors import AppError
from app.operator.cases import (
    ACTION_OUVERTURE,
    TYPE_ENTITE_CAS,
    InterventionCase,
    erreur_refus,
    portee_du_cas,
    roles_actifs_sur_portee,
)
from app.operator.commands import AdminCommand, commande_existante, corps_identique, erreur_idempotence, nouvelle_commande

CLASSE_FINANCIERE = "facturation.operation"
TYPE_OBJET_FACTURE = "Invoice"
ROLES_FINANCE = frozenset({"finance_support"})
PREFIXE_ESCALADE_FINANCE = "Escalade finance"


def erreur_facture_introuvable() -> AppError:
    return AppError(code="invoice_not_found", message="Facture introuvable.", status_code=404)


async def tenant_de_la_facture(db: AsyncSession, invoice_id: uuid.UUID) -> tuple[Invoice, uuid.UUID]:
    """La facture et le tenant qui la porte ; 404 si la facture n'existe pas.

    Le tenant est `beneficiaryTenantId` de l'abonnement, repris de `organizationId`
    tant que la migration BE-071 ne l'a pas renseigné.
    """
    facture = await db.get(Invoice, invoice_id)
    if facture is None:
        raise erreur_facture_introuvable()
    abonnement = await db.get(Subscription, facture.subscriptionId)
    if abonnement is None:
        raise erreur_facture_introuvable()
    return facture, abonnement.beneficiaryTenantId or abonnement.organizationId


async def ouvrir_escalade_finance(
    db: AsyncSession,
    actor_id: uuid.UUID,
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    correlation_id: str | None,
) -> None:
    """Ouvre un cas `haute` de qualification « Escalade finance » et l'audite, puis commit.

    Appelée juste avant le 403 de CA-5 : le commit doit précéder la levée d'erreur,
    sinon la transaction annulée effacerait la trace de l'escalade. L'écriture d'audit
    exige un identifiant de corrélation (BE-122) : il vient de la requête.
    """
    maintenant = datetime.now(timezone.utc)
    cas = InterventionCase(
        tenantId=tenant_id,
        status="ouvert",
        priority="haute",
        qualification=f"{PREFIXE_ESCALADE_FINANCE} : préparation refusée pour la facture {invoice_id}",
        openedBy=actor_id,
        openedAtUtc=maintenant,
    )
    db.add(cas)
    await db.flush()
    await ecrire_evenement_admin(
        db,
        organization_id=tenant_id,
        actor_user_id=actor_id,
        action=ACTION_OUVERTURE,
        entity_type=TYPE_ENTITE_CAS,
        entity_id=cas.id,
        summary="Escalade finance ouverte après refus de préparation",
        correlation_id=correlation_id,
        changes={"status": "ouvert", "priority": "haute"},
    )
    await db.commit()


async def preparer_operation_financiere(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    corps: dict[str, Any],
    correlation_id: str | None,
) -> tuple[AdminCommand, bool]:
    """Crée (ou retrouve) l'intention financière de la facture.

    Renvoie `(commande, cree)`. `cree` vaut False au rejeu identique (la route répond
    200). Ordre des contrôles : facture (404), autorité finance sur la portée du
    tenant (403 et escalade), idempotence (409 si la clé a servi à un autre corps).
    Aucun appel au PSP n'est émis (CA-3).
    """
    _, tenant_id = await tenant_de_la_facture(db, invoice_id)
    roles = await roles_actifs_sur_portee(db, actor_id, portee_du_cas(tenant_id))
    autorises = roles & ROLES_FINANCE
    if not autorises:
        await ouvrir_escalade_finance(db, actor_id, tenant_id, invoice_id, correlation_id)
        raise erreur_refus()

    corps_complet = {
        "commandType": CLASSE_FINANCIERE,
        "commandVersion": 1,
        "tenantId": tenant_id,
        "targetObjectType": TYPE_OBJET_FACTURE,
        "targetObjectId": str(invoice_id),
        "targetVersionExpected": None,
        "reasonTicket": corps["reasonTicket"],
        "idempotencyKey": corps["idempotencyKey"],
    }
    existante = await commande_existante(db, actor_id, corps["idempotencyKey"])
    if existante is not None:
        if not corps_identique(existante, corps_complet):
            raise erreur_idempotence()
        return existante, False

    commande = nouvelle_commande(
        corps=corps_complet,
        actor_id=actor_id,
        effective_role=sorted(autorises)[0],
        correlation_id=correlation_id,
    )
    db.add(commande)
    await db.commit()
    await db.refresh(commande)
    return commande, True
