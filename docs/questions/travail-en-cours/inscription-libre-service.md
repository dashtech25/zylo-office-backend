# Ouvrir l'inscription en libre-service (page register) ?

- **État** : ouverte (2026-10-09). Non intégré.
- **Lot concerné** : F-L5 (`src/app/(auth)/register/page.tsx`, lien dans `login/page.tsx`, `createOrganization` dans `src/core/api/organizations.ts`, page organisations).

## Question

Le parcours « créer un compte puis une organisation » doit-il être accessible au public ?

## Contexte

- Le snapshot ajoute une page publique qui appelle `POST /auth/register`. Le commentaire du fichier indique que cet endpoint existe déjà côté backend mais n'était appelé par aucune page.
- La page de contact commercial `/essai-gratuit` ne crée pas de compte. Le snapshot en fait une distinction explicite.
- Aucune protection anti-abus n'est présente côté frontend (pas de captcha, pas de vérification d'adresse e-mail dans le lot). Le backend applique-t-il une limitation de débit sur `/auth/register` ? À vérifier (T-012 couvre la connexion).
- La création d'organisation depuis cette page n'a pas été rapprochée des règles d'activation de module de T-021.

## Options

1. Ouvrir l'inscription avec limitation de débit et vérification de l'adresse e-mail (à planifier).
2. Garder l'inscription fermée : création de comptes par un administrateur, par invitation (T-021).
3. Intégrer la page seule, derrière un drapeau de configuration désactivé par défaut.

## Recommandation vérifiée

Option 2 pour l'instant. Vérifié : T-021 fournit le parcours d'invitation et d'activation, qui couvre le besoin sans endpoint public. Option 1 ou 3 seulement après décision produit et vérification de la limitation de débit de `/auth/register`.

## Décision attendue

- Valider l'option (1, 2 ou 3).
