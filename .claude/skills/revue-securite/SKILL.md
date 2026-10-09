---
name: revue-securite
description: Relit un changement sous l'angle sécurité (secrets, IAM, entrées, journaux, téléversements, chiffrement) et rend des constats classés.
when_to_use: Avant livraison d'un changement touchant auth, rbac, config, fichiers, intégrations externes ou données sensibles.
allowed-tools: Read Grep Glob Bash
---

# Revue de sécurité

Périmètre : `git diff remy...HEAD` (ou fichiers indiqués). Lecture seule.

Contrôles :
1. Secrets : aucune valeur de clé, mot de passe ou jeton dans le diff (`grep -rniE "password|secret|token|api_key" <diff>`).
2. Configuration : pas de valeur par défaut de secret hors développement (ADR 0003, `app/core/config.py`).
3. Chiffrement : les champs sensibles passent par `app/core/field_crypto.py` ; aucun clair dans les réponses ni les journaux (ADR 0005).
4. IAM : chaque route est gardée ; refus par défaut ; `organization_id` vérifié (skill `roles-permissions`).
5. Entrées : validation Pydantic ; téléversements limités en type et en taille (`app/shared/file_types.py`).
6. Erreurs : pas de détail interne (trace, requête SQL) renvoyé au client.
7. Dépendances : `requirements.txt` sans paquet connu vulnérable (dernier `pip-audit` consigné).

Classe chaque constat : bloquant, important, mineur, avec fichier:ligne. Ne corrige pas : propose.
