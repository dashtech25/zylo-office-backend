# Résumé du portail filtré par permission (BE-109)

Route : `GET /api/v1/organizations/{organization_id}/portal-summary`.
Code : `app/portail/resume_router.py` (route), `app/portail/resume.py` (`build_portal_summary`).

## Contrat

- Garde : `OrgScope` (BE-101) puis action `portail.resume.lire`, permission `portal.summary.read`.
  Sans session : 401. Hors appartenance ou identifiant mal formé : 404 `organization_not_found`.
  Sans `portal.summary.read` : 403 `permission_denied`.
- Sections, chacune incluse seulement si sa permission est accordée :

| Section | Source | Permission |
|---|---|---|
| `entitlements` | BE-107, `included` et `addOns` | `organization.entitlement.read` |
| `usage` | BE-108, dernier snapshot | `organization.usage.read` |
| `members` | BE-106, liste des membres | `organization.members.read` |
| `billing` | abonnement le plus récent (statuts seuls) | `billing.subscription.read` |

- Section non autorisée : absente de la réponse (pas de `null`, pas d'erreur globale).
- Lecture seule ; aucune donnée d'une autre organisation n'est lue.

## Écarts avec la fiche

- Permission du portail : la fiche écrit `portal:read` ; le code retient `portal.summary.read`
  (format `domaine.entite.action`, comme BE-108).
- Section membres : la fiche écrit `members:manage` ; le code retient `organization.members.read`,
  permission de lecture déjà utilisée par BE-106.
- Section facturation : la fiche écrit `billing:read` ; le code retient `billing.subscription.read`.
  La section ne porte que l'état de l'abonnement, sans montant.
- Permission accordée au propriétaire à la création de l'organisation (`OWNER_DEFAULT_PERMISSIONS`) ;
  les organisations existantes la reçoivent par le backfill `cli.py` (comme les autres codes du portail).
