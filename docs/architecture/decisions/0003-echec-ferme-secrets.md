# ADR 0003 : Refus de démarrer hors développement avec un secret par défaut

- **Date** : 2026-10-08 (T-002).
- **Statut** : Acceptée ; implémentation à vérifier (T-002, « À vérifier »).
- **Source** : `app/core/config.py` (valeur de repli `FALLBACK_JWT_SECRET`, validation au démarrage), [`docs/plans/taches/T-002-refus-demarrage-secrets.md`](../../plans/taches/T-002-refus-demarrage-secrets.md).

## Contexte

Une valeur de repli (`changeme-generate-a-real-random-secret`) servait de secret JWT et de secret de signature des URL de stockage. Une configuration oubliée pouvait démarrer en production avec une clé publique.

## Décision

Échec fermé : hors `development` et `test`, le démarrage est refusé (`ConfigurationSecretError`) si un secret est absent ou égal à la valeur de repli. Même règle pour `EMAIL_BACKEND=console` et `memory`, admis seulement dans l'environnement qui convient.

## Conséquences

- Un déploiement mal configuré échoue au démarrage, pas à la première requête.
- Les tests posent des secrets propres au dépôt de test.

## Alternatives écartées

Avertissement dans les journaux : trop facile à ignorer, rejeté.
