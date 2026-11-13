# Qui peut créer une organisation, et avec quel quota ?

- **Question** : tout utilisateur authentifié peut-il créer une organisation ? Avec quel quota par utilisateur ?
- **Tâches concernées** : T-019
- **Contexte** : aujourd'hui la création n'a ni quota ni contrôle de format (IAM-017). Aucune valeur de quota n'est fournie par le client.
- **Options** :
  - A. Tout utilisateur authentifié, avec un quota par utilisateur (recommandation) ; valeur proposée : 3 organisations, à confirmer.
  - B. Réservée à la plateforme : impose une permission d'administration (voir `permission-plateforme.md`).
  - C. Ouverte sans quota : rejeté, risque d'abus.
- **Recommandation vérifiée** : option A avec la valeur proposée, paramétrable par `ORG_CREATION_QUOTA`. Vérification : aucun quota dans `app/identity/` (IAM-017). Le client fixe la valeur ; sans valeur, T-019 garde le quota à zéro et le signale.
- **État** : En attente de réponse (valeur du quota)
