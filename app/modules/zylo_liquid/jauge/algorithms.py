"""Règles pures du jaugeage : conversion hauteur-volume, stock de contrôle, comparaison à la télémétrie. Aucune lecture de base."""

from app.modules.zylo_liquid.algorithms import interpolate_height_to_volume
from app.modules.zylo_liquid.pumps.algorithms import parse_exact_decimal


TANK_GAUGING_RECORDED_EVENT = "TankGaugingRecorded"



REAL_STOCK_SOURCE_CALIBRATION = "calibration_table"



REAL_STOCK_SOURCE_PAPER = "paper_table"



GAUGING_METHODS = ("dipstick", "gauge_pole", "other")



GAUGING_RATURE_REASON_LABELS = {
    "wrong_dip": "Règle mal plongée",
    "reading_error": "Erreur de lecture",
    "conversion_error": "Erreur de conversion",
    "remeasured_after_gap": "Mesure refaite après écart",
    "other": "Autre",
}



# Fenêtre au-delà de laquelle la mesure télémétrique retenue par le rapprochement (±24 h, la plus proche) est
# signalée « trop ancienne » (décalage affiché pour ne pas tromper l'utilisateur ; à confirmer terrain, PC-D2-d).
GAUGING_TELEMETRY_MAX_OFFSET_MINUTES = 30



# Seuil provisoire (non bloquant, à confirmer terrain) de l'avertissement « stock réel supérieur de plus de 5 % ».
GAUGING_ABOVE_THEORETICAL_PERCENT = 5



# Avertissement ambre si la mesure est faite plus de 15 minutes avant la fin du tour (à confirmer terrain).
GAUGING_BEFORE_END_MINUTES = 15



GAUGING_REPEATED_SHORTAGE_COUNT = 3



def parse_height_cm_to_mm(raw) -> "Decimal | None":
    """Hauteur saisie en CENTIMÈTRES (une décimale maximum, ≥ 0) convertie en MILLIMÈTRES (× 10, exact).
    None si absente, illisible, négative ou à plus d'une décimale."""
    from decimal import Decimal

    value = parse_exact_decimal(raw)
    if value is None or value < 0:
        return None
    if value != value.quantize(Decimal("0.1")):
        return None
    return (value * 10).quantize(Decimal("0.01"))



def height_in_table(points: "list[tuple[Decimal, Decimal]]", height_mm) -> str:
    """`ok`, `no_table` (aucun point), `below` (sous le premier point) ou `above` (au-dessus du dernier). L'interpolation
    existante BORNE sans prévenir hors plage : on refuse AVANT de convertir (jamais de stock inventé)."""
    if not points:
        return "no_table"
    heights = [p[0] for p in points]
    if height_mm < min(heights):
        return "below"
    if height_mm > max(heights):
        return "above"
    return "ok"



def convert_height_with_table(points: "list[tuple[Decimal, Decimal]]", height_mm) -> "Decimal | None":
    """Litres (2 décimales) pour une hauteur DANS la table, via l'unique fonction d'interpolation du module
    (`interpolate_height_to_volume`). None si la table est absente ou la hauteur hors table (jamais de bornage)."""
    from decimal import ROUND_HALF_UP, Decimal

    if height_in_table(points, height_mm) != "ok":
        return None
    liters = interpolate_height_to_volume([(float(h), float(v)) for h, v in points], float(height_mm))
    if liters is None:
        return None
    return Decimal(repr(round(liters, 6))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)



def compute_stock_control(opening, received, sold, non_sale, real) -> "tuple[Decimal | None, Decimal | None]":
    """(théorique, écart) en décimal exact. théorique = ouverture + reçu - vendu - sorties hors vente nettes ;
    écart = réel - théorique (signé, jamais arrondi à zéro). `sold`/`non_sale` None (D1 pas enregistré) : (None, None)."""
    if sold is None or non_sale is None:
        return None, None
    theoretical = opening + received - sold - non_sale
    variance = None if real is None else real - theoretical
    return theoretical, variance
