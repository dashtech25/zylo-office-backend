"""Règles pures des index de pompe, de la fermeture et de la continuité des compteurs (D1, B3, B4). Aucune lecture de base."""




# Index de pompe : Numeric(14,2), six chiffres entiers + 2 décimales (limite À CONFIRMER TERRAIN, PC-36).
PUMP_INDEX_MAX_INTEGER_DIGITS = 6



PUMP_INDEX_DECIMALS = 2



# Origine d'un index d'ouverture : reporté, premier tour de la pompe (saisi), écart de continuité déclaré.
OPENING_SOURCE_CARRIED = "carried"



OPENING_SOURCE_INITIAL = "initial"



OPENING_SOURCE_BREAK = "continuity_break"



OPENING_SOURCES = (OPENING_SOURCE_CARRIED, OPENING_SOURCE_INITIAL, OPENING_SOURCE_BREAK)



# Origine d'un stock d'ouverture : stock réel du tour précédent (D2) ou saisi.
STOCK_SOURCE_PREVIOUS_REAL = "previous_real_stock"



STOCK_SOURCE_INITIAL = "initial"



# Motifs d'un écart de continuité (À CONFIRMER TERRAIN, D8) ; seuls les deux premiers autorisent un index plus BAS.
CONTINUITY_REASON_METER_REPLACED = "meter_replaced"



CONTINUITY_REASON_METER_RESET = "meter_reset"



CONTINUITY_REASON_CARRY_ERROR = "carry_error"



CONTINUITY_REASON_OTHER = "other"



CONTINUITY_REASONS = (CONTINUITY_REASON_METER_REPLACED, CONTINUITY_REASON_METER_RESET, CONTINUITY_REASON_CARRY_ERROR, CONTINUITY_REASON_OTHER)



CONTINUITY_REASONS_ALLOWING_DECREASE = (CONTINUITY_REASON_METER_REPLACED, CONTINUITY_REASON_METER_RESET)



CONTINUITY_REASON_LABELS: dict[str, str] = {
    CONTINUITY_REASON_METER_REPLACED: "Compteur remplacé",
    CONTINUITY_REASON_METER_RESET: "Compteur remis à zéro (dépassement 999 999)",
    CONTINUITY_REASON_CARRY_ERROR: "Erreur de report du tour précédent",
    CONTINUITY_REASON_OTHER: "Autre",
}



CONTINUITY_NOTE_MIN, CONTINUITY_NOTE_MAX = 10, 300



PUMP_INDEX_CONTINUITY_BROKEN_EVENT = "PumpIndexContinuityBroken"



def format_decimal_fr(value, decimals: int = 2) -> str:
    """« 125 480,35 » (espace insécable fin avant les milliers, virgule décimale) pour les messages d'erreur."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", " ").replace(".", ",")



def parse_exact_decimal(raw) -> "Decimal | None":
    """Nombre décimal EXACT (jamais de flottant) depuis un nombre ou une chaîne (virgule ou point acceptés) ;
    None si illisible, non fini ou vide. Les espaces (milliers) sont ignorés."""
    from decimal import Decimal, InvalidOperation

    if raw is None:
        return None
    if isinstance(raw, Decimal):
        value = raw
    else:
        text = str(raw).strip().replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
        if not text:
            return None
        try:
            value = Decimal(text)
        except InvalidOperation:
            return None
    return value if value.is_finite() else None



def pump_index_problem(value) -> str | None:
    """None si l'index est valide ; sinon `negative`, `too_many_decimals` ou `too_large`."""
    from decimal import Decimal

    if value < 0:
        return "negative"
    if value.as_tuple().exponent < -PUMP_INDEX_DECIMALS:
        return "too_many_decimals"
    if value >= Decimal(10) ** PUMP_INDEX_MAX_INTEGER_DIGITS:
        return "too_large"
    return None



PUMP_CLOSING_RECORDED_EVENT = "PumpClosingRecorded"



PUMP_COUNTER_REPLACED_EVENT = "PumpCounterReplaced"



COUNTER_EVENT_NONE = "none"



COUNTER_EVENT_ROLLOVER = "rollover"



COUNTER_EVENT_REPLACED = "replaced"



COUNTER_EVENTS = (COUNTER_EVENT_NONE, COUNTER_EVENT_ROLLOVER, COUNTER_EVENT_REPLACED)



# Compteur remis à zéro : six chiffres entiers (modulo 1 000 000,00) — HYPOTHÈSE À CONFIRMER TERRAIN (PC-36).
COUNTER_ROLLOVER_MODULUS = 10 ** PUMP_INDEX_MAX_INTEGER_DIGITS



COUNTER_EVENT_NOTE_MIN = 10



# Motifs d'une rature (liste fermée, libellés FR affichés dans la pop-up et dans les messages).
RATURE_REASON_LABELS = {
    "read_error": "Erreur de lecture",
    "digits_swapped": "Chiffres inversés",
    "decimal_forgotten": "Décimale oubliée",
    "read_before_end": "Index lu avant la fin du tour",
    "other": "Autre",
}



RATURE_NOTE_MIN = 10



CLOSING_EXITS_NOTE_MAX = 255



CLOSING_RATURE_FIELDS = ("closingIndex", "exitsLiters", "tankReturnLiters")



# Plausibilités AMBRE, jamais bloquantes — SEUILS À CONFIRMER TERRAIN (PC-07, non fournis) :
# une lecture avant `fin - 15 min` ; un volume très éloigné de la moyenne des tours clos de la pompe
# (au moins 3 tours réels, sinon aucun avertissement : jamais de seuil inventé sans historique).
CLOSING_EARLY_READ_MARGIN_MINUTES = 15



CLOSING_HABIT_MIN_SHIFTS = 3



CLOSING_HABIT_HIGH_FACTOR = 2   # plus de 2 fois la moyenne



CLOSING_HABIT_LOW_DIVISOR = 4   # moins du quart de la moyenne



def compute_pump_movement(opening, closing, counter_event: str = COUNTER_EVENT_NONE, replaced_old_final=None, replaced_new_start=None):
    """Litres qui ont TOURNÉ au compteur pendant le tour, avant sorties (Decimal), ou None si une donnée manque.
    Normal : fermeture - ouverture. `rollover` : (1 000 000,00 - ouverture) + fermeture. `replaced` :
    (dernier index de l'ancien compteur - ouverture) + (fermeture - index de départ du nouveau)."""
    from decimal import Decimal

    if opening is None or closing is None:
        return None
    opening, closing = Decimal(opening), Decimal(closing)
    if counter_event == COUNTER_EVENT_ROLLOVER:
        return (Decimal(COUNTER_ROLLOVER_MODULUS) - opening) + closing
    if counter_event == COUNTER_EVENT_REPLACED:
        if replaced_old_final is None or replaced_new_start is None:
            return None
        return (Decimal(replaced_old_final) - opening) + (closing - Decimal(replaced_new_start))
    return closing - opening



def compute_sold_liters(opening, closing, exits=None, counter_event: str = COUNTER_EVENT_NONE, replaced_old_final=None, replaced_new_start=None):
    """Litres VENDUS d'une pompe — méthode PC-04 PROVISOIRE (à confirmer terrain) :
    `(fermeture - ouverture) - sorties`, sorties = 0 si non déclarées. Les RETOURS EN CUVE n'interviennent jamais ici
    (ils n'agissent que sur le stock, D2). Si le terrain confirme une autre règle, seule cette fonction change."""
    from decimal import Decimal

    movement = compute_pump_movement(opening, closing, counter_event, replaced_old_final, replaced_new_start)
    if movement is None:
        return None
    return movement - (Decimal(exits) if exits is not None else Decimal(0))



def compute_line_amount(sold_liters, unit_price):
    """Montant d'une ligne = litres vendus x prix, arrondi à 2 décimales (demi vers le haut) ; None si prix ou litres inconnus."""
    from decimal import ROUND_HALF_UP, Decimal

    if sold_liters is None or unit_price is None:
        return None
    return (Decimal(sold_liters) * Decimal(unit_price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)



def compute_product_amount(total_liters, unit_price):
    """Montant d'un PRODUIT = (somme des litres du produit) x prix, arrondi UNE seule fois (c'est ainsi que le papier calcule :
    1 633,77 x 840 = 1 372 366,80). Peut différer de quelques centimes de la somme des montants de lignes (PC-06)."""
    return compute_line_amount(total_liters, unit_price)



def closing_habit_warning(sold_liters, past_sold: list):
    """(moyenne, drapeau) : drapeau `high` / `low` si le volume s'écarte beaucoup de la moyenne des tours clos de la pompe ;
    (None, None) sans au moins CLOSING_HABIT_MIN_SHIFTS tours réels (jamais de seuil sans historique). Ambre, jamais bloquant."""
    from decimal import Decimal

    values = [Decimal(v) for v in past_sold if v is not None]
    if sold_liters is None or len(values) < CLOSING_HABIT_MIN_SHIFTS:
        return None, None
    average = sum(values) / len(values)
    if average <= 0:
        return average, None
    sold = Decimal(sold_liters)
    if sold > average * CLOSING_HABIT_HIGH_FACTOR:
        return average, "high"
    if sold < average / CLOSING_HABIT_LOW_DIVISOR:
        return average, "low"
    return average, None
