"""Algorithmes métier validés (Point 3 §10) — jamais réimplémentés à
l'intérieur d'un endpoint, toujours appelés depuis ce module unique."""


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


def correct_volume_to_reference_temperature(
    measured_volume_liters: float, measured_temperature_c: float, thermal_expansion_coefficient: float
) -> float:
    """Correction volumétrique à 15°C (nouveau-zylo-liquid/Point 5 §5.2) :
    V_15 = V_mesuré × [1 - alpha × (T_mesurée - 15)]."""
    return measured_volume_liters * (1 - thermal_expansion_coefficient * (measured_temperature_c - 15))
