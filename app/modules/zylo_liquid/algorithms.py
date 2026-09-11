"""Algorithmes métier validés (Point 3 §10) — jamais réimplémentés à
l'intérieur d'un endpoint, toujours appelés depuis ce module unique."""

import math
from datetime import timedelta

# Constantes métier nommées (au lieu de littéraux répétés en valeur par
# défaut) — permet à un endpoint de lecture seule (GET /system-defaults) de
# les exposer au frontend sans les retaper, donc sans risque de divergence
# entre ce qui est affiché et ce qui est réellement appliqué par ces
# fonctions. Aucune de ces valeurs n'est configurable par organisation
# aujourd'hui (Point 3 §10 : constantes validées, pas des réglages).
LEAK_THRESHOLD_LPH = 0.38
DELIVERY_RISE_THRESHOLD_MM = 50.0
DELIVERY_STABILITY_DELTA_MM = 5.0
DELIVERY_STABILIZATION_MINUTES = 15.0

# Seuils du moteur de caisse (page_caisse.md §D.1/§K, cas C/D/E/F) — à la
# différence des seuils de livraison ci-dessus, ceux-ci ne proviennent
# d'aucun algorithme métier déjà validé en production : ce sont des valeurs
# de démarrage prudentes, explicitement signalées comme à calibrer avec le
# métier une fois de vraies données de vente observées (page_caisse.md,
# priorité P1 « détection anomalie propre à la caisse »).
CASH_NOISE_FLOOR_LITERS = 3.0
CASH_MAX_PLAUSIBLE_RATE_LPH = 6000.0

# Tolérances de rapprochement (processus-double-sources-verite, Phase 6 §6,
# Phase 7 addendum §1) — défauts réseau, dérogeables par station via
# `StationReconciliationSettings` (Phase 7 §1). Les valeurs par défaut
# reprennent les tolérances du prototype validé par le commanditaire
# (contrôle contradictoire ± 0,5 % du volume déclaré, fenêtre ± 2 h) —
# décision actée avant la fusion de la page #/livraisons ; elles restent à
# confirmer sur données réelles (même réserve que CASH_NOISE_FLOOR_LITERS).
RECONCILIATION_DELIVERY_WINDOW_HOURS_DEFAULT = 2.0
RECONCILIATION_DELIVERY_VOLUME_TOLERANCE_FIXED_LITERS_DEFAULT = 50.0
RECONCILIATION_DELIVERY_VOLUME_TOLERANCE_PERCENT_DEFAULT = 0.5
# Alerte « déclaration en attente » (mission « flux de livraison station ») —
# volontairement pas un champ de StationReconciliationSettings (non demandé,
# pas de besoin de réglage par station exprimé) : une constante fixe, plus
# large que la fenêtre de rapprochement elle-même (2h) pour ne jamais
# signaler une déclaration simplement pas encore rapprochée.
RECONCILIATION_DELIVERY_STALE_PENDING_HOURS_DEFAULT = 24.0
RECONCILIATION_GAUGING_HEIGHT_TOLERANCE_MM_DEFAULT = 10.0
RECONCILIATION_QUALITY_CHECK_WINDOW_HOURS_DEFAULT = 1.0

# Détection d'arrêt camion (mission « tracking », étape 1) — constantes
# fixes pour tout le réseau (un camion dessert plusieurs stations, pas de
# point d'ancrage cohérent pour une dérogation par station — décision
# explicite du commanditaire). Valeurs de démarrage prudentes (comme
# CASH_NOISE_FLOOR_LITERS), à calibrer avec des positions réelles une fois
# le matériel déployé.
TRUCK_STOP_RADIUS_METERS_DEFAULT = 150.0
TRUCK_STOP_STABILIZATION_MINUTES_DEFAULT = 10.0


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


def _scan_deliveries(
    measurements: list[tuple],
    rise_threshold_mm: float,
    stability_delta_mm: float,
    stabilization_minutes: float,
) -> tuple[list[dict], dict | None]:
    """Cœur de l'algorithme de détection de livraison (Point 8 §8.3, seuils
    exacts du code Odoo audité cités en Point 3 §10 : hausse ≥ 50mm,
    stabilité < 5mm, confirmation après 15 min). Factorisé une seule fois
    et réutilisé par `detect_deliveries` (livraisons confirmées) et
    `detect_delivery_in_progress` (montée en cours, pas encore stabilisée)
    — même état, même seuils, jamais deux implémentations qui pourraient
    diverger. Retourne (événements confirmés, candidat encore ouvert à la
    fin de la fenêtre ou None)."""
    if len(measurements) < 2:
        return [], None

    events: list[dict] = []
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
            elif (peak_height - h) <= stability_delta_mm:
                # Stabilisation évaluée par rapport au pic (pas seulement à
                # la mesure précédente) : un palier proche du pic confirme
                # la livraison ; un palier loin en dessous — ex. consommation
                # normale après une fausse détection — ne doit jamais la
                # confirmer (cause du bug des livraisons à volume négatif).
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
                if h < start_height:
                    # Retombé sous le niveau de départ sans jamais s'être
                    # stabilisé près du pic : ce n'était pas une livraison
                    # (juste une consommation) — on abandonne le candidat
                    # sans enregistrer d'événement.
                    in_delivery = False
                    baseline_time, baseline_height = t, h

    open_candidate = None
    if in_delivery:
        last_time, last_height = measurements[-1]
        open_candidate = {"startTime": start_time, "startHeightMm": start_height, "currentTime": last_time, "currentHeightMm": last_height}

    return events, open_candidate


def detect_deliveries(
    measurements: list[tuple],
    rise_threshold_mm: float = DELIVERY_RISE_THRESHOLD_MM,
    stability_delta_mm: float = DELIVERY_STABILITY_DELTA_MM,
    stabilization_minutes: float = DELIVERY_STABILIZATION_MINUTES,
) -> list[dict]:
    """`measurements` : liste de (measuredAt: datetime, heightMm: float)
    triée chronologiquement. Retourne une liste de {startTime,
    startHeightMm, endTime, endHeightMm} — la conversion en volume est
    faite par l'appelant via `interpolate_height_to_volume` (jamais
    dupliquée ici)."""
    events, _ = _scan_deliveries(measurements, rise_threshold_mm, stability_delta_mm, stabilization_minutes)
    return events


def detect_delivery_in_progress(
    measurements: list[tuple],
    rise_threshold_mm: float = DELIVERY_RISE_THRESHOLD_MM,
    stability_delta_mm: float = DELIVERY_STABILITY_DELTA_MM,
    stabilization_minutes: float = DELIVERY_STABILIZATION_MINUTES,
) -> dict | None:
    """Montée en cours, pas encore confirmée (hauteur encore en train de
    monter, ou stabilisation trop récente pour conclure) — jamais persisté
    en base, recalculé à chaque appel depuis les mesures récentes. Retourne
    {startTime, startHeightMm, currentTime, currentHeightMm} ou None si
    aucune hausse en cours sur la fenêtre fournie."""
    _, open_candidate = _scan_deliveries(measurements, rise_threshold_mm, stability_delta_mm, stabilization_minutes)
    return open_candidate


def _haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance entre deux points GPS sur une sphère (formule de
    Haversine) — suffisante pour un rayon de détection d'arrêt de l'ordre
    de la centaine de mètres, aucun besoin d'une projection plus précise."""
    r_earth_meters = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return 2 * r_earth_meters * math.asin(math.sqrt(a))


def _scan_truck_stops(
    positions: list[tuple],
    radius_meters: float,
    stabilization_minutes: float,
) -> tuple[list[dict], dict | None]:
    """Détection d'arrêt camion (mission « tracking », étape 1) — même
    discipline de confirmation que `_scan_deliveries` (ancre stable +
    confirmation après N minutes), avec la distance à l'ancre comme mesure
    à la place de la hauteur de cuve. L'ancre ne bouge que tant qu'aucune
    fenêtre de stabilisation n'est en cours, pour ne jamais dériver
    progressivement loin du point de départ réel de l'arrêt.

    `positions` : liste de (recordedAt: datetime, latitude: float,
    longitude: float) triée chronologiquement. Retourne (arrêts confirmés,
    candidat encore en cours à la fin de la fenêtre ou None)."""
    if len(positions) < 2:
        return [], None

    events: list[dict] = []
    anchor_time, anchor_lat, anchor_lon = positions[0]
    in_stop = False
    start_time = start_lat = start_lon = None
    stabilization_start = None

    for i in range(1, len(positions)):
        t, lat, lon = positions[i]
        distance = _haversine_distance_meters(anchor_lat, anchor_lon, lat, lon)

        if not in_stop:
            if distance <= radius_meters:
                if stabilization_start is None:
                    stabilization_start = anchor_time
                if (t - stabilization_start) >= timedelta(minutes=stabilization_minutes):
                    in_stop = True
                    start_time, start_lat, start_lon = stabilization_start, anchor_lat, anchor_lon
            else:
                # Position hors du rayon de l'ancre : nouvelle ancre, la
                # fenêtre de stabilisation repart de zéro.
                anchor_time, anchor_lat, anchor_lon = t, lat, lon
                stabilization_start = None
        elif distance > radius_meters:
            # Reprise du mouvement : l'arrêt confirmé se termine ici.
            events.append({"startTime": start_time, "latitude": start_lat, "longitude": start_lon, "endTime": t})
            in_stop = False
            anchor_time, anchor_lat, anchor_lon = t, lat, lon
            stabilization_start = None

    open_candidate = None
    if in_stop:
        last_time, _, _ = positions[-1]
        open_candidate = {"startTime": start_time, "latitude": start_lat, "longitude": start_lon, "currentTime": last_time}

    return events, open_candidate


def detect_truck_stops(
    positions: list[tuple],
    radius_meters: float = TRUCK_STOP_RADIUS_METERS_DEFAULT,
    stabilization_minutes: float = TRUCK_STOP_STABILIZATION_MINUTES_DEFAULT,
) -> list[dict]:
    """`positions` : liste de (recordedAt, latitude, longitude) triée
    chronologiquement. Retourne une liste de {startTime, latitude,
    longitude, endTime} — un arrêt confirmé et terminé (le camion a repris
    sa route)."""
    events, _ = _scan_truck_stops(positions, radius_meters, stabilization_minutes)
    return events


def detect_truck_stop_in_progress(
    positions: list[tuple],
    radius_meters: float = TRUCK_STOP_RADIUS_METERS_DEFAULT,
    stabilization_minutes: float = TRUCK_STOP_STABILIZATION_MINUTES_DEFAULT,
) -> dict | None:
    """Arrêt en cours, pas encore terminé (le camion est toujours dans le
    rayon de l'ancre) — jamais persisté en base, recalculé à chaque appel.
    Retourne {startTime, latitude, longitude, currentTime} ou None."""
    _, open_candidate = _scan_truck_stops(positions, radius_meters, stabilization_minutes)
    return open_candidate


def compute_net_corrected_volume(
    calibration_points: list[tuple[float, float]],
    height_mm: float,
    water_height_mm: float | None,
    temperature_c: float | None,
    thermal_expansion_coefficient: float | None,
) -> float | None:
    """Volume carburant net, corrigé à 15°C (Point 10, correction EPA
    finale) : soustraction de l'eau AVANT le calcul du taux de fuite —
    sinon une variation d'eau normale (condensation) crée un faux positif
    — puis correction thermique — sinon un refroidissement nocturne normal
    crée aussi un faux positif (exemple documenté : 31 L de « fuite »
    fictive sur une cuve de 18385L de Gasoil pour 2°C de refroidissement)."""
    v_brut = interpolate_height_to_volume(calibration_points, height_mm)
    if v_brut is None:
        return None
    v_eau = interpolate_height_to_volume(calibration_points, water_height_mm) if water_height_mm is not None else 0.0
    v_net = v_brut - (v_eau or 0.0)
    if temperature_c is not None and thermal_expansion_coefficient is not None:
        return correct_volume_to_reference_temperature(v_net, temperature_c, thermal_expansion_coefficient)
    return v_net


def compute_leak_rate_lph(v_start_corrected: float, v_end_corrected: float, duration_hours: float) -> float:
    """Taux de fuite en litres/heure (Point 10, algorithme EPA final) :
    (V_corrigé_début - V_corrigé_fin) / durée."""
    return (v_start_corrected - v_end_corrected) / duration_hours


def evaluate_threshold_alarms(
    height_mm: float,
    water_height_mm: float | None,
    height_alarm_mm: float,
    height_alert_mm: float,
    low_alarm_mm: float,
    water_alarm_mm: float,
) -> list[str]:
    """Comparaison aux seuils d'alarme (Point 13 §13.4) :
    H_net = H_carburant - H_eau, comparé directement aux 4 seuils
    configurés par cuve, jamais un pourcentage. Retourne les types
    d'alerte déclenchés parmi 'level_high', 'level_high_pre_alarm',
    'level_low', 'water' — l'alerte pleine et la pré-alarme de niveau haut
    sont mutuellement exclusives (escalade), l'eau est indépendante."""
    h_net = height_mm - (water_height_mm or 0)
    triggered = []

    if h_net >= height_alarm_mm:
        triggered.append("level_high")
    elif h_net >= height_alert_mm:
        triggered.append("level_high_pre_alarm")

    if h_net <= low_alarm_mm:
        triggered.append("level_low")

    if (water_height_mm or 0) >= water_alarm_mm:
        triggered.append("water")

    return triggered


def is_leak_detected(rate_lph: float, threshold_lph: float = LEAK_THRESHOLD_LPH) -> bool:
    """Seuil binaire 0.38 L/H (standard EPA, Point 10 §10.4) — strictement
    supérieur, jamais égal (Point 10 §10.3 : « Si Taux_fuite > 0.38 L/H »)."""
    return rate_lph > threshold_lph


def correct_volume_to_reference_temperature(
    measured_volume_liters: float, measured_temperature_c: float, thermal_expansion_coefficient: float
) -> float:
    """Correction volumétrique à 15°C (nouveau-zylo-liquid/Point 5 §5.2) :
    V_15 = V_mesuré × [1 - alpha × (T_mesurée - 15)]."""
    return measured_volume_liters * (1 - thermal_expansion_coefficient * (measured_temperature_c - 15))


def classify_tank_variation(
    volume_start_liters: float,
    volume_end_liters: float,
    duration_hours: float,
    noise_floor_liters: float = CASH_NOISE_FLOOR_LITERS,
    max_plausible_rate_lph: float = CASH_MAX_PLAUSIBLE_RATE_LPH,
) -> tuple[str, float]:
    """Classe une variation de volume observée sur un segment hors-livraison
    (page_caisse.md §D.1, cas B/C/D/E/F) et retourne (type, volumeSoldLiters).

    - decline ≤ 0 (hauteur stable ou en légère hausse dans le bruit de
      mesure) -> "stable", volume 0.
    - decline > plancher de bruit et débit physiquement plausible -> "sale".
    - hausse franche sans livraison détectée qui la couvre -> "anomaly_unexplained_rise",
      jamais comptée comme une vente négative.
    - baisse dont le débit dépasse le plafond plausible -> "anomaly_extreme_variation",
      exclue du total automatique (seuils non calibrés avec le métier, voir
      constantes CASH_NOISE_FLOOR_LITERS / CASH_MAX_PLAUSIBLE_RATE_LPH)."""
    decline = volume_start_liters - volume_end_liters

    if decline <= noise_floor_liters and -decline <= noise_floor_liters:
        return "stable", 0.0

    if decline < 0:
        return "anomaly_unexplained_rise", 0.0

    rate_lph = decline / duration_hours if duration_hours > 0 else float("inf")
    if rate_lph > max_plausible_rate_lph:
        return "anomaly_extreme_variation", 0.0

    return "sale", decline
