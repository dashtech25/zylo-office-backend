# Déploiement du backend

## Préparation

1. Image : `Dockerfile` du backend (port interne 3002, voir [`ports.md`](../process/ports.md)). Le port d'écoute réel est fixé par la plateforme de déploiement.
2. Secrets : toutes les valeurs requises sont définies. Hors développement, l'application refuse de démarrer si un secret est absent ou par défaut ([ADR 0003](../architecture/decisions/0003-echec-ferme-secrets.md)). La clé `APP_FIELD_ENCRYPTION_KEY` est obligatoire ([ADR 0005](../architecture/decisions/0005-chiffrement-champs-holykell.md)).
3. Base : sauvegarde préalable, migrations appliquées séparément (voir [`migration.md`](migration.md)).
4. Documentation interactive (`/docs`, OpenAPI) désactivée hors développement (T-015) : vérifier qu'elle n'est pas exposée.

## Contrôles avant mise en ligne

- [ ] `validation-avant-livraison.md` passée, en particulier la section code.
- [ ] Version de l'image identifiée (commit) et notée dans la fiche de tâche.
- [ ] Accord écrit du commanditaire pour toute mise en production.

## Pendant

- Déploiement par la plateforme (Dokploy, mentionnée dans [`ports.md`](../process/ports.md)).
- Pas de CI bloquante à ce jour : la CI est désactivée (DOC-001). Les contrôles ci-dessus sont la seule barrière.

## Après

- Vérifier que l'application démarre et répond sur une route simple.
- Surveiller les journaux de démarrage pour un refus de configuration.
- En cas de problème : [`retour-arriere.md`](retour-arriere.md).

## Environnements

Recette et production : voir [`local-setup.md`](../process/local-setup.md), section 6. L'environnement par défaut n'est pas tranché ([`environnement-par-defaut.md`](../questions/architecture/environnement-par-defaut.md)).
