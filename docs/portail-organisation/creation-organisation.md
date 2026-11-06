# Création d'organisation (BE-102)

Route : `POST /api/v1/organizations` (`app/identity/router.py`), logique dans
`app/identity/service.py::create_organization`.

## Effet

Une seule transaction crée :

- une ligne `organization` (nom saisi, slug, `createdByUserId` = créateur, `tenantId`) ;
- une ligne `tenant` racine (BE-186 : une organisation par tenant en v1) ;
- une appartenance `organization_user` pour le créateur.

Aucun rôle n'est attribué au créateur. En particulier, aucun rôle `owner` n'est créé
(décision QE-POR-04, `definition-travail/00-pilotage/POINTS-OUVERTS.md`). Le rôle propriétaire
est affecté par une action explicite, jamais par cette création. Un champ `owner` (ou
équivalent) dans le corps est ignoré.

## Refus

| Cas | Code HTTP | Code d'erreur |
|---|---|---|
| Pas de session | 401 | `Authentification requise` (dépendance `get_current_user`) |
| Compte sans `identity.organization.create` | 403 | `permission_denied` |
| Même nom normalisé, même créateur | 409 | `organization_name_duplicate` |
| Slug déjà utilisé (toutes organisations) | 409 | `slug_already_used` |

Le code 401 sans session et le code 409 pour doublon suivent la recommandation de la fiche
BE-102 (QE-POR-01).

## Permission `org:create`

La permission est globale (sans portée organisation, car le créateur n'a pas encore
d'organisation). Elle est codée `identity.organization.create` (format
`domaine.entite.action`) et accordée par `app/identity/permissions.py::permissions_globales`
à tout compte actif. Ce n'est pas une ligne de la table `permission` ni un rôle : la garde
est donc centralisée dans cette fonction, qui peut être restreinte sans changer le service.

## Doublon

La comparaison porte sur le nom normalisé (`normalise_nom_organisation` : accents retirés,
casse ignorée, espaces de bord supprimés, espaces internes réduits) parmi les organisations
dont `createdByUserId` est le créateur et qui ne sont pas supprimées logiquement. Le même nom
créé par un autre compte est accepté. Les organisations antérieures à BE-102 ont
`createdByUserId` nul et ne participent pas à la déduplication.

## Migration

`alembic/versions/be102c0de0102_organization_created_by_be102.py` ajoute
`organization.createdByUserId` (nullable, clé étrangère vers `user.id`). Tête Alembic après
BE-102 : `be102c0de0102`.

## Tests

`tests/test_be102_creation_organisation.py` couvre CA-1 à CA-4. La fixture `organization` de
`tests/conftest.py` affecte explicitement le rôle `owner` après la création, pour les tests
qui supposent un propriétaire.
