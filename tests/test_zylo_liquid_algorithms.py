"""Niveau 1 — tests unitaires algorithmiques (Point 4 « Valider une API
comme les titans »). Aucune base de données, aucun réseau : la logique pure
seule, avec des valeurs de référence exactes tirées des documents source."""

from datetime import datetime, timedelta

import pytest

from app.modules.zylo_liquid.algorithms import (
    compute_leak_rate_lph,
    compute_net_corrected_volume,
    correct_volume_to_reference_temperature,
    detect_deliveries,
    interpolate_height_to_volume,
    is_leak_detected,
)

CALIBRATION_TABLE = [(0, 0), (1000, 18000), (1050, 19200), (1100, 20350), (2000, 40000)]


def test_interpolate_height_to_volume_reference_example():
    """Exemple exact de nouveau-zylo-liquid/Point 2 §2.4 : 1073 mm -> 19729 L."""
    volume = interpolate_height_to_volume(CALIBRATION_TABLE, 1073)
    assert volume == pytest.approx(19729, abs=1)


def test_interpolate_height_to_volume_exact_point():
    assert interpolate_height_to_volume(CALIBRATION_TABLE, 1050) == pytest.approx(19200)


def test_interpolate_height_to_volume_clamped_below_range():
    assert interpolate_height_to_volume(CALIBRATION_TABLE, -50) == pytest.approx(0)


def test_interpolate_height_to_volume_clamped_above_range():
    assert interpolate_height_to_volume(CALIBRATION_TABLE, 5000) == pytest.approx(40000)


def test_interpolate_height_to_volume_no_calibration_returns_none():
    assert interpolate_height_to_volume([], 1000) is None


def test_correct_volume_to_reference_temperature_reference_example():
    """Exemple exact de nouveau-zylo-liquid/Point 5 §5.2 : V=19729L, T=35°C,
    alpha Gasoil=0.00085 -> V15=19394L (PASS attendu, différence 335L)."""
    v15 = correct_volume_to_reference_temperature(19729, 35, 0.00085)
    assert v15 == pytest.approx(19394, abs=1)


def test_correct_volume_to_reference_temperature_at_reference_is_unchanged():
    """À 15°C exactement, aucune correction ne doit être appliquée (FAIL
    attendu si le résultat diffère du volume mesuré)."""
    v15 = correct_volume_to_reference_temperature(19729, 15, 0.00085)
    assert v15 == pytest.approx(19729)


def test_detect_deliveries_reference_example():
    """Scénario exact de nouveau-zylo-liquid/Point 8 §8.5/§8.8 : hausse de
    445mm à 1298mm puis stabilisation à 1293mm, confirmée après 15 min."""
    base = datetime(2026, 1, 1, 10, 0)
    measurements = [
        (base, 445),
        (base + timedelta(minutes=5), 490),
        (base + timedelta(minutes=10), 601),
        (base + timedelta(minutes=15), 748),
        (base + timedelta(hours=1, minutes=10), 1240),
        (base + timedelta(hours=1, minutes=15), 1298),
        (base + timedelta(hours=1, minutes=20), 1295),
        (base + timedelta(hours=1, minutes=25), 1293),
        (base + timedelta(hours=1, minutes=30), 1293),
    ]
    events = detect_deliveries(measurements)
    assert len(events) == 1
    event = events[0]
    assert event["startHeightMm"] == 445
    assert event["startTime"] == base
    assert event["endHeightMm"] == 1293
    assert event["endTime"] == base + timedelta(hours=1, minutes=30)

    # Volume brut console (Point 8.3, sans correction ventes — hors périmètre MVP) :
    # calibration(1293) - calibration(445) = 16075 - 5200 = 10875 L (Point 8.6)
    calibration = [(445, 5200), (1293, 16075)]
    start_volume = interpolate_height_to_volume(calibration, event["startHeightMm"])
    end_volume = interpolate_height_to_volume(calibration, event["endHeightMm"])
    assert end_volume - start_volume == pytest.approx(10875)


def test_detect_deliveries_small_oscillation_is_not_a_delivery():
    """FAIL attendu : une hausse sous le seuil de 50mm n'est jamais une
    livraison — juste une oscillation normale (Point 8.6, critère 2)."""
    base = datetime(2026, 1, 1, 10, 0)
    measurements = [(base, 500), (base + timedelta(minutes=5), 520), (base + timedelta(minutes=10), 505)]
    assert detect_deliveries(measurements) == []


def test_detect_deliveries_does_not_close_prematurely_during_brief_plateau():
    """Un plateau bref (<15 min) pendant la hausse ne doit pas clore la
    livraison — elle doit reprendre et se terminer sur la vraie fin."""
    base = datetime(2026, 1, 1, 10, 0)
    measurements = [
        (base, 445),
        (base + timedelta(minutes=10), 600),  # déclenche (>=50mm)
        (base + timedelta(minutes=15), 800),  # continue de monter
        (base + timedelta(minutes=20), 801),  # plateau bref (diff<5) mais < 15 min
        (base + timedelta(minutes=25), 1000),  # reprend la hausse -> pas encore fini
        (base + timedelta(minutes=30), 1200),
        (base + timedelta(minutes=35), 1200),
        (base + timedelta(minutes=40), 1200),
        (base + timedelta(minutes=45), 1200),  # stabilisation réelle, confirmée à 15 min de (minutes=30)
    ]
    events = detect_deliveries(measurements)
    assert len(events) == 1
    assert events[0]["endHeightMm"] == 1200
    assert events[0]["endTime"] == base + timedelta(minutes=45)


def test_is_leak_detected_threshold():
    """Seuil EPA 0.38 L/H (Point 10 §10.4), strictement supérieur."""
    assert is_leak_detected(0.39) is True  # PASS attendu : détecté
    assert is_leak_detected(0.38) is False  # à l'exact du seuil -> pas de fuite
    assert is_leak_detected(0.37) is False  # FAIL attendu si détecté à tort


def test_compute_leak_rate_lph_reference_example():
    """taux = (V_début - V_fin) / durée — exemple direct de Point 10 §10.3."""
    rate = compute_leak_rate_lph(v_start_corrected=10000, v_end_corrected=9990.5, duration_hours=24)
    assert rate == pytest.approx(0.39583, rel=1e-3)
    assert is_leak_detected(rate) is True


def test_compute_net_corrected_volume_water_subtraction_prevents_false_positive():
    """Correction 1 de Point 10 (algorithme EPA final) : une variation d'eau
    normale ne doit jamais fausser le taux de fuite carburant."""
    calibration = [(0, 0), (2000, 40000)]  # calibration linéaire simple pour l'eau et le carburant
    v_start = compute_net_corrected_volume(calibration, height_mm=1000, water_height_mm=10, temperature_c=None, thermal_expansion_coefficient=None)
    v_end = compute_net_corrected_volume(calibration, height_mm=1000, water_height_mm=12, temperature_c=None, thermal_expansion_coefficient=None)
    # même hauteur carburant totale, seule l'eau a augmenté (condensation normale)
    # -> le volume net carburant doit légèrement diminuer avec l'eau, pas rester une "fuite" du côté carburant pur
    assert v_start > v_end
    assert v_start - v_end == pytest.approx(interpolate_height_to_volume(calibration, 12) - interpolate_height_to_volume(calibration, 10))


def test_compute_net_corrected_volume_thermal_correction_prevents_false_positive():
    """Correction 2 de Point 10 (algorithme EPA final, exemple documenté
    §« La correction pour le simulateur ») : un refroidissement nocturne
    normal de 2°C sur une cuve de Gasoil (α=0.00085) fait naturellement
    baisser la hauteur mesurée de ~31L de contraction physique — sans
    fuite réelle. La correction thermique doit ramener le taux à ~0,
    jamais laisser ces 31L apparaître comme une fuite (FAIL attendu sans
    correction)."""
    calibration = [(0, 0), (2000, 40000)]  # 20 L/mm, linéaire
    alpha_gasoil = 0.00085
    v_brut_start = 18385.0
    contraction_liters = v_brut_start * alpha_gasoil * 2  # refroidissement de 2°C, formule Point 10
    v_brut_end = v_brut_start - contraction_liters
    height_start = v_brut_start / 20
    height_end = v_brut_end / 20

    v_start_corrected = compute_net_corrected_volume(calibration, height_start, None, 28, alpha_gasoil)
    v_end_corrected = compute_net_corrected_volume(calibration, height_end, None, 26, alpha_gasoil)
    rate = compute_leak_rate_lph(v_start_corrected, v_end_corrected, duration_hours=1)

    assert rate == pytest.approx(0, abs=0.5)  # correction thermique neutralise la contraction
    assert is_leak_detected(rate) is False

    # Sans correction thermique (None), les mêmes hauteurs donneraient un
    # taux de ~31 L/H, largement au-dessus du seuil — FAIL attendu si la
    # correction n'était pas appliquée (démontre pourquoi elle est requise).
    rate_uncorrected = compute_leak_rate_lph(v_brut_start, v_brut_end, duration_hours=1)
    assert is_leak_detected(rate_uncorrected) is True


def test_correct_volume_to_reference_temperature_below_reference_increases_volume():
    """En dessous de 15°C, le carburant est contracté : le volume corrigé à
    15°C doit être supérieur au volume mesuré (physiquement cohérent)."""
    v15 = correct_volume_to_reference_temperature(10000, 5, 0.00120)
    assert v15 > 10000
