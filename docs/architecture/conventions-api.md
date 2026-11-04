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
- Réponses : liste en `{data, meta:{total,limit,offset}}`. Toute nouvelle erreur suit `ApiErrorResponse` (`shared/schemas.py`) : `{error:{code,message,field_errors,details},request_id}`. Les succès existants ne sont pas enveloppés globalement.
- Jamais de donnée inventée : un champ sans source réelle est absent ou marqué indisponible, jamais une valeur plausible et fausse.

## Erreurs et corrélation HTTP

- `field_errors` est un objet `chemin -> liste de messages`; il est vide quand aucun champ précis n’est concerné. Les chemins de validation retirent le préfixe de source FastAPI (`body`, `query`, `path`, `header`, `cookie`) et utilisent des indices pointés (`items.0.quantity`).
- `details` reste disponible pendant la transition pour les détails métier historiques. Pour les erreurs de validation, l’ancienne liste `loc/type/msg` est conservée, mais les propriétés Pydantic `input` et `ctx` sont retirées car elles peuvent contenir des valeurs soumises ou des données de validateur.
- `request_id` dans le corps d’erreur correspond à `X-Request-Id`. Le middleware accepte `X-Request-Id` ou `X-Correlation-Id` d’entrée seulement si la valeur contient 1 à 128 caractères parmi lettres ASCII, chiffres, `.`, `_`, `:` et `-`; sinon il génère un UUID. Les deux en-têtes de réponse portent la même valeur.
- Ces règles couvrent les `AppError`, erreurs de validation FastAPI (`RequestValidationError`), exceptions Starlette/FastAPI (`HTTPException`, y compris 404/405) et exceptions inattendues (500). Les codes des `AppError` restent ceux levés par le domaine; les exceptions HTTP deviennent `http_<status>`. Le 500 demeure générique côté client. L’identifiant est stocké sur l’état ASGI de la requête pour être disponible même au gestionnaire 500 externe de Starlette; ces réponses portent aussi `X-Request-Id` et `X-Correlation-Id`.
- Le client ne retente pas une mutation automatiquement sur timeout/erreur réseau ambiguë sans mécanisme d’idempotence explicitement défini. La présence d’un request ID sert au diagnostic, pas à dédupliquer une commande.
