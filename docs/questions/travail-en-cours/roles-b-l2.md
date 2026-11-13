# Rôles et permissions du lot exploitation (B-L2) : ce qui est repris

- **État** : ouverte (2026-10-09). Appliqué dans `roles_seed.py` et `seed.py` ; à valider.
- **Règle** : une permission ne s'élargit jamais silencieusement. Chaque écart avec le snapshot est listé ici.

## Repris

- 24 permissions `zyloLiquid.*` du lot (tours, planning, pointage, passation, ouverture, mouvements, affectation, index de fermeture, jaugeage, caisse, rubriques) déclarées dans `permissions.py` **et** `seed.py`, comme l'impose CLAUDE.md.
- Ajouts par rôle existant, limités aux permissions du lot : gérant (`zylo_liquid_station_admin`), chef d'équipe, caissier, pompiste (`PUMP_READ` et lecture de son affectation), auditeur, HSE (lecture des tours).
- Nouveau rôle « Responsable de tour » (`zylo_liquid_shift_manager`), copié du snapshot. Le chef d'équipe et le caissier ne reçoivent aucun droit de saisie de caisse (règle PC-22 du snapshot).

## Non repris, et pourquoi

- `CURRENCY_READ`, `GEO_READ` ajoutées au gérant : élargissement lié aux devise et géographie (lot B-L5). Hors périmètre.
- `HOLYKELL_ACCOUNT_MANAGE` accordée au gérant : un gérant de station ne doit pas rattacher l'organisation à un compte Holykell (identifiants de niveau organisation). Non accordée à un rôle : seul le propriétaire, qui détient toutes les permissions, peut créer un compte Holykell. Recommandation : décision produit distincte.
- `create_tank` / `create_pump` gardés par la permission d'organisation entière (remy) : le snapshot les passait en portée station (correction du 2026-09-25). Non repris ici : cela élargit l'accès à un gérant de station. Recommandation : décision séparée, avec les tests de portée du lot B-L5.
- Le seed est idempotent par code de rôle (T-018) : les organisations déjà activées ne reçoivent pas les nouvelles permissions ni le nouveau rôle. Voulu ; pas de rattrapage automatique.

## À confirmer

- Liste des permissions par rôle (tableau dans `roles_seed.py`, commentaires « lot B-L2 »).
- Refus d'accorder `HOLYKELL_ACCOUNT_MANAGE` aux rôles de station.
