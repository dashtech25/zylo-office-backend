# T-029 : Fiabilité des tâches de fond (verrou) et des exceptions avalées

- **Statut** : Planifiée · **Priorité** : P2 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : backend · **Type** : refactor
- **Branche suggérée** : `fix/T-029-fiabilite` · **Base de test** : `zylo_t029_test` · **Ports** : back 3129
- **Dépendances** : T-028, T-034
- **Décisions requises** : aucune

## Objectif
Les boucles de fond (sondage Holykell, balayage structurel) tournent une seule fois à l'échelle, grâce à un verrou PostgreSQL. Les exceptions avalées sans trace sont restreintes et journalisées. Les journaux ne contiennent aucune valeur sensible.

## Problèmes résolus
- BCK-016 (boucles dupliquées par processus), BCK-017 (exceptions avalées), REV-S-21 (secrets dans les journaux)

## Dépendances : justification
T-028 (seeds sortis du démarrage), T-034 (les `except` de `zylo_liquid/service.py` sont traités après découpe du lot 1, pour ne pas déplacer le même code deux fois).

## Fichiers / modules concernés
- `app/main.py` (démarrage des boucles, lignes 116 et 126)
- `app/integrations/holykell/` (boucle de sondage)
- `app/shared/storage.py` (lignes 32, 122), `app/location/service.py` (lignes 431, 509, 523)
- `app/modules/zylo_liquid/telemetry_sync.py` (lignes 144 à 194)
- `app/modules/zylo_liquid/service.py` (lignes 2585, 3091, 5432, 5436, 7081, 14471, après découpe)

## Stratégie
1. `pg_try_advisory_lock` par boucle : une seule instance active par cycle.
2. Restreindre les exceptions attrapées aux erreurs attendues (réseau, parsing), journaliser le reste avec `logger.exception` et un contexte (identifiant, opération), sans argument sensible.
3. Test de fuite : capture des journaux pendant les parcours de connexion, de création de compte et d'appel Holykell ; aucune valeur de mot de passe, jeton ou `holykellPassword` n'apparaît.

## Tests attendus
- Deux processus lancent la boucle : une seule exécution par cycle (test d'intégration).
- Erreur injectée dans la télémétrie : journalisée, pas silencieuse.
- Un test par exception traitée (liste dans la PR).
- Test de fuite de journaux (REV-S-21).

## Critères d'acceptation
- Aucun `except Exception: pass` dans les fichiers listés.
- Verrou documenté dans `docs/architecture/exploitation.md`.
- Test de fuite de journaux vert.

## Risque et retour arrière
Moyen : un `except` restreint peut laisser remonter une erreur auparavant silencieuse. Mesurer avant de restreindre. Retour arrière : revert par fichier.

## Livrable documentaire
- `docs/architecture/exploitation.md` (créé)

## Parallélisable avec
T-016, T-027 (séquencer avec T-035a sur `zylo_liquid/service.py`).
