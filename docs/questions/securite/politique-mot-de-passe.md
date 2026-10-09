# Politique de mot de passe

- **Question** : quelle longueur minimale et quelles vérifications appliquer aux mots de passe (inscription, changement, réinitialisation) ?
- **Tâches concernées** : T-013, T-049
- **Contexte** : aujourd'hui les règles diffèrent entre `app/auth/schemas.py` et le frontend (revue IAM-016, FRT-013). Les comptes existants avec un mot de passe court ne sont pas invalidés par cette décision.
- **Options** :
  - A. 8 caractères : minimum courant, mais faible face aux attaques hors ligne.
  - B. 12 caractères, liste locale de mots courants, sans règles de composition (recommandation NIST SP 800-63B).
  - C. 12 caractères et vérification auprès d'un service externe de mots de passe compromis : dépendance externe, à consigner.
- **Recommandation vérifiée** : option B. Vérification : la fiche T-013 impose une seule constante côté backend et frontend ; la liste locale ne sort pas de l'infrastructure.
- **État** : Option B appliquée provisoirement le 2026-10-09 en T-013 (`docs/architecture/securite/politique-mot-de-passe.md`) ; à valider par le client
- **Point ouvert (revue du lot 5, 2026-10-09)** : `POST /auth/register` est public et répond 409 `email_already_used` pour un e-mail déjà utilisé, ce qui révèle l'existence d'un compte. Une réponse neutre suppose un flux de vérification de l'e-mail, qui n'existe pas. Décision à prendre : retirer l'inscription publique (les comptes passent par T-021) ou fixer une réponse neutre sans vérification.
