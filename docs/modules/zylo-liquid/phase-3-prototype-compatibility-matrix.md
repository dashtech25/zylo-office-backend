# Zylo Liquid — Phase 3 : matrice de compatibilité prototype ↔ Niveau 1

> **Note de mise à jour (2026-09-07, mission « vente-maintenant-reglementation »,
> Bloc 10 du plan d'implémentation)** : ce fichier était absent du backend
> actif — il n'existait que dans une copie archivée
> (`ancien/zylo-office-backend/docs/`), une incohérence documentaire
> constatée à l'audit (`01-audit-existant.md` §6.1 de la mission). Il est
> recopié ici tel quel, complété par les annotations `[MIS À JOUR]`
> ci-dessous pour les lignes désormais **obsolètes** — le contenu original
> (daté du 2026-09-03) n'est pas réécrit, uniquement annoté, pour préserver
> la trace historique de la décision initiale.
>
> Lignes concernées, toutes désormais implémentées dans une mission
> ultérieure :
> - **Ligne 7** (caisse/transactions/quarts) — `[MIS À JOUR]` : le volet
>   ventes/paiement existe maintenant via `Sale`/`ProductSaleTransaction`
>   (`processus-double-sources-verite` puis `vente-maintenant-reglementation`).
>   Les quarts (`ShiftCashDeclaration`) existent également. Reste hors
>   périmètre : un vrai modèle de shift pompiste au sens RH.
> - **Ligne 8** (contribution non pétrolière/boutique) — `[MIS À JOUR]` :
>   `SellableProduct`/`ProductSaleTransaction`/`ProductSaleLine`
>   (`vente-maintenant-reglementation`, Blocs 4/5) couvrent désormais la
>   vente de produits boutique et son chiffrage — plus "PRÉSENTER MAIS
>   DÉSACTIVER".
> - **Ligne 26** (HSE/incendie/maintenance/inspections/contrats) — `[MIS À
>   JOUR]` : `Equipment`/`Intervention`/`Technician`
>   (`vente-maintenant-reglementation`, Bloc 6) couvrent le volet
>   équipements/interventions. `RegulatoryDocument`/`RegulatoryDeclaration`
>   (Bloc 7) couvrent le volet documents réglementaires/sécurité incendie.
>   Contrats de maintenance formels (`MaintenanceContract`) restent non
>   construits (jugés hors périmètre immédiat en Phase 3 de cette mission).
> - **Ligne 27** (comptes clients à crédit) — `[MIS À JOUR]` :
>   `CommercialAccount`/`Receivable`/`Payment` construits
>   (`processus-double-sources-verite`), plus "hors périmètre".
> - **Ligne 30** (RBAC par station) — `[MIS À JOUR]` : le scoping par
>   station (`UserRole.resourceType/resourceId`) existe et est utilisé
>   massivement (session `processus-double-sources-verite`), plus "RBAC
>   actuel = organisation entière".
>
> Toutes les autres lignes restent valables telles quelles au 2026-09-07 —
> ne pas les considérer comme mises à jour implicitement.

> Produit en application de la mission « Intégration du prototype validé dans
> le véritable Zylo Liquid ». Source du prototype :
> `zylo_liquid_prototype/prototype.html` (audité réellement, 6881 lignes, ~90
> sections `<h1>`-`<h3>` recensées). Compatibilité évaluée contre l'état réel
> du backend au 2026-09-03 : 16 endpoints Niveau 1 tous `TERMINÉ`
> ([phase-2-api.md](phase-2-api.md)) et le frontend déjà construit
> (`zylo-office-frontend`, 4 pages livrées : tableau de bord réseau, liste des
> stations, détail d'une station, détail d'une cuve — voir PR #10/#12/#14/#15).
>
> Granularité : par **page/écran** du prototype (regroupant les sections
> `<h2>`/`<h3>` qui la composent), pas par donnée individuelle — la
> cartographie donnée par donnée (Livrable 2) est faite au fil de
> l'implémentation de chaque page, dans son propre commit/PR, pas ici à
> l'avance (règle « ne pas fabriquer une matrice au conditionnel avant
> d'avoir vérifié chaque donnée un jour »).

## Légende des décisions

- **IMPLEMENTER** — page déjà réalisable avec l'API Niveau 1 existante.
- **IMPLEMENTER APRÈS EXTENSION** — compatible avec le périmètre Niveau 1,
  mais une table/colonne/route manque encore.
- **IMPLEMENTER AVEC NOUVELLE LOGIQUE** — données de base présentes,
  agrégation/algorithme métier à écrire.
- **PRÉSENTER MAIS DÉSACTIVER** — emplacement conservé, données non
  disponibles au Niveau 1, état visuel « à venir ».
- **NE PAS IMPLÉMENTER (hors périmètre)** — dépend d'une capacité que
  Zylo Liquid Niveau 1 ne fournira pas dans un futur proche connu (POS,
  distributeurs, RH, HSE...) ; à ne réévaluer qu'à une décision produit
  explicite d'ouvrir un Niveau 2.

## Matrice

| # | Page du prototype (lignes) | Données clés | Backend Niveau 1 | Décision | État frontend |
|---|---|---|---|---|---|
| 1 | Choix du rôle de démo (3047) | Rôles RBAC | `identity`/`rbac` (Core) | IMPLEMENTER | Absent — écran de démo, pas un besoin produit réel (l'auth réelle existe déjà : login) |
| 2 | Mode dégradé / offline (3081-3151) | Stations concernées, règles offline | Aucun mécanisme offline construit (audit `phase12-offline-readiness-audit.md` = architecture seule) | PRÉSENTER MAIS DÉSACTIVER | Absent |
| 3 | Identité & permissions par module (3131-3151) | Rôle courant, permissions effectives | `rbac`, `modules_registry` (Core, existants) | IMPLEMENTER | Absent (pas de page "mon profil") |
| 4 | **Tableau de bord réseau** (3371-3600) | Santé opérationnelle, intégrité stock, valeur, stations en attention, produit à risque de rupture | endpoints 7/9/16 | **DÉJÀ FAIT** | ✅ `zylo-liquid/page.tsx` (PR #10) |
| 5 | Prévision de rupture / couverture de stock (3436, 6292) | Jours de couverture par produit | Nécessite un débit de consommation — aucune vente/sortie individuelle au Niveau 1 (télémétrie seule, pas de compteurs distributeurs) | NE PAS IMPLÉMENTER (hors périmètre) | Absent |
| 6 | Alarmes à escalader / techniques actives (3573, 3701) | Liste d'alertes actives réseau | endpoint 12 (`alerts`), déjà consommé par la page cuve mais **aucune page dédiée réseau** | **IMPLEMENTER** | Absent — prochaine page à construire |
| 7 | Caisse, encaissements, transactions de shift, clôture, quarts (3627-3701, 4971-5108) | Ventes, moyens de paiement, quarts pompistes | Aucun modèle caisse/POS/pompiste au Niveau 1 (confirmé absent en Phase 1, §20.7 — tables `users`/`user_station_access` encore "à valider", pas de table transaction) | NE PAS IMPLÉMENTER (hors périmètre) `[MIS À JOUR — voir note en tête de fichier]` | Absent |
| 8 | Contribution non pétrolière / boutique (3748) | CA boutique, lavage, vidange | `Station.hasShop/shopName/shopSurfaceM2` = descriptif seul, aucune donnée de revenu | PRÉSENTER MAIS DÉSACTIVER `[MIS À JOUR — voir note en tête de fichier]` | Absent |
| 9 | Écarts de caisse, constats stock hors tolérance (3758-3818) | Réconciliation caisse ↔ stock | Dépend du point 7 (aucune donnée caisse) | NE PAS IMPLÉMENTER (hors périmètre) | Absent |
| 10 | Incidents / alarmes de sécurité (3818-3836) | Incidents non liés aux cuves (sécurité, HSE) | Aucun modèle incident/sécurité | PRÉSENTER MAIS DÉSACTIVER | Absent |
| 11 | Implantation du réseau (carte, 3836) | Géolocalisation des stations | `Station.latitude/longitude` déjà en base | IMPLEMENTER | Absent |
| 12 | **Liste des stations** (3875-3922) | Nom, code, statut, nb cuves actives | endpoint 2 | **DÉJÀ FAIT** | ✅ `stations/page.tsx` (PR #12) |
| 13 | **Détail d'une station** (3922-4034) | Cuves, attributs, fermeture/réactivation | endpoints 2, 3 | **DÉJÀ FAIT** (cuves, attributs, statut) | ✅ `stations/[id]/page.tsx` (PR #14) |
| 13a | ↳ Équipements de distribution, encadrement, pompistes affectés (3946-3965) | Distributeurs, personnel affecté | Aucun modèle distributeur/personnel-station | PRÉSENTER MAIS DÉSACTIVER | Absent |
| 13b | ↳ Documents réglementaires, sécurité incendie/ATEX (3972-3975) | Documents, zones | Aucun modèle | NE PAS IMPLÉMENTER (hors périmètre) `[MIS À JOUR — voir note en tête de fichier, ligne 26]` | Absent |
| 13c | ↳ Console ATG et sondes de mesure (3987-3996) | État sync Holykell, capteurs mappés | endpoints 4, 6 | IMPLEMENTER | Absent — pas encore d'onglet "technique" sur la page station |
| 14 | **Détail d'une cuve** — jauge, composition, historique, technique (4167-4320) | current-state, measurements, calibration, seuils | endpoints 3, 5, 7, 8 | **DÉJÀ FAIT** | ✅ PR #15 (ce tour) |
| 15 | Jaugeage manuel de contrôle (4256-4320, 4924) | Saisie manuelle hauteur/volume pour vérifier la sonde | `TankMeasurement.isCorrection` existe en modèle mais **aucun endpoint de création manuelle** (append-only Holykell uniquement, règle explicite Phase 1) | IMPLEMENTER APRÈS EXTENSION — nécessite un nouvel endpoint de correction explicitement scopé (pas juste réutiliser measurements) | Absent |
| 16 | Incidents/alarmes détail, catalogue de traitement (4422-4494) | Description, actions, traitement attendu | `Alert` porte type/status/résolution ; pas de "catalogue de traitement métier" texte | IMPLEMENTER (champs de base) / PRÉSENTER MAIS DÉSACTIVER (catalogue) | Absent |
| 17 | Fiabilité par fournisseur (4494) | Historique livraisons par fournisseur | Aucun modèle fournisseur ; `DeliveryDetected` n'a pas de fournisseur | PRÉSENTER MAIS DÉSACTIVER | Absent |
| 18 | Journal des réceptions / livraisons détectées (4535, lecture seule) | Liste des livraisons détectées automatiquement | endpoint 10 | **IMPLEMENTER** (lecture seule) | Absent — prochaine page |
| 19 | Bon de livraison, saisie manuelle de réception, contrôle contradictoire (4579-4736) | Saisie manuelle d'une livraison (fournisseur, chauffeur, volumes déclarés) | Contrat explicite : « aucun endpoint de création manuelle » pour les livraisons (Phase 2 §"Endpoint 10") | NE PAS IMPLÉMENTER (hors périmètre, décision produit déjà actée) | Absent |
| 20 | Commandes fournisseurs (4736-4794) | Commandes à déclencher, journal, détail | Aucun modèle commande | NE PAS IMPLÉMENTER (hors périmètre) | Absent |
| 21 | Réconciliation par cuve, décomposition du calcul (4871-4924) | Stock théorique vs réel (livraisons − ventes − stock) | Ventes individuelles absentes (point 5/7) ; livraisons + mesures disponibles mais réconciliation complète impossible sans les sorties | PRÉSENTER MAIS DÉSACTIVER `[MIS À JOUR — un mécanisme de rapprochement (ReconciliationRecord) existe depuis processus-double-sources-verite]` | Absent |
| 22 | Ventes par produit, dernières transactions (4961-4971) | Volumes vendus, tickets | Aucune donnée de vente individuelle | NE PAS IMPLÉMENTER (hors périmètre) `[MIS À JOUR — Sale/ProductSaleTransaction couvrent ce besoin]` | Absent |
| 23 | Tableau consolidé / comparatif inter-stations, tendance conso par cuve (5215-5305) | KPIs réseau agrégés, tendance de consommation | Tendance de conso = dérivée de `measurements` (variation de volume dans le temps) — calculable sans vente individuelle, à un niveau agrégé | IMPLEMENTER AVEC NOUVELLE LOGIQUE (agrégation sur `measurements`, à documenter comme "variation de niveau", jamais qualifiée de "ventes") | Absent |
| 24 | Écarts de réconciliation par pompiste (5305) | Lié au personnel/quarts | Dépend du point 7 | NE PAS IMPLÉMENTER (hors périmètre) | Absent |
| 25 | Rapport journalier par station, historique des rapports (5339-5380) | Stocks en fin de journée + narratif | Stocks fin de journée = dérivable de `network/snapshot` (endpoint 13) ; le "rapport" narratif n'existe pas comme entité | IMPLEMENTER AVEC NOUVELLE LOGIQUE (snapshot quotidien), PRÉSENTER MAIS DÉSACTIVER pour le narratif | Absent |
| 26 | HSE, incendie, maintenance, inspections, contrats (5380-5526) | Équipements sécurité, interventions, contrats | Aucun modèle | NE PAS IMPLÉMENTER (hors périmètre) `[MIS À JOUR — voir note en tête de fichier]` | Absent |
| 27 | Comptes clients à crédit, grand livre, relevé (5643-5836) | Solde, mouvements, échéances | Couche 7 "Crédit client" du schéma cible — confirmée non construite (`phase-1-database.md` : couches 3-7 en attente de décision Core/module) | IMPLEMENTER APRÈS EXTENSION `[MIS À JOUR — voir note en tête de fichier]` | Absent |
| 28 | Comptes de synchronisation Holykell, cycles, sessions (5836-5895) | État des comptes Holykell, historique de sync | `HolykellAccount` + endpoint 6 (sync-status) couvrent l'état courant ; pas d'historique de cycles/sessions en table dédiée | IMPLEMENTER (état courant) / IMPLEMENTER APRÈS EXTENSION (historique) | Absent |
| 29 | Statistiques d'alertes, tables sous surveillance (admin, 5895-5925) | Compteurs d'alertes, observabilité technique | Calculable par agrégation sur `Alert` (comptage par type/période) ; "tables sous surveillance" = observabilité infra, hors périmètre métier | IMPLEMENTER AVEC NOUVELLE LOGIQUE (comptages) / NE PAS IMPLÉMENTER (partie infra) | Absent |
| 30 | Gestion utilisateurs, comptes, droits d'accès par station (6032-6081) | CRUD utilisateurs, permissions par station | `identity`/`rbac` Core existent mais **portée par station** non modélisée (RBAC actuel = organisation entière, pas par station) | IMPLEMENTER (comptes, rôles globaux) / IMPLEMENTER APRÈS EXTENSION (scope station) `[MIS À JOUR — voir note en tête de fichier]` | Absent |
| 31 | Produits carburant, ajout (6120-6145) | CRUD `fuel-products` | endpoint 1 | **IMPLEMENTER** | Absent — page admin à construire (l'API existe déjà) |
| 32 | Clés de configuration, surcharges (6208-6240) | Feature flags par organisation | Aucun modèle | NE PAS IMPLÉMENTER (hors périmètre) | Absent |
| 33 | Prix unitaires et coût d'achat (6261) | Historique des prix par station/produit | endpoints 14, 15, 16 | **IMPLEMENTER** | Absent — page admin à construire |
| 34 | Seuils de niveau de cuve (6282) | Édition des 4 seuils mm | `Tank.heightAlarmMm/heightAlertMm/lowAlarmMm/alertWaterMaxMm` + `PATCH /tanks/{id}` | **IMPLEMENTER** | Partiellement — lecture seule sur la page cuve (onglet technique), édition absente |
| 35 | Seuils de couverture de stock en jours (6292) | Jours avant rupture | Dépend du point 5 (pas de débit de consommation fiable) | NE PAS IMPLÉMENTER (hors périmètre) | Absent |
| 36 | Structure organisationnelle, stations et rattachement (6319-6335) | Organisation → stations | `identity` Core + endpoint 2 | **IMPLEMENTER** | Absent — page admin dédiée |
| 37 | Matrice rôles × vues (6359-6367) | Permissions par rôle, par écran | `rbac` Core (modèle existant), pas d'endpoint HTTP pour lister/éditer les permissions par rôle (confirmé absent, phase-2-api.md §7 "points encore à confirmer") | IMPLEMENTER APRÈS EXTENSION | Absent |

## Synthèse chiffrée

- **DÉJÀ FAIT** : 5 pages (réseau, stations, détail station, détail cuve — 4 PR mergées/ouvertes).
- **IMPLEMENTER immédiatement** (API déjà prête, page manquante) : alertes réseau (#6), carte du réseau (#11), console ATG/sondes sur la page station (#13c), livraisons détectées lecture seule (#18), comptes de sync Holykell (#28 partiel), produits carburant admin (#31), prix admin (#33), édition des seuils de cuve (#34), organisation/stations admin (#36).
- **IMPLEMENTER APRÈS EXTENSION** : jaugeage manuel (#15, nouvel endpoint de correction), historique de sync détaillé (#28), scope RBAC par station (#30, `[MIS À JOUR]` fait), matrice rôles×permissions (#37).
- **IMPLEMENTER AVEC NOUVELLE LOGIQUE** : tendance de consommation par cuve (#23, agrégation measurements), rapport journalier (#25, agrégation snapshot), statistiques d'alertes (#29, agrégation Alert).
- **PRÉSENTER MAIS DÉSACTIVER** : mode dégradé (#2), contribution boutique (#8, `[MIS À JOUR]` fait), incidents sécurité (#10), équipements/personnel station (#13a), catalogue de traitement (#16), fiabilité fournisseur (#17), réconciliation stock complète (#21).
- **HORS PÉRIMÈTRE (crédit client)** : comptes clients à crédit (#27, `[MIS À JOUR]` fait) — couche 7 du schéma cible, nécessite une décision architecturale explicite avant toute table (pas tranchée ici, cf. `phase-1-database.md` §20.7).
- **NE PAS IMPLÉMENTER (hors périmètre confirmé)** : tout ce qui dépend de ventes/transactions individuelles (`[MIS À JOUR]` en partie fait, #7/#22), de distributeurs, de personnel/quarts, de commandes fournisseurs, de HSE/maintenance/incendie (`[MIS À JOUR]` en partie fait, #26), de configuration/feature-flags — Niveau 1 était une télémétrie de cuves, pas un POS ni un ERP RH/maintenance ; ce périmètre a depuis évolué (voir note en tête de fichier).

## Prochaines étapes (ordre proposé, un écran à la fois)

1. Page **Alertes réseau** (#6) — endpoint 12 déjà consommé côté cuve, juste une vue globale + filtre + action de résolution.
2. Page **Livraisons détectées** (#18) — lecture seule, endpoint 10.
3. Onglet **Console ATG / sondes** sur la page station (#13c) — endpoints 4, 6.
4. Page admin **Produits carburant** (#31) — endpoint 1, CRUD déjà exposé par l'API client.
5. Page admin **Prix** (#33) — endpoints 14, 15, 16.
6. Édition des **seuils de cuve** (#34) — `PATCH /tanks/{id}` déjà utilisé pour la création, à réutiliser.

Chaque page suit la méthodologie déjà en place : une branche dédiée, une PR,
aucune donnée simulée, `tsc --noEmit` + `eslint` avant commit.
