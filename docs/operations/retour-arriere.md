# Retour arrière

- **Statut** : procédure écrite (T-028, T-051), non exécutée en production.
- **Règle générale** : on revient à une image précédente, et on ne défait un schéma que par restauration
  d'une sauvegarde contrôlée. Un `downgrade` n'est jamais lancé en production.

## 1. Retour de l'application (cas le plus fréquent)

Le code et le schéma sont séparés : si la migration n'a pas été appliquée, revenir à l'image précédente suffit.

1. Redéployer l'image du tag précédent (celui de la révision consignée dans `deploiement.md`).
2. Vérifier `GET /api/v1/health`.

Attention : si la migration a été appliquée, l'ancienne image peut ne plus être compatible avec le schéma.
Dans ce cas, passer au point 2.

## 2. Restauration de la base après migration

1. Arrêter le conteneur de l'application pour figer les écritures.
2. Déchiffrer la sauvegarde d'avant migration (`gpg --decrypt`), vérifier qu'elle est intègre (`gzip -t`).
3. Restaurer sur une **base jetable** d'abord, jamais directement sur la production :

   ```bash
   gunzip -c sauvegarde-<...>.sql.gz | psql "<URL base jetable>"
   ```

4. Contrôler le schéma restauré : `python -m app.cli verifier-revision` pointé sur la base jetable doit donner
   la révision d'avant migration (ou un refus clair si l'image ne correspond plus).
5. Seulement après contrôle : restaurer en production (décision d'exploitation, avec accord écrit), puis redémarrer
   l'image correspondant au schéma restauré.

`scripts/restore.sh <fichier> <base cible>` écrase la base cible. Ne jamais le lancer sur une base contenant des données
sans accord écrit.

## 3. Retour arrière Alembic (`downgrade`) : base de test uniquement

- `alembic downgrade -1` sert à vérifier qu'une migration est réversible, sur une base jetable `zylo_t<NNN>_test`.
- Pour `7ffb9473d45e` (TRUNCATE), le `downgrade` ne restaure aucune donnée : il ne doit jamais être lancé sur une base
  qui contient des données.
- Les `downgrade()` de `1047562d0691`, `00e30f42d09d` et `0240c128e5de` suppriment des tables : même règle.

## 4. Retour arrière du code de T-028 / T-051

Revenir au commit de la branche `remy` précédant la branche `chore/T-028-T-051-migrations-conteneur` :

- `CMD` redevient `alembic upgrade head && uvicorn ...` (ancien comportement) : à éviter, car il réintroduit la migration
  au démarrage, mais c'est le retour arrière documenté par T-028.
- `USER` disparaît : le conteneur redevient root. À n'utiliser que si le volume de stockage ne peut pas être
  remis à uid 10001.
- `on_startup` redevient le seed et le backfill à chaque démarrage (BCK-016).
