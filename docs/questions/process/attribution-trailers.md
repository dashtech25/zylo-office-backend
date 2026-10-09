# Trailer Co-Authored-By : quel modèle nommer

- **Question** : le trailer `Co-Authored-By` des commits doit-il nommer « Claude Opus 5.5 » (texte demandé par le commanditaire) ou le modèle qui exécute réellement le travail ?
- **Tâches concernées** : T-017, T-040 et tous les commits de documentation futurs.
- **Contexte** : le brief de la tâche T-017/T-040 impose `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. L'environnement de la session indique que le modèle exécutant est `claude-haiku-5-5` (Haiku 5.5). Les deux valeurs sont contradictoires.
- **Options** :
  - A. Garder le texte demandé par le brief (Opus 5.5) ;
  - B. Nommer le modèle réellement utilisé (Haiku 5.5) ;
  - C. Ne pas mettre de trailer modèle.
- **Recommandation vérifiée** : option A pour l'instant, parce que le brief est une instruction explicite et que la règle d'attribution du projet laisse la préséance aux instructions de l'utilisateur. Vérification : la règle de `docs/process/git-workflow.md` impose le trailer, sans préciser le nom du modèle. Corriger le trailer au commit suivant si le commanditaire tranche pour B.
- **État** : En attente de réponse. Recommandation appliquée provisoirement sur la branche `docs/T-017-T-040-docs-agents`.
