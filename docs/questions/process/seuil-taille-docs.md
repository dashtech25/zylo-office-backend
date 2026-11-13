# Seuil de longueur d'un fichier de documentation

- **Question** : quel seuil de lignes fait qu'un fichier de documentation est trop gros, hors `docs/archive/` ?
- **Tâches concernées** : T-017 (critère d'acceptation « seuil à confirmer dans la PR »), T-040.
- **Contexte** : les fichiers `phase-2-api.md` (907 lignes), `validation_log.md` (598) et `phase_1_database.md` (253) dépassaient la limite perçue. Après découpage, le plus grand fichier hors archive fait 212 lignes (`docs/modules/zylo-liquid/validation/niveau-2-cuves-mesures-reseau.md`). Vérification : `find docs -name '*.md' -not -path 'docs/archive/*' | xargs wc -l | sort -n | tail`.
- **Options** :
  - A. 300 lignes (seuil proposé par T-017) ;
  - B. 200 lignes, comme la limite de confort de `CLAUDE.md` ;
  - C. pas de seuil, revue humaine seulement.
- **Recommandation vérifiée** : option A. Tous les fichiers actuels hors archive passent ce seuil, et il laisse de la marge sans autoriser un fichier de 900 lignes. Le contrôle n'est pas automatisé à ce stade ; à ajouter à `scripts/docs/verifier_liens.sh` si le seuil est confirmé.
- **État** : En attente de réponse. Recommandation appliquée provisoirement (contribution : [`contribution.md`](../../workflows/contribution.md)).
