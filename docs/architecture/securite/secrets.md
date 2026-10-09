# Secrets applicatifs : chiffrement des champs sensibles (T-027)

- **Statut** : implémentation T-027, en attente de vérification.
- **Périmètre** : mot de passe du compte externe Holykell (`zyloLiquidHolykellAccount`).
- **Décision** : option A de `docs/questions/securite/chiffrement-cle-holykell.md` (variable dédiée, obligatoire hors développement, sauvegarde de la clé hors dépôt, suppression de l'ancienne colonne différée).

## 1. Ce qui est chiffré

| Élément | Où | Détail |
|---|---|---|
| Algorithme | `app/core/field_crypto.py` | Fernet (AES-128-CBC + HMAC-SHA256) de la bibliothèque `cryptography`, version figée dans `requirements.txt`. |
| Clé | variable `APP_FIELD_ENCRYPTION_KEY` | Chaîne d'au moins 32 caractères. Étirée par HKDF-SHA256 en clé Fernet de 32 octets (sel et contexte fixes, voir le module). Aucune valeur de clé dans le dépôt, les logs ou les docs. |
| Format stocké | colonne `holykellPasswordChiffre` (Text) | `enc:v1:<jeton Fernet>`. Le préfixe distingue une valeur chiffrée d'une valeur en clair historique. |
| Ancienne colonne | `holykellPassword` | Conservée pendant la transition, rendue nullable. Suppression : tâche distincte, non planifiée. |

Le chiffrement est non déterministe : deux chiffrements du même mot de passe donnent deux valeurs différentes.

## 2. Où le clair existe

- **Déchiffrement** : uniquement dans `app/modules/zylo_liquid/telemetry_sync.py` (`sync_one_account`), au moment de l'appel de connexion à Holykell.
- **Écriture** : `scripts/sync_holykell_live.py` et `app/modules/zylo_liquid/dev_seed.py` chiffrent avant d'écrire.
- **Réponses API** : aucun schéma ne contient le champ (`HolykellAccountSyncStatusResponse` est explicite). Un test vérifie que ni le clair ni le jeton chiffré n'apparaissent dans les réponses.
- **Journaux** : le message d'erreur de la synchronisation ne contient que le nom d'utilisateur et le code HTTP. Un test vérifie l'absence du clair dans les journaux pendant une synchronisation en échec.

## 3. Clé : cycle de vie

- **Obligatoire** hors `development` et `test` : `app/core/config.py` refuse le démarrage si elle est absente, vide ou trop courte.
- **En développement** : absente par défaut. Toute opération de chiffrement échoue alors avec un message explicite (`APP_FIELD_ENCRYPTION_KEY absente`) ; rien n'est écrit en clair par repli.
- **En test** : `tests/conftest.py` pose une clé fictive propre au dépôt de test.
- **Changement de clé** : non prévu par cette tâche. Changer la clé rend illisibles toutes les valeurs chiffrées. Une procédure de rotation (déchiffrer avec l'ancienne, rechiffrer avec la nouvelle) reste à écrire avant tout changement de clé en production.

### Procédure de sauvegarde et de restauration de la clé

La clé ne doit jamais être stockée dans le dépôt, dans une issue, dans un ticket ou dans un journal.

1. **Sauvegarde** : la clé est conservée hors dépôt, dans le gestionnaire de secrets de la personne nommée comme dépositaire (la question `chiffrement-cle-holykell.md` reste ouverte tant que ce nom n'est pas consigné). Au minimum deux copies sous contrôle de personnes distinctes.
2. **Vérification** : après chaque changement de la clé, le dépositaire confirme par écrit que la copie est lisible.
3. **Restauration** : sur une base jetable (jamais une base réelle), poser la clé restaurée dans `APP_FIELD_ENCRYPTION_KEY`, puis lire un compte chiffré. Une lecture réussie valide la sauvegarde. Un échec signifie que la sauvegarde ne correspond pas à la clé utilisée.
4. **Perte de la clé** : les comptes Holykell chiffrés deviennent inutilisables. Il faut alors ressaisir les mots de passe Holykell (action de l'opérateur, consignée dans `docs/questions/securite/rotation-credentials.md`).

## 4. Migration

### 4.1 Schéma (Alembic)

Révision `5b1c9e7d3a4f`, après `e2f3a4b5c6d7` :

- `upgrade` : ajoute `holykellPasswordChiffre` (nullable) et rend `holykellPassword` nullable. Additive, aucune perte.
- `downgrade` : déchiffre les lignes sans valeur en clair (clé requise), réremplit `holykellPassword`, rétablit NOT NULL et retire la colonne chiffrée. Sans clé utilisable, le downgrade échoue sans rien modifier.

### 4.2 Données existantes (script)

`scripts/chiffrer_mots_de_passe_holykell.py`, par lots (`--lot`, défaut 100) :

```bash
.venv/bin/python scripts/chiffrer_mots_de_passe_holykell.py --dry-run          # compte, n'écrit rien
.venv/bin/python scripts/chiffrer_mots_de_passe_holykell.py                    # chiffre, conserve le clair
.venv/bin/python scripts/chiffrer_mots_de_passe_holykell.py --effacer-clair    # vide le clair après vérification
```

- **Idempotent** : une ligne déjà chiffrée n'est pas réécrite ; une relance ne modifie rien.
- **Vérification** : chaque valeur chiffrée est déchiffrée et comparée au clair avant écriture. Un écart arrête le script sans écraser la ligne.
- **Sans clé** : le script s'arrête avant toute lecture écrite.
- **Sortie** : compteurs et identifiants uniquement, jamais de valeur.
- **Ordre recommandé** : sauvegarde de la base, `--dry-run`, migration sans `--effacer-clair`, contrôle de synchronisation Holykell, puis `--effacer-clair` sur accord écrit.

Le script ne doit être lancé sur aucune base réelle tant que la procédure de sauvegarde de la clé n'a pas été validée.

### 4.3 Retour arrière

- Tant que `--effacer-clair` n'a pas été lancé, la colonne en clair reste complète : le retour arrière ne nécessite pas la clé.
- Après `--effacer-clair`, le retour arrière (`alembic downgrade -1`) nécessite la clé pour restaurer les valeurs.

## 5. Compatibilité pendant la transition

`app/core/field_crypto.lire_champ` lit la colonne chiffrée si elle est renseignée, sinon la colonne en clair historique. Ce repli permet de lire les comptes non encore migrés. Il sera retiré avec la suppression de l'ancienne colonne.

## 6. Limites connues

- L'ancienne colonne `holykellPassword` existe toujours, et contient les valeurs en clair tant que `--effacer-clair` n'a pas été lancé.
- Le repli de lecture sur le clair est volontairement conservé pendant la transition (exigence de compatibilité). Il ne disparaît qu'avec la suppression de la colonne.
- La procédure de sauvegarde de la clé nécessite une personne nommée (question ouverte). Ce document décrit la procédure, il ne la remplace pas.
- `scripts/sync_holykell_live.py` garde un mot de passe de démonstration par défaut (`HOLYKELL_SYNC_PASSWORD`, valeur de repli dans le script). Ce script est un outil de développement ; il n'est pas concerné par le chiffrement de production et doit être nettoyé séparément.
- Aucune rotation du mot de passe Holykell n'est faite par ce code : elle reste une action de l'opérateur.
