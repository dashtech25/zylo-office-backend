# Zylo Liquid : journal de validation

> Découpé depuis [`docs/archive/zylo-liquid/validation_log.md`](../../../archive/zylo-liquid/validation_log.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

> Journal de bord tenu à jour à chaque endpoint, selon la méthodologie
> « Point 4 — Valider une API comme les titans » (adoptée à partir de
> l'endpoint 2, appliquée rétroactivement à l'endpoint 1) : une
> fonctionnalité n'est pas validée parce qu'elle est codée, mais parce
> qu'elle est prouvée, à trois niveaux — algorithme seul (Niveau 1),
> contrat d'endpoint (Niveau 2), scénario métier de bout en bout
> (Niveau 3). Toute preuve consignée ici est une exécution réelle (pytest
> et/ou curl contre un serveur réel), jamais une relecture de code.

---

Trois niveaux, un fichier par niveau :

- [Niveau 1 : algorithmes](niveau-1-algorithmes.md)
- [Niveau 2 : catalogue (produits, stations)](niveau-2-catalogue.md)
- [Niveau 2 : cuves, mesures, réseau, livraisons](niveau-2-cuves-mesures-reseau.md)
- [Niveau 3 : flux métier](niveau-3-flux.md)
- [Suivi global](suivi.md)

> Avertissement (DOC-022) : les entrées portent la date du 2026-09-01. Les fonctionnalités ajoutées après cette date (ex. `eabf517`, alertes `manual_gauging_discrepancy`) ne figurent pas ici et sont **non validées** tant qu'aucune entrée n'est ajoutée.
