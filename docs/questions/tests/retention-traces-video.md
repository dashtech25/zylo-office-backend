# Rétention des vidéos et traces Playwright

- **Question** : pendant combien de temps conserve-t-on les vidéos et traces des tests e2e, et lesquelles ?
- **Tâches concernées** : T-008, T-009
- **Contexte** : `playwright.config.ts`, ligne 27, fixe `video: "on"` (vérifié) : chaque test enregistre une vidéo, y compris les données de test. Aucune règle de rétention n'existe (REV-S-17).
- **Options** :
  - A. 7 jours pour les échecs, aucune conservation pour les succès (recommandation).
  - B. 30 jours pour tout : coût de stockage et exposition plus élevés.
  - C. Tout conserver : rejeté.
- **Recommandation vérifiée** : option A ; `video: "retain-on-failure"` est l'équivalent Playwright. Vérification : la valeur `on` est lue dans la configuration.
- **État** : En attente de réponse
