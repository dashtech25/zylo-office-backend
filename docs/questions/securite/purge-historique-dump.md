# Purge de l'historique git du dump de base de données

- **Question** : faut-il réécrire l'historique git pour retirer `backups/zylo_office_20260831_180729.sql.gz`, sachant que le dépôt `origin` est **public** ?
- **Tâches concernées** : T-001 (question créée et rattachée), T-027, T-015
- **Contexte** :
  - le fichier est suivi depuis le commit `8aea496` (vérifié : `git log --all -- backups/` liste ce commit et le commit de retrait `8f2a72b`) ; il est présent sur les branches distantes `origin/main`, `origin/develop`, `origin/remy` et `origin/aminou` (`git branch -r --contains 8aea496`, état des références distantes du dernier fetch) ;
  - **visibilité consignée** : `origin` = `https://github.com/dashtech25/zylo-office-backend` est **PUBLIC** (`isPrivate: false`). Contrôle du 2026-10-08 par `gh repo view dashtech25/zylo-office-backend --json visibility,isPrivate` (API GitHub, compte `nkremy` connecté à `gh`). Le dump n'a pas été ouvert ;
  - retirer le fichier de l'index (T-001, commit `8f2a72b`) n'a aucun effet sur l'historique ni sur les copies déjà clonées ou forkées depuis un dépôt public.
- **Options** :
  - A. Conserver l'historique, faire tourner les identifiants (voir `rotation-credentials.md`) et passer le dépôt en privé. Pas de réécriture, pas de rupture pour les clones existants. Ne supprime pas les copies déjà téléchargées pendant la période publique.
  - B. Réécrire l'historique (`git filter-repo`) puis force-push. Casse les clones et les branches de travail, et ne supprime pas les copies déjà téléchargées par des tiers.
  - C. Dépôt public (constat) : considérer le contenu du dump comme publié, faire tourner les identifiants immédiatement, puis choisir A ou B.
- **Recommandation vérifiée** : options C puis A. Vérification : visibilité publique (ci-dessus) et présence du fichier dans l'historique de plusieurs branches distantes. Conséquence : le contenu est traité comme compromis ; la rotation (`rotation-credentials.md`) est la mesure qui protège réellement les données. Une réécriture ne revient pas en arrière et ne protège pas les copies déjà publiées : elle ne se décide qu'avec accord écrit du commanditaire, après la rotation. Aucun force-push n'est fait par l'agent.
- **Points à trancher par écrit par le commanditaire** :
  1. passer ou non le dépôt `dashtech25/zylo-office-backend` en privé, et à quelle date ;
  2. choisir A (historique conservé) ou B (réécriture + force-push, en connaissance des conséquences ci-dessus) ;
  3. confirmer l'accord ou le refus de la rotation immédiate listée dans `rotation-credentials.md`.
- **Condition de clôture de T-001** : réponse écrite du commanditaire sur les trois points, et rotation attestée (voir `rotation-credentials.md`). La fusion de T-001 n'attend pas la purge.
- **État** : En attente de réponse écrite du commanditaire. Visibilité publique consignée le 2026-10-08 (traiter comme fuite jusqu'à décision contraire).
