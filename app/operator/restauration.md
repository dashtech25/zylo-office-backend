# Sauvegarde et restauration (BE-175)

Module : `app/operator/restauration.py`. Scripts réutilisés : `scripts/backup.sh`, `scripts/restore.sh`.

- **Sauvegarde** : `sauvegarder_base(dossier)` produit un dump gzip complet de la base de `DATABASE_URL`.
- **Restauration** : `restaurer_sauvegarde(actor_user_id, fichier, base_cible)`. Ordre des contrôles : droit opérateur (`assert_operator_user`, 403), puis refus de la base source (422), puis script.
- Aucune route HTTP. La restauration écrase la base cible : elle doit être jetable.
- Restauration par tenant : non implémentée, la restauration porte sur la base entière (point ouvert, voir la doc de module du code).
- Preuve : `tests/test_be175_sauvegarde_restauration.py`.
