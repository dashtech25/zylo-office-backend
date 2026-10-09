# ADR 0008 : Table de ports unique et allocation par worktree

- **Date** : 2026-10-08 (T-003, option A de [`ports-canoniques`](../../questions/architecture/ports-canoniques.md)).
- **Statut** : Acceptée.
- **Source** : [`docs/process/ports.md`](../../process/ports.md).

## Contexte

Trois schémas coexistaient (3002, 3001, 3055) et la baseline utilisait 3006 et 3007 : README, CLAUDE.md et configuration se contredisaient (audit DOC-002, DOC-003, ARC-014).

## Décision

Un seul fichier fait foi : `docs/process/ports.md`. Checkout principal : backend 3002, frontend dev 3001, frontend prod e2e 3055. Worktree de tâche T-NNN : backend 3100+n, frontend dev 3200+n, frontend prod 3300+n. Ports interdits : 3006 et 3007. `scripts/check_ports.sh` le vérifie.

## Conséquences

- Les README et `CLAUDE.md` renvoient à ce fichier au lieu de recopier la table.
- Un port occupé fait échouer la création d'un worktree (préflight).
