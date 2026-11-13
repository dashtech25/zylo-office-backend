# Table de ports unique

- **Statut** : en vigueur depuis T-003. Ce fichier fait foi pour les ports ; les README et `CLAUDE.md` renvoient ici sans recopier la table.
- **Décision** : `docs/questions/architecture/ports-canoniques.md` (option A).
- **Contrôle** : `scripts/check_ports.sh` échoue si un port interdit apparaît dans un fichier de configuration.

## 1. Table

| Usage | Backend | Frontend dev | Frontend prod (Playwright) |
|---|---|---|---|
| Checkout principal (hors worktree) | 3002 | 3001 | 3055 |
| Worktree de la tâche T-NNN (n = NNN) | 3100+n | 3200+n | 3300+n |
| Conteneur Docker | 3002 (interne) | — | 3003 (port de conteneur du frontend) |
| Interdits | 3006, 3007 | 3006, 3007 | 3006, 3007 |

- Production : le port d'écoute réel est fixé par la plateforme de déploiement (Dokploy), hors de cette table. L'image backend expose 3002 par défaut.
- Le port du frontend dev du checkout principal est 3001 (`npm run dev`), pas 3000 (défaut de Next.js).

## 2. Règle d'allocation par worktree

- Une tâche T-NNN a un numéro n = NNN (3 chiffres). Son worktree prend : backend 3100+n, frontend dev 3200+n, frontend prod 3300+n.
- Unicité : pour n de 1 à 51, les plages 3101–3151, 3201–3251 et 3301–3351 ne contiennent ni 3001, ni 3002, ni 3003, ni 3055. La formule ne produit des plages disjointes que pour n < 100 ; `scripts/dev/env_tache.sh` refuse NNN >= 100.
- Les tâches à lettre (T-033a, T-035b…) partagent le numéro n et s'exécutent en chaîne, jamais en parallèle.
- La base de test d'une tâche suit le même numéro : `zylo_t<NNN>_test` (voir `docs/process/git-workflow.md`, §4).

## 3. CORS

- Les origines autorisées viennent de la variable `CORS_ORIGINS` (liste JSON), lue par `app/core/config.py`. Une variable présente remplace le défaut.
- Chaque worktree déclare son origine frontend dans son `.env`, écrit par `scripts/dev/env_tache.sh` : `CORS_ORIGINS=["http://localhost:<3200+n>","http://127.0.0.1:<3200+n>"]`.
- Le défaut couvre le checkout principal (3001) et le serveur e2e Playwright (3055).
- Méthodes et en-têtes sont listés explicitement dans `app/main.py`.

## 4. Fichiers qui reprennent ces valeurs

| Fichier | Port utilisé | Remarque |
|---|---|---|
| `app/core/config.py` | `PORT` 3002, `CORS_ORIGINS` 3001 et 3055 | défaut du checkout principal |
| `.env.example` | 3002, CORS 3001 | copie locale du checkout principal |
| `Dockerfile` | `PORT=3002`, `EXPOSE 3002` | port interne du conteneur |
| `README.md` | 3002 | démarrage local |
| `CLAUDE.md` | 3002 | commande de démarrage réel |
| frontend `package.json` | 3001 (`dev`, `start`) | checkout principal |
| frontend `.env.local.example` | API 3002, `PORT` 3001 | copie locale du checkout principal |
| frontend `src/core/api/client.ts` | repli 3002 | le repli est journalisé en console (dépôt frontend) |
| frontend `playwright.config.ts` | 3055 | serveur e2e, suspendu |
| frontend `Dockerfile` | 3003 | port de conteneur |

## 5. Interdits

- **3006 et 3007** : anciens ports de la documentation et de la baseline de tests. Ils ne doivent apparaître dans aucun fichier de configuration. `scripts/check_ports.sh` le vérifie.
- Un port occupé par un autre processus fait échouer `scripts/dev/env_tache.sh creer` (préflight).

## 6. Copies locales de main-local et des issues (parallélisme local)

Source : `implementation/scripts/parallelisme.env` (procédure : `implementation/PARALLELISME-LOCAL.md`, section 1.5). Port = base + emplacement. L'emplacement 0 est réservé à la branche `main-local` ; les copies prennent les emplacements 1 à `COPIES_MAX` (6 par défaut, maximum technique 99).

| Usage | Backend | Frontend dev | Frontend e2e (Playwright) |
|---|---|---|---|
| Branche main-local (emplacement 0) | 3400 | 3500 | 3600 |
| Copie de l'emplacement s (1 à `COPIES_MAX`) | 3400 + s (3401+) | 3500 + s (3501+) | 3600 + s (3601+) |

- Disjonction : les plages 3401 à 3699 ne contiennent ni 3001, ni 3002, ni 3003, ni 3055, ni 3006, ni 3007, et ne recouvrent pas les plages T-NNN (3101 à 3399).
- Le numéro d'emplacement, et non le numéro de l'issue, pilote les ports.
- CORS : le `.env` de chaque copie autorise les origines du frontend dev et du frontend e2e de son emplacement (les deux ports).
- `E2E_PORT` (frontend) : à ajouter à la table de la section 1 pour les copies ; le repli 3055 reste pour le checkout principal.
