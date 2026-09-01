"""Niveau 1 — tests unitaires algorithmiques (Point 4 « Valider une API
comme les titans »). Aucune base de données, aucun réseau : la logique pure
seule, avec des valeurs de référence exactes tirées des documents source."""

import pytest

from app.modules.zylo_liquid.algorithms import correct_volume_to_reference_temperature, interpolate_height_to_volume

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


def test_correct_volume_to_reference_temperature_below_reference_increases_volume():
    """En dessous de 15°C, le carburant est contracté : le volume corrigé à
    15°C doit être supérieur au volume mesuré (physiquement cohérent)."""
    v15 = correct_volume_to_reference_temperature(10000, 5, 0.00120)
    assert v15 > 10000
