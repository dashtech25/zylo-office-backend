# Conventions de code et d'API

- **Statut** : en vigueur.
- **Source** : ancien `CLAUDE.md` du backend, sections « Séquence obligatoire », « Règles de nommage et de contrat ».

## Séquence avant de créer quelque chose

1. Une fonction ou un schéma générique existe-t-il dans `shared/` ?
2. Un mécanisme transverse existe-t-il dans `core/` ?
3. Étendre un service ou un router existant plutôt que le dupliquer.
4. Créer seulement si aucun des points ci-dessus ne convient.

Exemples à réutiliser : `shared/pagination.py` (`Page`), `shared/schemas.py` (enveloppes de réponse), `shared/currency*` et `shared/geo*` (référentiels partagés), `core/security.py` (`get_current_user`, JWT), `core/errors.py` (gestionnaire d'exceptions), `rbac/service.py` (`require_permission()`).

## Nommage et contrat

- Tables : camelCase, en anglais, commentées (convention depuis la phase 3).
- Permissions : `<domaine>.<entite>.<action>`. Jamais une chaîne ad hoc, jamais un enum de rôles codé en dur dans un router. Voir [`modele-organisations-roles.md`](securite/modele-organisations-roles.md).
- Réponses : liste en `{data, meta:{total,limit,offset}}` ; erreur en `{error:{code,message,details}}` (`shared/schemas.py`, `core/errors.py`). Pas de format propre à chaque endpoint.
- Jamais de donnée inventée : un champ sans source réelle est absent ou marqué indisponible, jamais une valeur plausible et fausse.
