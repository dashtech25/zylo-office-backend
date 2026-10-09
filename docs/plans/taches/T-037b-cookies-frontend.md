# T-037b : Jetons dans des cookies HttpOnly, partie frontend

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : frontend · **Domaine** : security · **Type** : security
- **Branche suggérée** : `feat/T-037b-cookies-frontend` · **Base de test** : `zylo_t037b_test` · **Ports** : back 3137, front dev 3237, front prod 3337
- **Dépendances** : T-037a, T-030, T-033b
- **Décisions requises** : `securite/stockage-jetons.md`

## Objectif
Le frontend ne lit ni n'écrit plus aucun jeton. `localStorage` ne garde que l'identifiant d'organisation (préférence d'interface). Le client envoie les cookies (`credentials: 'include'`), sans en-tête Bearer, après la date de fin de T-037a.

## Problèmes résolus
- FRT-001 (P1, jetons dans `localStorage`), REV-S-20 (jetons lisibles par JavaScript pendant la transition)

## Dépendances : justification
T-037a (backend), T-030 (coquille et providers d'authentification), T-033b (client API unique, sans quoi `client.ts` serait modifié deux fois).

## Fichiers / modules concernés
- `src/core/auth/tokens.ts` (supprimé ou réduit à rien)
- `src/core/api/client.ts` (`credentials: 'include'`, retrait de l'en-tête Bearer)
- `src/core/organization/OrganizationContext.tsx` (seule préférence restant en `localStorage`)

## Stratégie
1. Bascule après la date de fin fixée en T-037a, pas avant : pendant la transition, le frontend reste compatible.
2. Retirer l'envoi de l'en-tête dans `client.ts` en un seul commit.
3. Les tests Playwright qui injectaient un jeton dans le stockage sont sans objet tant que Playwright est suspendu (voir `docs/process/decision-playwright-suspendu.md`).

## En-têtes de sécurité du frontend (REV-S-19)
- `next.config.ts` : `headers()` avec `Content-Security-Policy` (politique stricte, sans `unsafe-inline` pour les scripts si Next.js le permet, à vérifier au build), `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`.
- Le passage des jetons en cookies rend ces en-têtes nécessaires : ils sont livrés dans la même PR.
- Test : les en-têtes de la réponse de production contiennent chacun la valeur attendue (tests pytest / tsc / lint / build locaux ; Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`).

## Tests attendus
- Tests pytest / tsc / lint / build locaux (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`) ; comportement non couvert par un test automatisé : en-têtes de sécurité présents sur `/login` et sur une page protégée.
- Tests pytest / tsc / lint / build locaux (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`) ; comportement non couvert par un test automatisé : connexion, rafraîchissement, déconnexion ; `localStorage` et `sessionStorage` ne contiennent aucun jeton ; `document.cookie` ne montre pas le jeton.
- Parcours complet de T-026 vert.

## Critères d'acceptation
- En-têtes CSP, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` présents sur les réponses de production (test).
- Aucun jeton dans `localStorage` ni `sessionStorage`.
- Déconnexion efface les cookies.
- Tests pytest / tsc / lint / build locaux (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`) ; comportement non couvert par un test automatisé : parcours complet connexion, rafraîchissement, déconnexion.

## Risque et retour arrière
Élevé. Retour arrière : réactiver l'en-tête côté client tant que la date de fin n'est pas passée.

## Livrable documentaire
- `docs/architecture/securite/jetons.md` (complété, côté frontend).

## Parallélisable avec
T-039, T-040 (fichiers distincts).
