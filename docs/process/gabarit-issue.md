# Gabarit d'issue

- **Statut** : en vigueur (T-016). Une issue par tâche, générée depuis la fiche (`docs/plans/ISSUES_A_CREER.md`).
- **Labels** : voir `labels.md`.

## Titre

`[T-NNN] <titre de la fiche>` (identique à la ligne du registre).

## Corps

```markdown
Fiche : docs/plans/taches/T-NNN-<slug>.md
Vague : N · Priorité : Px · Taille : S|M|L · Dépôt(s) : …
Dépendances : T-…  (toutes fusionnées avant de démarrer)
Décisions requises : docs/questions/<catégorie>/<sujet>.md  (ou « aucune »)
Validation client avant fusion : oui | non

## Objectif
Repris de la fiche, en une à trois phrases.

## Critères d'acceptation
- [ ] …  (repris de la fiche, cochés par l'auteur de la PR)

## Hors périmètre
- …
```

## Règles

- L'issue ne remplace pas la fiche : la fiche reste la source de vérité, l'issue la reflète.
- Une tâche qui change des droits existants ne passe pas à « fusionnée » sans réponse écrite du client.
- Ne jamais coller de dump, de `.env`, de jeton ou de donnée terrain dans une issue.
