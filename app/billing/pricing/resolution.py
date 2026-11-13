"""Résolution du prix, de la devise et de la taxe d'un objet tarifé (BE-078).

Contrat :

- `resoudre_prix` lit la règle du tenant (`organization_id`), de l'objet
  (`object_code`, code de l'offre) et du scénario (`scenario`). Il n'existe
  aucun repli : ni le prix du catalogue (`plan.priceCents`), ni une devise
  ou une taxe par défaut ne sont utilisés. Sans règle, ou avec une règle
  incomplète, la fonction lève `AppError` (422) avec le code correspondant :
  - `PRICE_NOT_CONFIGURED` : pas de règle, ou montant absent ;
  - `CURRENCY_NOT_CONFIGURED` : devise absente ;
  - `TAX_NOT_CONFIGURED` : taux de taxe absent.
  Le contrôle de présence du montant passe avant celui de la devise, puis celui
  de la taxe.
- Une règle appartient à un tenant : la requête filtre sur `organizationId`, donc
  la règle d'un autre tenant produit `PRICE_NOT_CONFIGURED`, comme une règle absente.
- `PrixResolu` est une valeur figée. Elle ne référence pas la ligne `price_rule`.
  Une modification ultérieure de la règle ne change donc pas un prix déjà résolu.
  Le devis (BE-077) stocke `as_snapshot()` au moment de la capture (CA-3 de BE-078).
- `definir_regle_prix` crée ou met à jour la règle du triplet (tenant, objet,
  scénario). Il n'est pas exposé en HTTP : la décision finance sur qui saisit les
  règles reste ouverte (QE-FAC-10). Un montant négatif ou un taux hors de
  0 à 10000 points de base (0 à 100 %) est refusé.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import PriceRule
from app.core.errors import AppError

TAUX_MAX_BPS = 10_000


@dataclass(frozen=True)
class PrixResolu:
    """Prix, devise et taxe résolus pour un objet, un scénario et un tenant.

    Les champs sont des valeurs, pas des références vers la règle. `resolvedAt`
    date la résolution ; il ne sert pas à recalculer le prix.
    """

    organization_id: uuid.UUID
    object_code: str
    scenario: str
    amount_minor: int
    currency: str
    tax_rate_bps: int
    resolved_at: datetime

    def as_snapshot(self) -> dict:
        """Copie sérialisable (JSON) destinée au snapshot du devis (BE-077).

        Les clés sont en camelCase, comme les autres contenus JSON du module.
        Le dictionnaire est neuf à chaque appel : le modifier ne touche pas l'objet.
        """
        return {
            "organizationId": str(self.organization_id),
            "objectCode": self.object_code,
            "scenario": self.scenario,
            "amountMinor": self.amount_minor,
            "currency": self.currency,
            "taxRateBps": self.tax_rate_bps,
            "resolvedAt": self.resolved_at.isoformat(),
        }


async def resoudre_prix(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    object_code: str,
    scenario: str,
) -> PrixResolu:
    """Renvoie le prix résolu, ou lève l'erreur de configuration manquante.

    Ne commit pas et n'écrit rien : c'est une lecture. Voir la docstring du module
    pour l'ordre des contrôles et les codes d'erreur.
    """
    regle = await db.scalar(select(PriceRule).where(
        PriceRule.organizationId == organization_id,
        PriceRule.objectCode == object_code,
        PriceRule.scenario == scenario,
    ))
    if regle is None or regle.amountMinor is None:
        raise billing_error(BillingErrorCode.PRICE_NOT_CONFIGURED)
    if regle.currency is None:
        raise billing_error(BillingErrorCode.CURRENCY_NOT_CONFIGURED)
    if regle.taxRateBps is None:
        raise billing_error(BillingErrorCode.TAX_NOT_CONFIGURED)
    return PrixResolu(
        organization_id=organization_id,
        object_code=object_code,
        scenario=scenario,
        amount_minor=int(regle.amountMinor),
        currency=regle.currency,
        tax_rate_bps=int(regle.taxRateBps),
        resolved_at=datetime.now(timezone.utc),
    )


async def definir_regle_prix(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    object_code: str,
    scenario: str,
    amount_minor: int | None,
    currency: str | None,
    tax_rate_bps: int | None,
) -> PriceRule:
    """Crée ou met à jour la règle du triplet (tenant, objet, scénario), puis commit.

    `None` sur un champ le laisse non configuré ; la résolution le signalera.
    Erreur `price_rule_invalid` (422) si le montant est négatif ou si le taux est
    hors de 0 à `TAUX_MAX_BPS`.
    """
    if amount_minor is not None and amount_minor < 0:
        raise AppError(code="price_rule_invalid", message="Montant négatif refusé.", status_code=422)
    if tax_rate_bps is not None and not 0 <= tax_rate_bps <= TAUX_MAX_BPS:
        raise AppError(code="price_rule_invalid", message="Taux de taxe hors bornes.", status_code=422)
    regle = await db.scalar(select(PriceRule).where(
        PriceRule.organizationId == organization_id,
        PriceRule.objectCode == object_code,
        PriceRule.scenario == scenario,
    ))
    if regle is None:
        regle = PriceRule(organizationId=organization_id, objectCode=object_code, scenario=scenario)
        db.add(regle)
    regle.amountMinor = amount_minor
    regle.currency = currency
    regle.taxRateBps = tax_rate_bps
    await db.commit()
    await db.refresh(regle)
    return regle
