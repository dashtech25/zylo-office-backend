# Documentation Zylo Office — Backend

Index de toute la documentation technique du backend. Convention à suivre
pour tout futur module — ne pas la réinventer par module.

## Organisation

```text
docs/
├── README.md                  # ce fichier — index, toujours à jour
├── core/                      # documentation du socle (Organization, User,
│                               # RBAC, modules_registry, billing, geo...)
│   └── ...
└── modules/                   # une documentation par module métier
    └── <nom-du-module>/
        ├── phase-1-database.md   # base de données
        ├── phase-2-api.md        # API (à créer quand la Phase 2 démarre)
        └── phase-3-frontend.md   # frontend (à créer quand la Phase 3 démarre)
```

## Règle de nommage

Un document de phase porte le nom `phase-<N>-<sujet>.md`, aligné sur les
grandes phases du module telles que définies dans son prompt d'origine
(`PHASE 1 — BASE DE DONNÉES`, `PHASE 2 — API`, `PHASE 3 — FRONTEND`, etc. —
voir `instruction_2_base_donnees_phase_1.md` pour l'exemple de Zylo Liquid).
Chaque document de phase doit répondre aux mêmes questions, dans cet ordre,
pour rester comparable d'un module à l'autre :

1. **Quelle architecture est appliquée** et pourquoi (référence à la
   décision déjà actée, jamais réinventée).
2. **Ce qui a été construit** dans cette phase précisément — pas plus.
3. **Ce qui a été factorisé dans le Core**, avec justification.
4. **Ce qui reste propre au module**, avec justification.
5. **Comparaison aux sources de vérité** utilisées (schéma validé, base
   réellement testée, code existant...) — jamais une supposition.
6. **Décisions prises**, chacune avec sa source et sa justification.
7. **Points encore à confirmer** — tout ce qui n'a pas pu être tranché sans
   arbitrage humain, explicitement listé plutôt que deviné.
8. **Rapport final** : fichiers créés/modifiés, validation ou non de la
   phase, raisons si non validée.

## Pourquoi cette structure

- **`core/` séparé de `modules/`** reflète directement l'architecture
   Modular Monolith with Layered Domain Model du projet — la documentation
   suit la même séparation que le code (`app/core/`, `app/shared/` d'un
   côté, `app/modules/<nom>/` de l'autre).
- **Un sous-dossier par module** permet d'ajouter un nouveau module (CRM,
  Stock, Comptabilité...) sans jamais toucher à la documentation d'un module
  existant, et sans que deux modules ne se marchent dessus.
- **Un fichier par phase** garde chaque document court et daté dans le
  temps — on ne réécrit pas un document déjà validé, on en ajoute un nouveau
  pour la phase suivante, avec ses propres critères de validation.

## Documents existants

- [`core/phase12-offline-readiness-audit.md`](core/phase12-offline-readiness-audit.md) — audit de conformité offline/synchronisation du socle (Phase 12 du plan `grande_phases.md`).
- [`core/app-launcher-endpoints.md`](core/app-launcher-endpoints.md) — endpoints organisations de l'utilisateur + modules installés par organisation, prérequis du App Launcher frontend (issue #55).
- [`modules/zylo-liquid/phase-1-database.md`](modules/zylo-liquid/phase-1-database.md) — base de données du module Zylo Liquid (résumé ; le document de référence complet est `phase_1_database.md` à la racine du dépôt, conservé pour respecter le nom de livrable exact demandé par `instruction_2_base_donnees_phase_1.md`).
- [`modules/zylo-liquid/phase-2-api.md`](modules/zylo-liquid/phase-2-api.md) — API du module Zylo Liquid, document vivant complété endpoint par endpoint (procédure : `Point 3 — Définir la procédure de développement endpoint par endpoint.md`).
