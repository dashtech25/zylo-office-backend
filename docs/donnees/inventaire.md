# Inventaire des données et classes de rétention (BE-242)

Référence du code : `app/data_inventory/` (service, modèle, registre, permission, seed) et
migration `alembic/versions/f0e1d2c3b4a5_data_inventory.py`.

## Ce qui est contrôlé

| Règle | Où | Effet en cas d'écart |
|---|---|---|
| Chaque table du schéma migré figure au registre | `tables_sans_inventaire` | le contrôle échoue (liste des tables manquantes) |
| Chaque entrée déclare une `classe` et un `proprietaire` | `valider_champ` | anomalie renvoyée à l'appelant, entrée rejetée |
| Une classe sans durée décidée vaut NON DÉFINI et bloque la suppression automatique | `retention_decidee`, `suppression_automatique_autorisee` | suppression manuelle et tracée uniquement |
| La lecture du registre exige `donnees.inventaire.lire` | `lire_inventaire` | 403 `permission_denied` avant toute requête |

Aucune route HTTP n'est déclarée : BE-242 ne porte aucune route.

## Table `data_inventory`

Une ligne par couple `(objet, champ)`, contrainte d'unicité `uq_data_inventory_objet_champ`.

- `objet` : nom réel de la table ; `champ` : colonne, ou `*` pour l'objet entier.
- `classe`, `proprietaire` : obligatoires au contrôle.
- `retentionJours` : entier positif, ou NULL pour NON DÉFINI.
- `finalite`, `tenantScope`, `lecteurs`, `transfert`, `sauvegarde`, `export`, `suppression` : texte libre.

## Registre provisoire

`app/data_inventory/registre.py` liste les 123 tables du schéma avec une classe et un
propriétaire. Ces valeurs sont **provisoires** : elles suivent la nature des données, sans
validation du responsable données. Aucune durée de rétention n'est décidée, donc toutes
restent NON DÉFINI et bloquent la suppression automatique. Le passage à la décision se fait
par l'entrée QE-EXP-12 (durées de rétention).

## Accès

La permission `donnees.inventaire.lire` est déclarée dans `permissions.py` et créée par
`seed.py`. Aucun rôle ne la reçoit par défaut ; elle est réservée au responsable données.
