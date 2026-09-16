"""Algorithmes de tracking GPS des camions-citernes — extraits de
`app/modules/zylo_liquid/algorithms.py` (2026-09-15, Phase 2 de la
migration monolithe modulaire, voir ARCHITECTURE.md). Logique inchangée,
seul l'emplacement bouge. Comme dans `zylo_liquid/algorithms.py`, ces
fonctions sont les seules autorisées à porter cette logique — jamais
réimplémentées à l'intérieur d'un endpoint."""

import math
from datetime import timedelta

# Détection d'arrêt camion (mission « tracking », étape 1) — constantes
# fixes pour tout le réseau (un camion dessert plusieurs stations, pas de
# point d'ancrage cohérent pour une dérogation par station — décision
# explicite du commanditaire). Valeurs de démarrage prudentes, à calibrer
# avec des positions réelles une fois le matériel déployé.
TRUCK_STOP_RADIUS_METERS_DEFAULT = 150.0
TRUCK_STOP_STABILIZATION_MINUTES_DEFAULT = 10.0

# Filtre de plausibilité à l'ingestion (2026-09-13, incident réel) — un
# boîtier/téléphone peut ponctuellement renvoyer un point aberrant (perte de
# précision GPS, multi-trajet radio en zone urbaine dense) à des centaines de
# mètres du reste du trajet, avec une vitesse implicite bien au-delà de ce
# qu'un camion-citerne peut atteindre. Non filtrés, ces points créent des
# lignes « impossibles » sur la carte (constaté en conditions réelles : 8
# points à ~40 km/h alors que le trajet réel était une marche à 3-6 km/h).
# Seuil large et prudent (jamais calibré sur route réelle) : mieux vaut
# rejeter un point trop rarement qu'exclure un vrai déplacement rapide.
TRUCK_POSITION_MAX_PLAUSIBLE_SPEED_KMH_DEFAULT = 150.0


def is_position_plausible(
    prev_recorded_at,
    prev_latitude: float,
    prev_longitude: float,
    recorded_at,
    latitude: float,
    longitude: float,
    max_speed_kmh: float = TRUCK_POSITION_MAX_PLAUSIBLE_SPEED_KMH_DEFAULT,
) -> bool:
    """Rejette un point dont la vitesse implicite depuis le point précédent
    du même boîtier dépasse `max_speed_kmh` — jamais appliqué au tout premier
    point d'un boîtier (rien à comparer, toujours plausible). Écart de temps
    nul ou négatif entre les deux points : jamais plausible (positions
    dupliquées/désordonnées ne doivent pas être comparées comme un
    déplacement)."""
    elapsed_seconds = (recorded_at - prev_recorded_at).total_seconds()
    if elapsed_seconds <= 0:
        return False
    distance_meters = _haversine_distance_meters(prev_latitude, prev_longitude, latitude, longitude)
    implied_speed_kmh = (distance_meters / elapsed_seconds) * 3.6
    return implied_speed_kmh <= max_speed_kmh


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
    discipline de confirmation que `_scan_deliveries` (module zylo_liquid) :
    ancre stable + confirmation après N minutes, avec la distance à l'ancre
    comme mesure à la place de la hauteur de cuve. L'ancre ne bouge que tant
    qu'aucune fenêtre de stabilisation n'est en cours, pour ne jamais dériver
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


# Écart minimal entre la distance aux deux lieux candidats les plus
# proches pour trancher automatiquement (scénario 5, validé avec le
# commanditaire) — en dessous, l'arrêt part en file de réconciliation
# humaine plutôt que d'être deviné.
TRUCK_STOP_LOCATION_AMBIGUITY_THRESHOLD = 0.20


def match_truck_stop_to_locations(
    stop_latitude: float,
    stop_longitude: float,
    locations: list[tuple],
) -> dict:
    """Reconnaissance automatique d'un arrêt par rapport aux lieux nommés
    (scénario 5) — réutilise `_haversine_distance_meters`, jamais un
    nouvel algorithme. `locations` : liste de (id, latitude, longitude,
    radiusMeters) des lieux actifs de l'organisation.

    Retourne un de ces trois résultats :
    - {"status": "matched", "locationId": ...} — un seul lieu dans le
      rayon, ou le plus proche l'emporte avec un écart >= 20% sur le
      deuxième candidat.
    - {"status": "ambiguous", "candidateIds": [...]} — au moins deux
      lieux dans le rayon, écart de distance < 20%, réconciliation requise.
    - {"status": "unmatched"} — aucun lieu ne couvre cette position."""
    candidates = [
        (loc_id, _haversine_distance_meters(stop_latitude, stop_longitude, lat, lon))
        for loc_id, lat, lon, radius in locations
        if _haversine_distance_meters(stop_latitude, stop_longitude, lat, lon) <= radius
    ]
    if not candidates:
        return {"status": "unmatched"}
    if len(candidates) == 1:
        return {"status": "matched", "locationId": candidates[0][0]}

    candidates.sort(key=lambda c: c[1])
    closest_id, closest_distance = candidates[0]
    _, second_distance = candidates[1]
    if second_distance == 0 or (second_distance - closest_distance) / second_distance < TRUCK_STOP_LOCATION_AMBIGUITY_THRESHOLD:
        return {"status": "ambiguous", "candidateIds": [c[0] for c in candidates]}
    return {"status": "matched", "locationId": closest_id}
