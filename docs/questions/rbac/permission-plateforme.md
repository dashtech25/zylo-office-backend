# Faut-il un rôle d'administration plateforme ?

- **Question** : existe-t-il un besoin d'administration globale (catalogue de plans, modules, paramétrage commun) qui exige une permission plateforme ?
- **Tâches concernées** : T-050, T-019
- **Contexte** : le plan supposait une « permission plateforme » ; `app/identity/service.py` indique « sans concept de super-admin plateforme » (REV-A-08). Le catalogue de plans est aujourd'hui créable par API (IAM-003).
- **Options** :
  - A. Pas de permission plateforme : catalogue seedé, administration par commande explicite (recommandation).
  - B. Permission `identity.platform.manage` attribuée par seed à un compte nommé, jamais par API.
- **Recommandation vérifiée** : option A. Vérification : la phrase « sans concept de super-admin plateforme » est présente dans `app/identity/service.py` ; la création de plan par API est retirée par T-019.
- **État** : En attente de réponse
