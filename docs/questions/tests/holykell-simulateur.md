# Test P7 (connexion Holykell) : environnement et statut dans la CI

- **Question** : sur quel environnement le test P7 de connexion Holykell s'exécute-t-il, et est-il exclu de la CI ?
- **Tâches concernées** : T-009, T-027, T-038b
- **Contexte** : la spec `e2e/proprietaire-07-connexion-holykell.spec.ts` vise `localhost:8500` (simulateur) et indique qu'aucun endpoint n'existait à son écriture (revue REV-D-22). Le plan parle d'un compte externe. Le tag `external` annoncé n'existe pas (vérifié : aucune occurrence dans `e2e/` ni dans `playwright.config.ts`).
- **Options** :
  - A. Simulateur versionné et lancé en CI : nécessite un simulateur maintenu.
  - B. Tag `@external`, exclu de la CI, exécuté à la main sur simulateur ou compte réel, identifiants lus depuis l'environnement (recommandation).
  - C. Supprimer P7 : rejeté tant qu'aucune décision n'est prise.
- **Recommandation vérifiée** : option B. Vérification : absence du tag (contrôle `grep`) ; identifiants jamais versionnés (T-009, critère de contrôle).
- **État** : En attente de réponse (choix de l'environnement par le client)
