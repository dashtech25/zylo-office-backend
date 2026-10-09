---
name: nouvelle-adr
description: Rédige une ADR datée à partir d'une question tranchée dans docs/questions/ ou d'une décision prise.
when_to_use: Quand l'utilisateur demande de transformer une recommandation validée en décision d'architecture, ou de consigner une décision durable.
disable-model-invocation: true
allowed-tools: Read Grep Write Bash
---

# Nouvelle ADR

Entrée : la question tranchée (`docs/questions/<catégorie>/<sujet>.md`) ou la décision à consigner.

1. Numéro : le suivant dans `docs/architecture/decisions/` (`ls docs/architecture/decisions | sort | tail -1`).
2. Fichier : `docs/architecture/decisions/NNNN-titre-court.md`, en minuscules et tirets.
3. Contenu, dans cet ordre :
   - titre `# ADR NNNN : ...` ;
   - ligne `- **Date** :`, `- **Statut** :` (Proposée, Acceptée, Remplacée par NNNN) et `- **Source** :` avec chemins relatifs vérifiés ;
   - sections `## Contexte`, `## Décision`, `## Conséquences`, `## Alternatives écartées`.
4. Ajouter la ligne au tableau de `docs/architecture/decisions/README.md`.
5. Ne jamais supprimer une ADR : une décision remplacée reçoit le statut « Remplacée par NNNN » et la nouvelle ADR la référence.
6. Mettre à jour la question source : état « Appliquée » avec renvoi vers l'ADR.
7. Lancer `scripts/docs/verifier_liens.sh`.
