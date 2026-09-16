"""Algorithmes métier validés (Point 3 §10) — jamais réimplémentés à
l'intérieur d'un endpoint, toujours appelés depuis ce module unique."""

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

# Constantes/algorithmes de tracking GPS (détection d'arrêt, plausibilité
# de position, rapprochement aux lieux nommés) — déplacés vers
# `app/location/algorithms.py` (2026-09-15, Phase 2). Rien de tracking ne
# doit revenir ici : ce fichier ne porte plus que les algorithmes cuves/
# caisse/rapprochement propres à zylo_liquid.


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


# Correction du 2026-09-14 (constat outillé, voir
# vente-maintenant-reglementation/validation-algorithme-livraison.md) : un
# dépotage réel fluctue presque toujours (turbulence/mousse pendant le débit,
# phénomène documenté — les "turbulence arresters" posés sur les tubes de
# remplissage existent justement pour l'atténuer). Avant cette correction,
# `peak_height` suivait la valeur BRUTE instantanée et n'était comparée qu'au
# pic MAXIMAL JAMAIS observé : un seul pic de bruit au-dessus de la vraie
# hauteur finale "empoisonnait" durablement ce pic de référence, empêchant
# toute confirmation de stabilisation ensuite — vérifié : dès qu'une
# fluctuation dépassait ±5mm (la bande de stabilité elle-même), une vraie
# livraison de 10 000 L n'était plus jamais détectée, quelle que soit la
# durée d'attente (le pic ne redescend jamais, donc l'écart au pic ne
# repasse jamais sous le seuil).
#
# Un correctif "ancre qui se réinitialise sur le point courant" a été
# essayé et rejeté : le bruit étant indépendant d'un point à l'autre, deux
# points consécutifs peuvent différer de plus de `stability_delta_mm` même
# à niveau réellement stable dès que l'amplitude de fluctuation dépasse la
# bande de stabilité — l'ancre se réinitialise alors sans arrêt et les 15
# minutes ne s'accumulent jamais.
#
# Correctif retenu : à chaque nouveau point, on maintient la plus longue
# séquence CONTIGUË se terminant au point courant dont l'écart max-min reste
# ≤ `stability_delta_mm` (on retire des points en tête de fenêtre tant que
# ce n'est pas le cas — comme une fenêtre glissante à taille variable). Si
# cette séquence couvre au moins `stabilization_minutes` (par le temps, pas
# par un nombre de points — robuste à un échantillonnage irrégulier), la
# livraison est confirmée. Un pic ou un creux de bruit isolé ne fait que
# raccourcir temporairement la séquence (les points avant lui sont écartés) ;
# dès que les points suivants redeviennent plats, la séquence recommence à
# grandir — contrairement à l'ancien pic historique qui restait bloqué pour
# toujours.


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
    fin de la fenêtre ou None).

    La stabilisation est évaluée sur une fenêtre glissante des dernières
    `stabilization_minutes` minutes (voir commentaire au-dessus) plutôt que
    par rapport au pic historique jamais dépassé — robuste à la
    turbulence/mousse réelle d'un dépotage, qui fait fluctuer la hauteur de
    plusieurs mm sans que ce soit un vrai second pic durable."""
    if len(measurements) < 2:
        return [], None

    events: list[dict] = []
    baseline_time, baseline_height = measurements[0]
    in_delivery = False
    start_time = start_height = None
    window: list[tuple] = []  # (time, height) — plus longue séquence plate se terminant au point courant
    stabilization_window = timedelta(minutes=stabilization_minutes)

    for i in range(1, len(measurements)):
        t, h = measurements[i]

        if not in_delivery:
            if h - baseline_height >= rise_threshold_mm:
                in_delivery = True
                start_time, start_height = baseline_time, baseline_height
                window = [(t, h)]
            elif h <= baseline_height:
                baseline_time, baseline_height = t, h
        else:
            if h < start_height:
                # Retombé sous le niveau de départ sans jamais s'être
                # stabilisé : ce n'était pas une livraison (juste une
                # consommation) — on abandonne le candidat sans enregistrer
                # d'événement.
                in_delivery = False
                baseline_time, baseline_height = t, h
                window = []
                continue

            window.append((t, h))
            window_heights = [wh for _, wh in window]
            while len(window) > 1 and (max(window_heights) - min(window_heights)) > stability_delta_mm:
                window.pop(0)
                window_heights.pop(0)

            if (t - window[0][0]) >= stabilization_window:
                events.append(
                    {"startTime": start_time, "startHeightMm": start_height, "endTime": t, "endHeightMm": h}
                )
                in_delivery = False
                baseline_time, baseline_height = t, h
                window = []

    open_candidate = None
    if in_delivery:
        last_time, last_raw = measurements[-1]
        open_candidate = {"startTime": start_time, "startHeightMm": start_height, "currentTime": last_time, "currentHeightMm": last_raw}

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
