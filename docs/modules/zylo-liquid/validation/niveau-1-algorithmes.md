# Niveau 1 : tests unitaires algorithmiques

> Découpé depuis [`docs/archive/zylo-liquid/validation_log.md`](../../../archive/zylo-liquid/validation_log.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

## Niveau 1 — Tests unitaires algorithmiques

### interpolate_height_to_volume — VALIDÉ le 2026-09-01

| Cas | Entrée | Attendu | Obtenu | Statut |
|-----|--------|---------|--------|--------|
| Cas de référence exact | Table Point 2 §2.4, H=1073mm | 19729 L (±1) | 19729 L | ✓ (PASS) |
| Point exact de la table | H=1050mm | 19200 L | 19200 L | ✓ |
| Hors plage, en dessous | H=-50mm | Borné au premier point (0 L) | 0 L | ✓ |
| Hors plage, au dessus | H=5000mm | Borné au dernier point (40000 L) | 40000 L | ✓ |
| Aucune calibration | Table vide | `None` (jamais un volume inventé) | `None` | ✓ |

Source exacte : `nouveau-station-simulator/nouveau-zylo-liquid/Point 2 —
La table de calibration.md` §2.4. Preuve : `tests/test_zylo_liquid_algorithms.py`.

### correct_volume_to_reference_temperature — VALIDÉ le 2026-09-01

| Cas | Entrée | Attendu | Obtenu | Statut |
|-----|--------|---------|--------|--------|
| Cas de référence exact | V=19729L, T=35°C, α=0.00085 (Gasoil) | 19394 L (±1) | 19394 L | ✓ (PASS) |
| À la température de référence | V=19729L, T=15°C | Inchangé (19729 L) — **FAIL si différent** | 19729 L | ✓ |
| Sous la référence | V=10000L, T=5°C, α=0.00120 | Volume corrigé > volume mesuré (contraction) | Confirmé (10060 L) | ✓ |

Source exacte : `nouveau-station-simulator/nouveau-zylo-liquid/Point 5 —
Température et densité.md` §5.2. Preuve : `tests/test_zylo_liquid_algorithms.py`.

### detect_deliveries — VALIDÉ le 2026-09-01

| Cas | Entrée | Attendu | Obtenu | Statut |
|-----|--------|---------|--------|--------|
| Cas de référence exact | Scénario Point 8 §8.5/§8.8 (445→1298→stable 1293) | 1 livraison, start=445mm, end=1293mm | Confirmé | ✓ (PASS) |
| Volume brut combiné à l'interpolation | calibration(1293)-calibration(445) | 10875 L (Point 8.6, sans correction ventes) | 10875 L | ✓ |
| Oscillation sous le seuil (50mm) | Hausse de 20mm | Aucune livraison détectée | `[]` | ✓ (FAIL attendu si détectée à tort) |
| Plateau bref pendant la hausse (<15min) | Hausse→plateau 5min→reprise→fin réelle | 1 seule livraison, sur la vraie fin | Confirmé | ✓ |

Source exacte : `nouveau-station-simulator/nouveau-zylo-liquid/Point 8 —
Détection de livraison (version corrigée et complète).md` §8.3, §8.5, §8.6,
§8.8. Seuils confirmés par Point 3 §10 (code Odoo audité : hausse ≥50mm,
stabilité <5mm, confirmation 15min — jamais les valeurs d'exemple
génériques 500L/30min de §8.6). Preuve : `tests/test_zylo_liquid_algorithms.py`.

### compute_net_corrected_volume / compute_leak_rate_lph / is_leak_detected — VALIDÉ le 2026-09-01

| Cas | Entrée | Attendu | Obtenu | Statut |
|-----|--------|---------|--------|--------|
| Seuil EPA (frontière) | 0.38 exactement | Pas de fuite (strictement supérieur requis) | Confirmé | ✓ |
| Seuil EPA (au-dessus) | 0.39 | Fuite détectée | Confirmé (PASS) | ✓ |
| Seuil EPA (en dessous) | 0.37 | Pas de fuite | Confirmé (FAIL attendu si détectée à tort) | ✓ |
| Taux direct (exemple Point 10 §10.3) | ΔV=9.5L/24h | ≈0.396 L/H, fuite détectée | Confirmé | ✓ |
| Faux positif eau (condensation) | Eau +2mm entre début et fin | Volume net carburant diminue en cohérence avec l'eau, pas une fuite fictive isolée | Confirmé | ✓ |
| Faux positif thermique (exemple documenté) | Refroidissement 2°C, cuve 18385L Gasoil α=0.00085 | Sans correction : ~31L/H « fuite » fictive détectée (FAIL) ; avec correction : ≈0, pas de fuite (PASS) | Confirmé (les deux résultats) | ✓ |

Source exacte : `nouveau-station-simulator/nouveau-zylo-liquid/Point 10 —
Détection de fuite.md`, section finale (« Correction de l'algorithme du
point 10 » — version EPA corrigée, pas l'algorithme initial simplifié de
§10.3). Seuil 0.38 L/H confirmé §10.4 (standard EPA). Preuve :
`tests/test_zylo_liquid_algorithms.py`.

### evaluate_threshold_alarms — VALIDÉ le 2026-09-01

| Cas | Entrée | Attendu | Obtenu | Statut |
|-----|--------|---------|--------|--------|
| Cas de référence exact | Point 13 §13.5 : H_carburant=195mm, H_eau=0mm, Low_alarm=200mm | `["level_low"]` | Confirmé | ✓ (PASS) |
| Niveau haut supersede la pré-alarme | H_net=950, alarm=900, alert=800 | `["level_high"]` uniquement | Confirmé (FAIL attendu si les deux) | ✓ |
| Pré-alarme seule | H_net=850, alarm=900, alert=800 | `["level_high_pre_alarm"]` | Confirmé | ✓ |
| Eau indépendante du niveau | Niveau normal + eau au-dessus du seuil | `["water"]` uniquement | Confirmé | ✓ |
| Plage normale | Toutes valeurs sous les seuils | `[]` | Confirmé (FAIL attendu si alerte à tort) | ✓ |

Source exacte : `nouveau-station-simulator/nouveau-zylo-liquid/Point 13 —
Alarmes.md` §13.4-13.5. Preuve : `tests/test_zylo_liquid_algorithms.py`.

Le prochain algorithme à exercer sera défini au moment de construire
l'endpoint suivant (snapshot réseau, item 13).

---
