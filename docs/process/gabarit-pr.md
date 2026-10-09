# Gabarit de pull request

- **Statut** : en vigueur (T-016). Une PR par tâche (ou par lot de tâche lettrée), depuis la branche `<type>/T-NNN-<slug>`.
- **Fusion** : par l'orchestrateur seul, vague par vague (`PLAN_REMISE_SUR_PIED.md` §2). L'auteur n'ouvre pas de fusion.

## Titre

`[T-NNN] <verbe à l'infinitif, en français>`, 70 caractères au plus.

## Corps

```markdown
## Tâche
Fiche : docs/plans/taches/T-NNN-<slug>.md · Branche : <type>/T-NNN-<slug> · Base : base-T004 (ou commit fusionné : …)
Base de test : zylo_tNNN[lettre]_test · Ports : back 31NN, front dev 32NN, front prod 33NN

## Changements
- …

## Fichiers touchés
- … (uniquement ceux listés dans la fiche, sinon justifier ici)

## Tests (commande et compte)
- `…` → N passés, M échoués (comparés à la base de référence : …)
- `python3 scripts/docs/check_plan.py` → 0 erreur (si le plan ou une fiche a changé)

## Décisions
- Décision non évidente : docs/questions/<catégorie>/<sujet>.md (état : …)

## Risques et retour arrière
- …

## Contrôles avant revue
- [ ] Aucun dump, `.env` ou jeton dans le diff (hook `.githooks/pre-commit`, sans `--no-verify`)
- [ ] Seules les bases `zylo_tNNN[lettre]_test` sont utilisées par les tests
- [ ] Playwright (si utilisé) lancé sur le build de production avec la configuration versionnée
- [ ] Registre et issues régénérés si une fiche a changé (`check_plan.py --generer`)
- [ ] Validation client obtenue si la tâche change des droits existants

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
