# Catalogues publics ou authentifiés

- **Question** : `GET /modules` et `GET /billing/plans` doivent-ils rester publics ou exiger une authentification ?
- **Tâches concernées** : T-023
- **Contexte** : ces routes listent les modules et les plans de facturation (IAM-020). Un catalogue public expose l'offre commerciale et les identifiants internes.
- **Options** :
  - A. Authentifiés : seul un utilisateur connecté voit le catalogue (recommandation).
  - B. Publics : nécessaire si une page de vente doit afficher les plans sans connexion ; dans ce cas, un jeu de données public distinct est préférable à la route interne.
- **Recommandation vérifiée** : option A. Vérification : les routes sont listées dans l'inventaire de T-023, qui échouera tant que la décision n'est pas consignée.
- **État** : En attente de réponse (faible enjeu, la recommandation est appliquée à défaut)
