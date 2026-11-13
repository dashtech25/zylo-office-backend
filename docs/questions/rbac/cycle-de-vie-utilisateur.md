# Que deviennent un utilisateur désactivé ou retiré de l'organisation ou d'un module ?

- **Question** : lors d'un départ, quels effets sur le compte, les sessions, les données créées et les affectations ?
- **Tâches concernées** : T-048, T-020
- **Contexte** : aucune route ne désactive un utilisateur ni ne retire une affectation (REV-A-06). `User.status` accepte `active`, `suspended`, `pending`.
- **Options** :
  - A. Suspension réversible, révocation des sessions, retrait de l'appartenance et des affectations ; données conservées et rattachées à l'organisation (recommandation).
  - B. Suppression physique : rejetée, destructive et interdite par le plan (§2).
  - C. Anonymisation des données personnelles tout en conservant les données métier : plus protectrice, plus coûteuse ; à décider si le client a des obligations de protection des données.
- **Recommandation vérifiée** : option A. Vérification : les statuts existent déjà dans le modèle ; la révocation des sessions est prévue par T-020 ; aucune suppression n'est nécessaire pour les effets demandés.
- **État** : En attente de réponse (conservation des données à confirmer)
