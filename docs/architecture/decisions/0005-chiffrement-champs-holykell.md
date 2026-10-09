# ADR 0005 : Chiffrement du mot de passe Holykell

- **Date** : 2026-10-09 (T-027, recommandation appliquée provisoirement).
- **Statut** : Acceptée, provisoire. Suppression de l'ancienne colonne en clair : non planifiée.
- **Source** : [`docs/architecture/securite/secrets.md`](../securite/secrets.md), [`docs/questions/securite/chiffrement-cle-holykell.md`](../../questions/securite/chiffrement-cle-holykell.md) (option A).

## Contexte

Le mot de passe du compte externe Holykell était stocké en clair dans `holykellPassword`.

## Décision

Chiffrement Fernet (bibliothèque `cryptography`, version figée) avec une clé dans la variable `APP_FIELD_ENCRYPTION_KEY`, obligatoire hors développement et test. Valeur stockée : `enc:v1:<jeton>` dans `holykellPasswordChiffre`. Le clair n'existe que pendant l'appel de synchronisation.

## Conséquences

- Perte de la clé : les comptes chiffrés deviennent inutilisables ; il faut ressaisir les mots de passe.
- Sauvegarde de la clé : hors dépôt, confiée à une personne nommée (question ouverte).
- Changement de clé : procédure de rotation à écrire avant toute opération en production.

## Alternatives écartées

Gestionnaire de secrets ou KMS : plus sûrs, mais dépendance d'infrastructure hors périmètre actuel (options B et C de la question).
