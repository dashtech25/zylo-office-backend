"""Algorithmes métier validés (Point 3 §10) — jamais réimplémentés à
l'intérieur d'un endpoint, toujours appelés depuis ce module unique."""

from datetime import timedelta


def interpolate_height_to_volume(calibration_points: list[tuple[float, float]], height_mm: float) -> float | None:
    """Interpolation linéaire hauteur -> volume entre les deux points de la
    table qui encadrent la mesure (nouveau-zylo-liquid/Point 2 §2.4, Point 3
    §3.2). Hors de la plage couverte, la valeur est bornée (clamp) au point
    extrême le plus proche plutôt qu'extrapolée. Retourne None si aucun
    point de calibration n'est fourni (cuve non calibrée — Point 2 §1.4)."""
    if not calibration_points:
        return None

    points = sorted(calibration_points, key=lambda p: p[0])

    if height_mm <= points[0][0]:
        return points[0][1]
    if height_mm >= points[-1][0]:
        return points[-1][1]

    for (h_bas, v_bas), (h_haut, v_haut) in zip(points, points[1:]):
        if h_bas <= height_mm <= h_haut:
            if h_haut == h_bas:
                return v_bas
            ratio = (height_mm - h_bas) / (h_haut - h_bas)
            return v_bas + (v_haut - v_bas) * ratio

    return None  # inatteignable si les bornes ci-dessus sont correctes


def detect_deliveries(
    measurements: list[tuple],
    rise_threshold_mm: float = 50,
    stability_delta_mm: float = 5,
    stabilization_minutes: float = 15,
) -> list[dict]:
    """Détection de livraison (Point 8 §8.3, seuils exacts du code Odoo
    audité cités en Point 3 §10 : hausse ≥ 50mm, stabilité < 5mm,
    confirmation après 15 min — jamais les valeurs d'exemple génériques de
    Point 8.6). `measurements` : liste de (measuredAt: datetime, heightMm:
    float) triée chronologiquement. Retourne une liste de
    {startTime, startHeightMm, endTime, endHeightMm} — la conversion en
    volume est faite par l'appelant via `interpolate_height_to_volume`
    (jamais dupliquée ici)."""
    if len(measurements) < 2:
        return []

    events = []
    baseline_time, baseline_height = measurements[0]
    in_delivery = False
    start_time = start_height = None
    peak_height = None
    stabilization_start = None

    for i in range(1, len(measurements)):
        t, h = measurements[i]
        prev_t, prev_h = measurements[i - 1]

        if not in_delivery:
            if h - baseline_height >= rise_threshold_mm:
                in_delivery = True
                start_time, start_height = baseline_time, baseline_height
                peak_height = h
                stabilization_start = None
            elif h <= baseline_height:
                baseline_time, baseline_height = t, h
        else:
            if h > peak_height:
                peak_height = h
                stabilization_start = None
            elif abs(h - prev_h) < stability_delta_mm:
                if stabilization_start is None:
                    stabilization_start = prev_t
                elif (t - stabilization_start) >= timedelta(minutes=stabilization_minutes):
                    events.append(
                        {"startTime": start_time, "startHeightMm": start_height, "endTime": t, "endHeightMm": h}
                    )
                    in_delivery = False
                    baseline_time, baseline_height = t, h
            else:
                stabilization_start = None

    return events


def correct_volume_to_reference_temperature(
    measured_volume_liters: float, measured_temperature_c: float, thermal_expansion_coefficient: float
) -> float:
    """Correction volumétrique à 15°C (nouveau-zylo-liquid/Point 5 §5.2) :
    V_15 = V_mesuré × [1 - alpha × (T_mesurée - 15)]."""
    return measured_volume_liters * (1 - thermal_expansion_coefficient * (measured_temperature_c - 15))
