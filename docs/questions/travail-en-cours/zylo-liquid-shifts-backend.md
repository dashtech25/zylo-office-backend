# Intégrer le lot zylo_liquid « shifts, planning, pompes, caisse, présence, passation » ?

- **État** : ouverte (2026-10-09). Rien n'est intégré. Le lot reste sur `wip/2026-10-08-snapshot-backend` et `wip/2026-10-08-snapshot-frontend`.
- **Lots concernés** : backend B-L2 (13 migrations, `models.py`, `schemas.py`, `service.py`, `router.py`, `permissions.py`, `seed.py`, ~11 tests), B-L3 (jauge de cuves, migration `c8d0e2f4a516`), B-L4 (`algorithms.py`) ; frontend F-L6 (~47 écrans) et F-L7 (écrans modifiés).

## Question

Dans quel ordre et sous quelles conditions faut-il intégrer ce lot de fonctionnalités, qui n'est pas encore dans `remy` ?

## Contexte

- Le snapshot part de `72dca7d` (backend). `remy` a 82 commits de plus, dont T-021, T-022, T-027 (chiffrement du mot de passe Holykell : `holykellPasswordChiffre`, migration `5b1c9e7d3a4f`, nouvelle tête alembic) et les hooks d'activation (`61c514b`).
- Les 13 migrations du snapshot forment une chaîne linéaire qui part de `e2f3a4b5c6d7`. Elles doivent être rebasées sur `5b1c9e7d3a4f`.
- **Régression bloquante** : `app/modules/zylo_liquid/service.py` du snapshot (vers la ligne 4280) crée `HolykellAccount(holykellPassword=data.holykellPassword)` en clair. T-027 interdit ce chemin : le champ doit être `holykellPasswordChiffre`.
- Les services créent des comptes salariés avec un mot de passe temporaire (`secrets.token_urlsafe(9)`) renvoyé dans la réponse API (`temporaryPassword`, création unitaire et import en masse). À valider avec le produit : canal de remise du mot de passe, ou lien d'activation comme pour T-021.
- Les nouvelles permissions (`zyloLiquid.shiftPlanning`, `zyloLiquid.pump`, etc.) doivent être alignées sur les rôles par module de T-018. Le fichier `permissions.py` est lié à B-L5 (question séparée).
- Les tests de ce lot n'ont pas été exécutés (le lot touche `models.py` et `roles_seed.py`, déjà modifiés dans `remy`).

## Options

1. **Intégrer en sous-lots** : d'abord les migrations et modèles rebasés, puis le service corrigé (chiffrement Holykell, mot de passe temporaire traité), puis les routeurs et les tests, puis le frontend.
2. **Reporter** le lot jusqu'à la fusion de T-010 et T-018 (évite de réécrire les autorisations deux fois).
3. **Archiver** sans intégrer, et reprendre les fonctions au cas par cas dans de nouvelles tâches.

## Recommandation vérifiée

Option 1, après fusion de T-018 (sinon les permissions du lot seront réécrites). Vérifié : le chiffrement de T-027 est présent dans `remy` (`models.py` ligne 74), le snapshot ne l'utilise pas (ligne 4280). Le correctif est donc nécessaire avant toute fusion.

## Décision attendue

- Valider l'option (1, 2 ou 3).
- Valider le mécanisme de remise du mot de passe temporaire des salariés.
