# zylo_liquid : architecture du service (découpe, T-034)

- **Statut** : lot 1 réalisé (stations et cuves). Les lots suivants (T-035a à T-035e) restent à faire.
- **Problème** : ARC-004 (module « god file »). `service.py` concentre encore la logique de tous les sous-domaines.
- **Référence de mesure** (2026-10-09, avant lot 1) : `service.py` 7 092 lignes, 243 fonctions de premier niveau ; `schemas.py` 2 150 lignes ; `router.py` 2 339 lignes. Les chiffres 15 681 lignes et 504 fonctions cités dans `docs/audit/architecture.md` ne correspondent pas à ce dépôt : à corriger dans l'audit.

## Structure après le lot 1

| Fichier | Rôle | Lignes |
|---|---|---|
| `service.py` | Façade de réexport + sous-domaines pas encore extraits (prix, état courant, livraisons, fuites, alertes, caisse, réconciliation, ventes, produits, personnel, fournisseurs, réglementation) | 6 298 |
| `common.py` | Helpers et état partagés entre `service.py` et les sous-paquets (cache des produits carburant, `_check_declaration_scope`) | 27 |
| `stations/service.py` | Stations, services de station, politique de prix, produits carburant (catalogue et par station) | 425 |
| `stations/schemas.py` | Schémas des stations et des produits carburant | 247 |
| `tanks/service.py` | Cuves, pompes, correspondances capteurs, calibration | 488 |
| `tanks/schemas.py` | Schémas des cuves, pompes, capteurs et calibration | 136 |
| `schemas.py` | Façade de réexport des schémas déplacés, plus les schémas restants | 1 820 |
| `router.py` | Inchangé par le lot 1 (aucune route, aucune garde modifiée) | 2 339 |

Fonctions déplacées : 18 stations, 16 cuves, 1 helper partagé (plus le cache et la constante `_TANK_PRODUCT_UPDATE_FIELDS`). Classes et validateurs déplacés : 27.

## Sens de dépendance

```text
router.py  ->  service.py (façade)  ->  stations/ , tanks/ , common.py
tanks/     ->  stations/ , common.py
stations/  ->  common.py
```

- Un sous-paquet n'importe jamais `service.py` ni `schemas.py` : ce serait un cycle. Le contrat `acyclic_siblings` (`.importlinter`, `modules-metier-acyclic-siblings`) le vérifie.
- `stations/` n'importe jamais `tanks/`.
- `location` et `alerts` ne peuvent importer ni `service`, ni `router`, ni `schemas`, ni `stations`, ni `tanks`, ni `common` de zylo_liquid (contrats `*-never-imports-zylo-liquid-or-zylo-tanker-logic`).
- `common.py` ne contient que des helpers sans règle de domaine.

## Règle de découpe pour les lots suivants

1. **Filet d'abord** : ajouter les fonctions déplacées à la liste de `tests/test_zylo_liquid_facade_lot1.py` (ou à un fichier équivalent du lot) pour figer leurs signatures. Vérifier que les tests HTTP du sous-domaine passent avant le déplacement.
2. **Fermeture des dépendances** : pour le groupe à déplacer, calculer par AST les fonctions de `service.py` qu'il appelle. Chaque dépendance est soit déplacée avec le groupe, soit, si c'est un helper sans règle de domaine, placée dans `common.py`. Si une dépendance reste dans `service.py`, le groupe est trop grand : le réduire.
3. **Corps à l'identique** : copier les segments source, sans réécriture. Une comparaison AST (`ast.dump`) avant et après doit être égale pour chaque fonction déplacée.
4. **Imports du sous-paquet** : importer les schémas depuis le sous-paquet de schémas, jamais depuis `zylo_liquid.schemas`.
5. **Façade** : `service.py` et `schemas.py` réexportent tous les noms déplacés, pour que `router.py`, `dev_seed.py`, `telemetry_sync.py` et les tests ne changent pas.
6. **Contrôles** : `pytest` complet (aucun échec de plus que la référence), `lint-imports` (13 contrats), comparaison de l'OpenAPI avant et après (sortie identique), `tests/test_route_inventory.py` et `tests/test_gardes_permissions_routes.py`.
7. **Mise à jour** de ce document (tableau de structure et liste ci-dessous).

Ne pas toucher à `router.py` dans un lot de découpe de services : une route déplacée change l'ordre d'enregistrement et les gardes. Les routes sont découpées dans un lot dédié, avec leur propre matrice d'autorisation.

## Reste à découper (ordre prévu par les fiches T-035a à T-035e)

| Lot | Sous-domaine | Paquet cible |
|---|---|---|
| T-035a | Caisse et shifts | `cash/` |
| T-035b | Livraisons et rapprochements | `deliveries/` |
| T-035c | Réglementation et déclarations | `regulation/` |
| T-035d | Ventes et produits | `sales/` |
| T-035e | Reste (personnel, fournisseurs, état courant, mesures, prix) | sous-paquets existants ou `common/` |

Fonctions restantes à découper par ces lots : voir les fiches `docs/plans/taches/T-035*.md`. Le critère d'acceptation de T-035e (service.py sous 2 000 lignes, ou reliquat listé) n'est pas encore atteint.
