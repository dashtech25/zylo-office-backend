# Stockage des jetons de session : cookies posés par l'API ou BFF, et domaine commun

- **Question** : les jetons sont-ils posés en cookies par FastAPI, ou par un serveur intermédiaire Next.js (BFF) ? Quel domaine commun (même site) en production et en développement ?
- **Tâches concernées** : T-037a, T-037b
- **Contexte** : aujourd'hui les jetons sont lus et écrits dans `localStorage` (`src/core/auth/tokens.ts`, relevé par REV-S-20). Des cookies `HttpOnly` nécessitent un domaine commun entre l'interface et l'API. Aucune tâche d'infrastructure ne le garantit aujourd'hui.
- **Options** :
  - A. Cookies posés par FastAPI, même site (proxy ou sous-domaine commun) : recommandation.
  - B. BFF Next.js qui détient les jetons : une couche de plus, mais le backend ne gère plus les cookies.
  - C. Conserver `localStorage` : rejeté (jeton lisible par tout script de la page).
- **Recommandation vérifiée** : option A. Vérification : aucune dépendance BFF dans le frontend actuel ; le comportement de `Secure` sur `http://localhost` varie selon les navigateurs (Safari historiquement), à tester avant la bascule.
- **État** : En attente de réponse (décision d'infrastructure du client : proxy ou sous-domaine)
