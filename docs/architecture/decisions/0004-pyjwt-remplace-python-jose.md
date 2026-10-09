# ADR 0004 : PyJWT remplace python-jose

- **Date** : 2026-10-08 (T-015).
- **Statut** : Acceptée (T-015 « Terminée »).
- **Source** : `requirements.txt` (commentaire T-015), `app/core/security.py`.

## Contexte

`python-jose` 3.5.0 gardait une vulnérabilité sans correctif (CVE-2026-85394) et tirait `ecdsa`, lui-même sans correctif (PYSEC-2026-1325).

## Décision

Remplacer `python-jose` par `PyJWT==2.15.1`. Le format HS256 est identique : les jetons déjà émis restent valides.

## Conséquences

- Mise à jour du module de sécurité uniquement ; pas de changement d'API externe.
- À reprendre à chaque audit de dépendances (`pip-audit`).
