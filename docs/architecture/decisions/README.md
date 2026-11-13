# Décisions d'architecture (ADR)

Une décision = un fichier `NNNN-titre.md`, numéroté dans l'ordre d'acceptation. Gabarit : la skill `nouvelle-adr` (`.claude/skills/nouvelle-adr/SKILL.md`).

Statuts : `Proposée`, `Acceptée`, `Remplacée par NNNN`. Une décision remplacée n'est jamais supprimée.

| ADR | Titre | Statut |
|---|---|---|
| [0001](0001-monolithe-modulaire.md) | Monolithe modulaire, pas de microservices | Acceptée |
| [0002](0002-roles-par-module.md) | Rôles et permissions rattachés à un module (`role.moduleCode`) | Acceptée, validation client en attente |
| [0003](0003-echec-ferme-secrets.md) | Refus de démarrer hors développement avec un secret par défaut | Acceptée, à vérifier (T-002) |
| [0004](0004-pyjwt-remplace-python-jose.md) | PyJWT remplace python-jose | Acceptée |
| [0005](0005-chiffrement-champs-holykell.md) | Chiffrement du mot de passe Holykell (Fernet, clé en variable d'environnement) | Acceptée, provisoire (T-027) |
| [0006](0006-playwright-suspendu.md) | Suspension de Playwright | Acceptée (décision client du 2026-10-09) |
| [0007](0007-storybook-retire.md) | Retrait de Storybook | Acceptée, exécution planifiée (T-041) |
| [0008](0008-table-ports-unique.md) | Table de ports unique et allocation par worktree | Acceptée (T-003) |
| [0009](0009-fournisseur-paiement-provisoire.md) | Fournisseur de paiement provisoire derrière un adaptateur | Proposée, réversible; aucun paiement live |
