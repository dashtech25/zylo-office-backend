"""Règles pures de la caisse : montants, répartition des ventes par pompiste, NOTA. Aucune lecture de base."""

from app.modules.zylo_liquid.pumps.algorithms import parse_exact_decimal
from decimal import Decimal as _D5Decimal


CASH_COLLECTION_RECORDED_EVENT = "CashCollectionRecorded"



CASH_NOTE_MAX = 255



CASH_AMOUNT_MAX_INTEGER_DIGITS = 12



CASH_AMOUNT_FIELDS = ("creditVouchersAmount", "mobilePaymentsAmount", "otherDeductionsAmount", "attendantCountedAmount", "managerRecountedAmount")



CASH_RATURE_REASONS = ("count_error", "entry_error", "voucher_found", "index_corrected", "other")



CASH_RATURE_REASON_LABELS = {
    "count_error": "Erreur de comptage", "entry_error": "Erreur de saisie", "voucher_found": "Bon retrouvé",
    "index_corrected": "Index corrigé", "other": "Autre",
}



CASH_REASON_NOTE_MIN = 10



PUMP_SHARE_REASON_MIN = 10



# États d'attribution d'une pompe.
PUMP_ATTRIBUTION_STATES = ("no_sale", "single", "segment_index", "manual", "needs_manual", "no_holder", "closing_missing")



def parse_cash_amount(raw) -> "tuple[Decimal | None, str | None]":
    """Montant de caisse : (valeur, None) ou (None, problème). Problèmes : `not_a_number`, `negative`, `too_many_decimals`,
    `too_large`. Accepte « 303 950,32 » comme « 303950.32 » (espaces, virgule). Jamais de flottant : un nombre JSON
    flottant passe par sa représentation texte."""
    from decimal import Decimal

    value = parse_exact_decimal(raw)
    if value is None:
        return None, "not_a_number"
    if value < 0:
        return None, "negative"
    if value.as_tuple().exponent < -2:
        return None, "too_many_decimals"
    if value >= Decimal(10) ** CASH_AMOUNT_MAX_INTEGER_DIGITS:
        return None, "too_large"
    return value, None



def split_amount_with_remainder(total, weights: list) -> list:
    """Répartit `total` (2 décimales) au prorata EXACT de `weights` (litres), chaque part arrondie à 2 décimales ; la DERNIÈRE
    part reçoit le reliquat d'arrondi de sorte que la somme soit exactement `total`. Poids tous nuls : parts à zéro (le total
    doit alors être nul)."""
    from decimal import ROUND_HALF_UP, Decimal

    cent = Decimal("0.01")
    if not weights:
        return []
    weight_sum = sum(weights, Decimal(0))
    parts: list = []
    for weight in weights[:-1]:
        parts.append((total * weight / weight_sum).quantize(cent, rounding=ROUND_HALF_UP) if weight_sum else Decimal("0.00"))
    parts.append(total - sum(parts, Decimal(0)))
    return parts



def attribute_pump_sales(
    *, liters, amount, unit_price, segments: list, closing_index, has_exits: bool, counter_event: str = "none", manual_shares: dict | None = None,
) -> dict:
    """Attribution des litres et du montant d'UNE pompe à ses pompistes (règle PC-05).

    `liters` / `amount` / `unit_price` : litres vendus, montant et prix copiés par D1 (None = non disponible).
    `segments` : chronologie B4/B5 de la pompe, du plus ancien au plus récent, liste de `(user_id | None, start_index | None)`.
    `manual_shares` : répartition MANUELLE déclarée `{user_id: litres}` (None = aucune).

    Renvoie `{"state", "holders", "shares": {user_id: (litres, montant | None)}, "problem"}`. Un état `needs_manual` signifie
    que RIEN n'est attribué : les pompistes concernés restent « non calculés »."""
    from decimal import ROUND_HALF_UP, Decimal

    cent = Decimal("0.01")
    holders: list = []
    for user_id, _start in segments:
        if user_id is not None and user_id not in holders:
            holders.append(user_id)
    result = {"state": "needs_manual", "holders": holders, "shares": {}, "problem": None}
    if not holders:
        # Pompe fermée pour le tour (sans pompiste) : rien à attribuer tant qu'elle n'a pas de vente.
        result["state"] = "no_sale" if liters is None or Decimal(liters) == 0 else "no_holder"
        return result
    if liters is None:
        result["state"] = "closing_missing"
        return result
    liters = Decimal(liters)
    amount = None if amount is None else Decimal(amount)
    if len(holders) == 1:
        result.update(state="single", shares={holders[0]: (liters, amount)})
        return result

    def amounts_for(parts_liters: list) -> list:
        if amount is None:
            return [None] * len(parts_liters)
        return split_amount_with_remainder(amount, parts_liters)

    # (b) Plusieurs titulaires : répartition automatique SEULEMENT si tous les index de changement sont connus et que la pompe
    # n'a ni sorties ni événement compteur (les litres vendus ne sont alors plus une simple différence d'index).
    indexes = [start for _user, start in segments]
    auto_ok = not has_exits and counter_event == "none" and closing_index is not None and all(i is not None for i in indexes)
    if auto_ok:
        bounds = [Decimal(i) for i in indexes] + [Decimal(closing_index)]
        seg_liters = [bounds[k + 1] - bounds[k] for k in range(len(segments))]
        orphan = any(user is None and seg_liters[k] != 0 for k, (user, _s) in enumerate(segments))
        if all(v >= 0 for v in seg_liters) and not orphan and sum(seg_liters, Decimal(0)) == liters:
            kept = [(user, seg_liters[k]) for k, (user, _s) in enumerate(segments) if user is not None]
            seg_amounts = amounts_for([v for _u, v in kept])
            shares: dict = {}
            for (user, seg_l), seg_a in zip(kept, seg_amounts):
                old_l, old_a = shares.get(user, (Decimal(0), Decimal(0) if amount is not None else None))
                shares[user] = (old_l + seg_l, None if amount is None else old_a + seg_a)
            result.update(state="segment_index", shares=shares)
            return result
    # (c) Répartition manuelle déclarée (somme exacte des litres exigée ; sinon elle est ignorée = à refaire).
    if manual_shares:
        declared = {u: Decimal(v) for u, v in manual_shares.items()}
        if set(declared) <= set(holders) and sum(declared.values(), Decimal(0)) == liters:
            order = [u for u in holders if u in declared]
            part_amounts = amounts_for([declared[u] for u in order])
            result.update(state="manual", shares={u: (declared[u], a) for u, a in zip(order, part_amounts)})
            return result
        result["problem"] = "manual_shares_stale"
    return result



def compute_cash_line(sales_value, credit, mobile, other, counted, recounted) -> dict:
    """Calcul d'une ligne de caisse en décimal exact : théorique = ventes - déductions (None si ventes inconnues),
    remis = recompté, écart signé = remis - théorique (None si théorique inconnu), nature, concordance des comptages."""
    from decimal import Decimal

    deductions = Decimal(credit) + Decimal(mobile) + Decimal(other)
    theoretical = None if sales_value is None else Decimal(sales_value) - deductions
    remitted = Decimal(recounted)
    variance = None if theoretical is None else remitted - theoretical
    nature = None if variance is None else ("surplus" if variance > 0 else "shortage" if variance < 0 else "balanced")
    return {
        "deductions": deductions, "theoretical": theoretical, "remitted": remitted, "variance": variance, "varianceNature": nature,
        "countsMatch": Decimal(counted) == Decimal(recounted),
    }



def unresolved_pump_groups(unresolved_holders: list[list]) -> list[set]:
    """Groupes de pompistes liés par des pompes partagées NON réparties (composantes connexes). Chaque élément de
    `unresolved_holders` est la liste des pompistes d'une pompe non répartie. Sert à l'« écart de groupe »."""
    groups: list[set] = []
    for holders in unresolved_holders:
        merged = set(holders)
        rest = []
        for group in groups:
            if group & merged:
                merged |= group
            else:
                rest.append(group)
        groups = rest + [merged]
    return groups



CASH_FORMULA_VERSION = "c_minus_expenses_plus_d"



CASH_NOTA_TOLERANCE = _D5Decimal("1.00")  # PC-06 : remplacée par A10 plus tard ; la différence est toujours affichée.



CASH_RETAINED_NOTE_MIN = 10



CASH_SETTLEMENT_MODES = ("cash", "cheque", "loading_card")



CASH_SETTLEMENT_MODE_LABELS = {"cash": "Espèces", "cheque": "Chèque", "loading_card": "Carte de chargement"}



CASH_SUMMARY_SAVED_EVENT = "ShiftReportCashComputed"



def _sum_or_none(*values):
    """Somme exacte ; None dès qu'un terme est inconnu (jamais un zéro inventé)."""
    if any(v is None for v in values):
        return None
    return sum(values, _D5Decimal(0))



def compute_cash_summary(
    *, products_a1, lubricants_a2, gas_a3, shop_a4, credits_b5, value_vouchers_b6, electronic_b7,
    deduct_retained_sales: bool, manual_expenses, settlements, handover_f,
) -> dict:
    """Grandeurs de la caisse d'un tour. Les rubriques 1 à 7 valent un `Decimal` ou `None` (rubrique non commencée / sans source).

    A = rub. 1 + 2 + 3 + 4 ; B = rub. 5 + 6 + 7 ; C = A - B ; dépenses = (rub. 2 + rub. 4 si la règle PC-03 est active) + Σ lignes
    saisies ; D = Σ règlements VAL/CCT ; E = C - dépenses + D ; H = F - E (F = espèces remises, vient de D3).
    Renvoie `{A, B, C, retainedLubricants, retainedShop, retainedTotal, manualExpensesTotal, expensesTotal, D, E, F, H, missing}` ;
    `missing[lettre]` liste les rubriques sources absentes."""
    from decimal import Decimal

    manual_total = sum((Decimal(x) for x in manual_expenses), Decimal(0))
    settlements_total = sum((Decimal(x) for x in settlements), Decimal(0))
    a = _sum_or_none(products_a1, lubricants_a2, gas_a3, shop_a4)
    b = _sum_or_none(credits_b5, value_vouchers_b6, electronic_b7)
    c = None if a is None or b is None else a - b
    if deduct_retained_sales:
        retained_lub, retained_shop = lubricants_a2, shop_a4
        retained = _sum_or_none(lubricants_a2, shop_a4)
    else:
        retained_lub = retained_shop = Decimal(0)
        retained = Decimal(0)
    expenses = None if retained is None else retained + manual_total
    e = None if c is None or expenses is None else c - expenses + settlements_total
    h = None if handover_f is None or e is None else Decimal(handover_f) - e
    missing: dict[str, list[str]] = {}
    for letter, parts in (
        ("A", {"rubric1": products_a1, "rubric2": lubricants_a2, "rubric3": gas_a3, "rubric4": shop_a4}),
        ("B", {"rubric5": credits_b5, "rubric6": value_vouchers_b6, "rubric7": electronic_b7}),
    ):
        missing[letter] = [name for name, value in parts.items() if value is None]
    missing["expenses"] = [name for name, value in (("rubric2", lubricants_a2), ("rubric4", shop_a4)) if deduct_retained_sales and value is None]
    missing["C"] = missing["A"] + missing["B"]
    missing["E"] = missing["C"] + missing["expenses"]
    return {
        "A": a, "B": b, "C": c, "retainedLubricants": retained_lub, "retainedShop": retained_shop, "retainedTotal": retained,
        "manualExpensesTotal": manual_total, "expensesTotal": expenses, "D": settlements_total, "E": e,
        "F": None if handover_f is None else Decimal(handover_f), "H": h, "missing": missing,
    }



def compute_nota_difference(nota_total, cash_gap_h, tolerance=None) -> dict:
    """Contrôle NOTA = H (PC-06) : différence = somme du NOTA - H, conforme si |différence| <= tolérance (1,00 FCFA par défaut,
    borne incluse : 1,00 accepté, 1,01 refusé). Le NOTA n'est JAMAIS ajusté pour tomber juste. Valeur inconnue : `None`."""
    from decimal import Decimal

    if nota_total is None or cash_gap_h is None:
        return {"difference": None, "withinTolerance": None}
    limit = CASH_NOTA_TOLERANCE if tolerance is None else Decimal(tolerance)
    difference = Decimal(nota_total) - Decimal(cash_gap_h)
    return {"difference": difference, "withinTolerance": abs(difference) <= limit}



def cash_gap_nature(value) -> str | None:
    """surplus (> 0) | shortage (< 0) | balanced (= 0) ; None si inconnu."""
    return None if value is None else ("surplus" if value > 0 else "shortage" if value < 0 else "balanced")
