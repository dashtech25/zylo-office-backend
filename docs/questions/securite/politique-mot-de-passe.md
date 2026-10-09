# Politique de mot de passe

- **Question** : quelle longueur minimale et quelles vérifications appliquer aux mots de passe (inscription, changement, réinitialisation) ?
- **Tâches concernées** : T-013, T-049
- **Contexte** : aujourd'hui les règles diffèrent entre `app/auth/schemas.py` et le frontend (revue IAM-016, FRT-013). Les comptes existants avec un mot de passe court ne sont pas invalidés par cette décision.
- **Options** :
  - A. 8 caractères : minimum courant, mais faible face aux attaques hors ligne.
  - B. 12 caractères, liste locale de mots courants, sans règles de composition (recommandation NIST SP 800-63B).
  - C. 12 caractères et vérification auprès d'un service externe de mots de passe compromis : dépendance externe, à consigner.
- **Recommandation vérifiée** : option B. Vérification : la fiche T-013 impose une seule constante côté backend et frontend ; la liste locale ne sort pas de l'infrastructure.
- **État** : Option B appliquée provisoirement en T-013 (`docs/architecture/securite/politique-mot-de-passe.md`) ; à valider par le client
