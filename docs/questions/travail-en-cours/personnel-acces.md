# Personnel de station : réinitialisation, lot et atomicité (A4, T-021)

- **État** : ouverte (2026-10-09). Intégré avec les choix ci-dessous ; à valider.
- **Contexte** : le snapshot renvoyait un mot de passe temporaire dans les réponses (création, lot, réinitialisation). Décision client : aucun secret dans une réponse. Le flux d'invitation T-021 remplace ce mécanisme.

## Décisions prises

1. **Réinitialisation d'un compte actif refusée** (409 `password_reset_unavailable`). Le projet n'a pas de réinitialisation par e-mail (`app/auth` ne l'expose pas). Recommandation : tâche distincte « mot de passe oublié » ; en attendant, un compte actif ne peut pas être réinitialisé par un tiers.
2. **Réinitialisation d'un compte en attente** : réémission du lien d'activation (`reissue_invitation`), aucune valeur renvoyée.
3. **Création en lot non atomique à l'écriture** : la validation reste tout-ou-rien (aucune écriture si une ligne est fautive). Chaque personne est ensuite écrite (compte + invitation, fiche, poste). Le snapshot groupait tout dans une transaction grâce à `assign_role(commit=False)`, qui relève du lot B-L5 (non repris). Recommandation : intégrer B-L5 (ou une variante transactionnelle d'`assign_role`) pour rétablir l'atomicité complète.
4. **Changement de poste** : retrait puis attribution, chacun validé avant ; si l'attribution échoue après le retrait (cas non prévu par la pré-validation), la personne reste sans poste. Même dépendance que le point 3.
5. **Pas de rattrapage automatique du rôle « Responsable de tour »** dans les organisations existantes (seed idempotent, comportement T-018). Recommandation : une migration de données explicite, décidée séparément.
6. **Envoi requis** : sans e-mail configuré, création et lot sont refusés avant écriture (503). Voulu : aucun compte sans canal d'activation.

## À confirmer

- Acceptation du point 1 (aucune réinitialisation possible par un tiers pour un compte actif).
- Acceptation du point 3 jusqu'à l'intégration de B-L5.
