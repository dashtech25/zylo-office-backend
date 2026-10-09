# T-027 : Chiffrer le mot de passe du compte Holykell, avec clé de secours et procédure de restauration

- **Statut** : À vérifier · **Priorité** : P1 · **Vague** : 1 · **Taille** : L · **Dépôt(s)** : backend · **Domaine** : zylo-liquid · **Type** : security
- **Branche suggérée** : `fix/T-027-secrets-holykell` · **Base de test** : `zylo_t027_test` · **Ports** : back 3127
- **Dépendances** : T-002
- **Décisions requises** : `securite/chiffrement-cle-holykell.md` (recommandation : variable dédiée, procédure de sauvegarde de clé hors dépôt)

## Objectif
Le mot de passe du compte externe Holykell est stocké en clair (`holykellPassword`, `models.py` ligne 74). Le chiffrer au niveau applicatif avec la clé déclarée par T-002, migrer les valeurs existantes, et consigner la procédure de sauvegarde et de restauration de la clé. La suppression de l'ancienne colonne n'est **pas** dans cette tâche (voir la section « Suppression différée »).

## Problèmes résolus
- BCK-007 (P1), REV-S-09 (colonne laissée en clair), REV-S-21 (valeur dans les journaux), REV-A-18 (procédure de perte de clé)

## Dépendances : justification
- T-002 : clé de chiffrement obligatoire déclarée par T-002 et utilisée ici.
- Retirées (confort ou CI, pas de prérequis technique) : T-001 (rotation de credentials : processus, pas de code) ; T-005 (confort).

## Fichiers / modules concernés
- `app/modules/zylo_liquid/models.py` (ligne 74), `schemas.py` (requête)
- `app/modules/zylo_liquid/service.py` (écriture, lignes 4262 et 4280)
- `app/modules/zylo_liquid/telemetry_sync.py` (lecture pour l'appel externe)
- Migration additive : colonne chiffrée, backfill par lots, vérification

## Stratégie
1. Chiffrement authentifié avec la clé `APP_FIELD_ENCRYPTION_KEY` (T-002). Aucune valeur de clé dans le dépôt.
2. Migration en trois temps : ajout de la colonne chiffrée ; backfill par lots avec vérification (nombre de lignes égal, déchiffrement contrôlé) ; bascule de la lecture vers la colonne chiffrée.
3. Procédure de sauvegarde de la clé hors dépôt, et test de restauration sur base jetable.
4. Rotation du mot de passe Holykell : action de l'opérateur, consignée dans `rotation-credentials.md`, avec propriétaire et date.

## Suppression différée
La suppression de l'ancienne colonne `holykellPassword` est une tâche séparée, non planifiée dans ce plan. Elle ne démarre que sur accord écrit du commanditaire, après une période d'observation et une sauvegarde vérifiée (règle du plan §2 : pas de suppression de colonne en production sans accord).

## Tests attendus
- Aller-retour chiffrement/déchiffrement ; valeur chiffrée différente de la valeur claire.
- Migration sur base de test avec données de démonstration : toutes les lignes migrées.
- Synchronisation Holykell simulée : la valeur déchiffrée est transmise au mock.
- Capture des journaux pendant la synchronisation : aucune occurrence de la valeur claire.
- Test de restauration : base jetable, clé restaurée depuis la procédure, lecture réussie.

## Critères d'acceptation
- Plus aucune lecture de la colonne en clair dans le code.
- Clé absente hors développement : démarrage refusé (T-002).
- Procédure de sauvegarde et de restauration de la clé écrite et testée.
- Décision de suppression différée consignée.

## Risque et retour arrière
Élevé : si la clé est perdue, les comptes Holykell deviennent inutilisables. Une migration interrompue laisse des valeurs mixtes. Retour arrière : la colonne en clair reste en place tant que la bascule n'est pas faite ; la bascule est réversible par configuration.

## Livrable documentaire
- `docs/architecture/securite/secrets.md` (créé)
- `docs/questions/securite/chiffrement-cle-holykell.md`

## Parallélisable avec
T-028, T-029 (séquencer avec T-034, puis T-035a à T-035e, sur `zylo_liquid/service.py`).
