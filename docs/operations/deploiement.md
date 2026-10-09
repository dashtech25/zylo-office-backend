# Déploiement du backend

- **Statut** : procédure écrite (T-028, T-051), non exécutée en production.
- **Révision de production consignée** : `<à renseigner par l'opérateur, lecture seule : python -m app.cli verifier-revision>`
- **Périmètre** : image `Dockerfile` de `zylo-office-backend`, base PostgreSQL de production. Aucune commande
  de ce document ne doit être lancée contre une base de développement ou de recette sans accord.

## Prérequis

- Variables d'environnement de production fournies par la plateforme (`ENVIRONMENT=production`, `DATABASE_URL`,
  `JWT_SECRET`, `APP_FIELD_ENCRYPTION_KEY`, `STORAGE_SIGNED_URL_SECRET`). Aucune n'est écrite dans le dépôt.
- Volume de stockage documentaire (`/app/var/storage`) accessible en écriture par l'utilisateur uid 10001 :

  ```bash
  chown -R 10001:10001 <chemin-hote-du-volume>
  ```

  Sans cela, le conteneur non root ne peut pas écrire les documents. Vérifier avant le premier déploiement.

## Étapes

1. **Construire l'image** à partir du commit déployé, avec un tag daté ou le hash du commit. Ne pas réutiliser
   `latest` pour retrouver une version précédente.
2. **Sauvegarder la base** avant toute migration. Un dump chiffré, stocké hors du dépôt et hors du serveur d'application :

   ```bash
   pg_dump --no-owner "<URL PostgreSQL de production, sans le pilote asyncpg>" | gzip > sauvegarde-<AAAAMMJJ-HHMM>.sql.gz
   gpg --symmetric --cipher-algo AES256 sauvegarde-<AAAAMMJJ-HHMM>.sql.gz
   ```

   Vérifier que le fichier existe et n'est pas vide. Le restaurer une fois par trimestre sur une base jetable
   (voir `docs/operations/retour-arriere.md`). Une sauvegarde non restaurée ne compte pas.
3. **Vérifier la révision et le plan** :

   ```bash
   docker run --rm --env-file <fichier-env-prod> <image> python -m app.cli verifier-revision
   docker run --rm --env-file <fichier-env-prod> <image> python -m app.cli migrer --dry-run
   ```

4. **Appliquer les migrations** (une seule fois par déploiement, un seul processus) :

   ```bash
   docker run --rm --env-file <fichier-env-prod> <image> python -m app.cli migrer
   # si la liste contient une révision destructive :
   docker run --rm --env-file <fichier-env-prod> -v <dossier-sauvegarde>:/sauvegarde:ro <image> \
     python -m app.cli migrer --confirmer-destructives --sauvegarde /sauvegarde/<fichier>
   ```

5. **Seeds puis backfill** (idempotents, sans effet si rien ne manque) :

   ```bash
   docker run --rm --env-file <fichier-env-prod> <image> python -m app.cli seed
   docker run --rm --env-file <fichier-env-prod> <image> python -m app.cli backfill
   ```

6. **Démarrer le conteneur** de l'application. Il vérifie la révision au démarrage et refuse de servir si l'étape 4 a été
   sautée. Le `HEALTHCHECK` interroge `/api/v1/health`.
7. **Contrôle après déploiement** : `GET /api/v1/health` renvoie 200 ; une connexion de test sur un compte connu répond.
8. **Consigner** la révision déployée dans la section ci-dessus.

## Ce qui n'est pas automatisé

- La sauvegarde (étape 2) est une action opérateur. La garde de `migrer` vérifie seulement qu'un fichier existe.
- Le lieu de stockage des sauvegardes et la personne qui teste leur restauration restent à désigner
  (question `docs/questions/architecture/sauvegarde-avant-migration.md`).
- Les boucles Holykell et de balayage structurel tournent toujours dans le processus de l'application (BCK-016) :
  ne pas lancer plusieurs réplicas sans traiter ce point.
