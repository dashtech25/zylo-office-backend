# Points ouverts : ce qui reste à décider ou à valider

**Date** : 2026-10-10. **Statut** : consolidation. Ce fichier ne contient aucune nouvelle décision. Il reprend ce qui est déjà consigné ailleurs, avec le fichier et la ligne où chaque point est écrit.

Chemins relatifs au dossier `definition-travail/`. « Ligne n » = numéro de ligne au moment de cette consolidation.

## Légende des codes

- **J1** = `00-pilotage/perimetre-declaratif/decisions-appliquees.md` (premier journal de décisions). Ses décisions sont notées D1 à D9.
- **J2** = `00-pilotage/perimetre-declaratif/decisions-appliquees-2.md` (deuxième journal). Ses décisions sont notées A1 à A10, B1 à B16, D-A1, D-E.
- **J3** = `00-pilotage/perimetre-declaratif/decisions-appliquees-3.md` (troisième journal). Ses décisions sont notées R1 à R6, passes B et C.
- **FLX-nnn** : fiche d'une fonction (un cas d'usage). **OBJ-nn** : fiche d'un objet. **ETA-nn** : fiche d'états. **ACT-nn** : acteur.
- **QST-nnn** : fiche de question, dans `07-questions/`.
- **PT-nn** : paramètre candidat, dans `03-plateforme/administration/parametres-candidats.md`.
- **Fonction nn** : numéro de la fonction dans la liste des 175 fonctions (`00-pilotage/perimetre-declaratif/liste-station.md`).
- **Registre lot 1, 2, 3** : `00-pilotage/perimetre-declaratif/registre-questions-lot1.md`, `00-pilotage/perimetre-declaratif/registre-questions-lot2.md`, `00-pilotage/perimetre-declaratif/registre-questions-lot3.md`.

---

## 1. Décisions appliquées par recommandation, à valider

Chaque décision a été prise selon la recommandation de la question concernée, et doit être validée par l'utilisateur.

| Réf. | Décision en une phrase | Où elle est consignée |
|---|---|---|
| D1 | Web Push seul en version 1 ; aucun courriel d'alerte en version 1 | J1 ligne 9 |
| D2 | Accusé d'alerte : pompiste, responsable de tour et gérant seulement ; chef d'équipe non en version 1 (à confirmer par QST-170) | J1 ligne 10 |
| D3 | Coffre : gérant seul par défaut ; double contrôle paramétrable ; PT-107 créé | J1 ligne 11 |
| D4 | Bons valeur : saisie unique en fin de tour ; copie numérique facultative à la réception | J1 ligne 12 |
| D5 | Boutique : vente article par article par défaut ; PT-108 créé | J1 ligne 13 |
| D6 | Un seul objet « véhicule habilité » pour le crédit et le camion de livraison | J1 ligne 14 |
| D7 | L'auditeur reste ACT-09 ; ACT-13 remplacé par ACT-09 quand il désigne l'auditeur | J1 ligne 15 |
| D8 | La direction est ACT-01 | J1 ligne 16 |
| D9 | PT-99 fusionné dans PT-75 ; PT-100 fusionné dans PT-77 (portée différente, voir section 3) | J1 ligne 17 |
| A1 | Après signature, toute correction passe par une déclaration liée ; plus de renvoi après signature | J2 ligne 7 ; réalignement lignes 189 à 204 |
| A2 | Les sorties ajustent les litres vendus ; les retours n'ajustent que le stock (recommandation de QST-005) | J2 ligne 16 |
| A3 | Prix hors carburant : la station fixe son prix de vente, la direction fixe la liste de référence (QST-194) | J2 ligne 33 ; J3 ligne 27 (R3) |
| A4 | Bon non signé : dérogation du gérant possible, cinq cas (décision client D-08) | J2 ligne 40 ; J3 ligne 16 (R2) |
| A5 | OBJ-69 : un seul objet « véhicule habilité » (même décision que D6) | J2 ligne 48 ; J3 ligne 36 (R4) |
| A6 | Commande : ETA-24 porte les états de validation (en attente, validée, rejetée) ; le refus reste une hypothèse (QST-240) | J2 ligne 54 |
| A7 | Représentant du gérant : désigné par écrit, sinon aucun | J2 ligne 63 ; J3 ligne 7 (R1, plus restrictif, voir section 2) |
| A8 | Canal de notification : Web Push seul (option 1 de QST-025) | J2 ligne 72 |
| A10 | Chef d'équipe remplaçant : aligné sur QST-172 (pas d'accès à la caisse ni au NOTA) | J2 ligne 84 |
| R2 | Bon non signé : voir A4 | J3 ligne 16 |
| R5 | Accusé d'alerte du chef d'équipe : non en version 1 (même décision que D2) | J3 ligne 46 |
| R6 | Boutique : article par article par défaut ; vente par catégorie ou total seul si PT-108 l'autorise | J3 ligne 52 |
| - | Retrait de l'état « renvoyé » d'un rapport de tour (ETA-02) ; correction par déclaration liée (FLX-238) | J2 lignes 232 à 246 ; passes lignes 264 à 323 |
| - | « désactivée » devient « suspendue » pour l'état d'une personne, d'une pompe, d'une station ou d'un élément | J2 lignes 206 à 262 |
| - | Passe B : libellé « coordinateur flotte », chemins cassés corrigés, choix du fichier 08-a-trancher par thème | J3 lignes 66 à 107 |
| - | Passe C : en-tête « Identifiants d'origine (lot 3) » devient « Ancien identifiant (historique) » dans 98 fiches ; « désactivé » au masculin remplacé dans 21 fichiers | J3 lignes 109 à 132 |
| - | Corrections B1 à B16 (états de compte à crédit, ETA-23, FLX-272, FLX-247, FLX-189, ACT-01 dans FLX-182, etc.) | J2 lignes 89 à 175 |
| - | Plan : décisions 1 à 4 et 38 questions bloquantes appliquées par recommandation (la décision 4 sur les fichiers de plus de 1 700 lignes a été prise par l'utilisateur) | `00-pilotage/perimetre-declaratif/plan-implementation.md` lignes 684 à 782 |

---

## 2. Contradictions restantes ou tranchées sur une base fragile

| Réf. | Point | Où | Ce qui reste à faire |
|---|---|---|---|
| 2.1 | **Pouvoirs du représentant du gérant (QST-021).** La recommandation limite le représentant à la signature de la livraison et du jaugeage. FLX-153 étend ce pouvoir : le représentant peut signer la correction si le gérant l'a désigné pour ce point. | J3 ligne 12 ; `04-modules/zylo-liquid/flux/FLX-153-controle-du-rapport-par-le-gerant.md` lignes 128 et 165 ; `07-questions/plateforme/roles/QST-021-gerant-tours-representant.md` lignes 27 et 37 | Trancher la portée du représentant. Les versions précédentes (J2 A7 : « peut pointer, contrôler, saisir à la place du gérant ») sont encore dans FLX-105 ligne 275 et FLX-156 ligne 141, qui portent la mention HYPOTHÈSE-QST-021. |
| 2.2 | **Matrice des droits pour ACT-13 et ACT-14.** ACT-13 désigne le lecteur réseau, ACT-14 l'opérateur navire. La matrice n'a pas de colonne pour eux. Le libellé de la ligne 41 a été changé (J3 ligne 71) ; la ligne 76 garde « ACT-14 : L·R » ; la revue R2 parle encore de « Droits ACT-13/14 ». | J1 lignes 35 et 36 ; J2 lignes 161 à 165 ; `03-plateforme/roles-permissions/proposition-roles.md` lignes 41 et 76 ; `08-controles/revues-r2/revue-r2-finale.md` ligne 45 | Décider dans quelle colonne placer les droits du lecteur réseau et de l'opérateur navire, puis corriger la matrice et la revue. |
| 2.3 | **Chef d'équipe (QST-114 et QST-172).** QST-114 est aligné sur QST-172 : le chef d'équipe n'accède ni à la caisse ni au NOTA ; l'écart calculé reste à confirmer. Le droit du chef d'équipe au-delà du cahier est encore ouvert (QST-170). La ligne 21 de la fiche chef d'équipe dit encore que la matrice suit l'existant (S·S), ce qui contredit D2. | J2 ligne 84 ; `07-questions/modules/liquid-tours/QST-114-chef-equipe-remplacant-et-caisse.md` ligne 23 ; `07-questions/plateforme/roles/QST-172-acces-du-chef-d-equipe-a-la-caisse-par-pompiste-et-au-nota.md` ; `07-questions/plateforme/roles/QST-170-droits-du-chef-d-equipe-au-dela-du-cahier-maintenance-documents-accuse.md` ; `02-existant/propositions-par-acteur/chef-equipe.md` ligne 21 (J3 ligne 48) | Corriger la ligne 21 de la fiche chef d'équipe ; trancher QST-170. La ligne 73 de la matrice a déjà été corrigée (J3 ligne 72). |
| 2.4 | **Accusé d'alerte.** D2 est appliquée, mais le registre lot 3 garde QST-035 (acquittement) comme décision en attente, avec QST-170. | Registre lot 3, section « Contestées », lignes 191 à 201 | Confirmer la règle de D2 avec QST-035 et QST-170. |
| 2.5 | **État « renvoyé » retiré, nom de fichier FLX-237 conservé.** Le nom du fichier `04-modules/zylo-liquid/flux/FLX-237-rapport-renvoye-pour-correction.md` a été gardé. Le titre et le contenu ont été réécrits. Le journal 2 dit deux choses : « le nom du fichier et la fonction 137 restent à décider » (ligne 243) et « nom de fichier conservé » (ligne 242). Le bandeau d'historique (ligne 13) peut encore dire que les étapes ne sont pas réécrites. | J2 lignes 232 à 246 ; J2 ligne 243 ; FLX-237 ligne 13 | Décider le nom du fichier et la fonction 137 ; mettre à jour le bandeau de FLX-237. |
| 2.6 | **Retrait de « renvoyé », restes dans d'autres fiches.** QST-080 garde des phrases sur l'état renvoyé (lignes 5, 11 et 15, présentées comme retrait). FLX-131 ligne 100 : le versement peut être fait avant ou après signature. ETA-06 n'a pas de tableau de transitions (ligne 13 seulement). | J2 lignes 245 et 279 ; J2 ligne 121 ; `07-questions/modules/liquid-tours/QST-080-statuts-du-rapport-de-tour.md` ; `04-modules/zylo-liquid/flux/FLX-131-comptage-especes-et-versement.md` ligne 100 ; `04-modules/zylo-liquid/etats/ETA-06-feuille-de-pointage.md` | Confirmer le retrait et décider le sort du versement ; créer ou non le tableau de transitions de ETA-06. |
| 2.7 | **OBJ-69 : mention « HYPOTHÈSE-QST-232 » dans FLX-180, ligne 162.** La décision D6 tranche qu'il n'y a qu'un seul objet, mais la ligne 162 dit encore « la partie crédit reste dans le même objet (HYPOTHÈSE-QST-232) ». La ligne 8 dit « définition à confirmer, QST-232 ». La ligne 116 répète « OBJ-69 » deux fois. | J1 ligne 46 ; J3 lignes 40 à 42 ; `04-modules/zylo-liquid/flux/FLX-180-commande-fournisseur-affecter-camion.md` lignes 8, 116 et 162 | Reformuler les lignes 8, 116 et 162 ; trancher QST-232. |
| 2.8 | **OBJ-69 dans FLX-247.** Les lignes 22 et 55 ne portent pas la référence ; les lignes 7 et 33 ont été modifiées à la place. FLX-180 ligne 57 (suivi GPS) n'a pas été changée. | J3 lignes 41 et 63 ; `03-plateforme/integrations-externes/FLX-247-suivi-des-camions.md` | Vérifier que la référence à OBJ-69 est bien partout où il faut. |
| 2.9 | **Commande fournisseur (FLX-182).** Contradictions relevées : étape de direction (QST-237), états d'attente (QST-244), date prévue (QST-228), périmètre carburant (QST-227), saisie par le gérant ou le responsable de tour (QST-242). Le libellé « ACT-01 retenu (D8) » a été choisi à la place de « secondaire (à confirmer) ». | Registre lot 2, section « Contradictions relevées », lignes 405 à 409 ; J1 ligne 45 ; J2 lignes 143 à 146 ; `04-modules/zylo-liquid/flux/FLX-182-commande-fournisseur-validation-direction.md` | Trancher les cinq questions ; valider le libellé « retenu (D8) ». |
| 2.10 | **Push ou courriel (D1).** `03-plateforme/abonnements/proposition-mvp.md` ligne 30 (« e-mail, compteur ») et `01-sources/syntheses/communications.md` ligne 61 (« le choix entre e-mail et Web Push reste à trancher, QST-025 ») contredisent D1. Le MVP déclenche le courriel à la création des alertes hautes, le code envoie le push seulement (registre lot 3, lignes 285 et 287). | J1 ligne 44 ; registre lot 3 lignes 285 à 287 ; `07-questions/plateforme/notifications/QST-025-notifications-alertes.md` ; `07-questions/plateforme/notifications/QST-407-envoi-du-push-a-la-creation-seulement-ou-aussi-a-l-escalade.md` | Corriger les deux lignes ; trancher QST-025 et QST-407. |
| 2.11 | **Coffre (D3).** Les lignes 43 et 46 de FLX-272 ont été corrigées (J2 lignes 155 et 156). Le mode du coffre (gérant seul ou double contrôle) n'est pas tranché dans les sources. | J1 ligne 11 ; J2 lignes 152 à 157 ; registre lot 3 ligne 293 ; `07-questions/modules/liquid-caisse/QST-099-fond-de-caisse-coffre-et-depot.md` | Trancher le mode de contrôle du coffre. |
| 2.12 | **Prix hors carburant.** Les lignes 16 et 21 de `03-plateforme/organisation/FLX-217-politique-prix.md` n'ont pas été changées. Le titre de FLX-148 (ligne 19, « par catégorie ou total seul ») n'a pas été aligné sur la règle article par article. | J3 lignes 32 et 57 | Aligner ces lignes sur A3 et R6. |
| 2.13 | **Contestées du lot 2 (22 identifiants).** Liste : QST-237, QST-232, QST-228, QST-227, QST-242, QST-017 (deux identifiants), QST-272, QST-285, QST-089, QST-296, QST-051, QST-216, QST-186, QST-171, QST-241, QST-307, QST-049, QST-004, QST-067 (deux identifiants), QST-394. | Registre lot 2, section « Contestées », lignes 344 à 370 | Trancher. |
| 2.14 | **Contestées du lot 3 (10 identifiants).** Liste : QST-035 et QST-170 (droit du chef d'équipe), QST-407 (push à l'escalade), QST-025, QST-061, QST-422 (limites d'export codées en dur, contraires à la règle « rien en dur »), QST-445 (partage d'un bon de commande), QST-086 (caissier ou responsable de tour), QST-311 (restauration dans ou hors périmètre), QST-262 (sigle VAL/CCT ou VAL/LCT), QST-099 (coffre). | Registre lot 3, section « Contestées », lignes 191 à 201 | Trancher. |
| 2.15 | **Incohérences relevées par les rédacteurs du lot 3 (14 points).** Parmi elles : invitations par courriel (ligne 286), impression sans feuille de style (ligne 291), moment de saisie des bons valeur (ligne 292), numérotation des fonctions 151 et 154 (ligne 298). Aucune n'est tranchée. | Registre lot 3, lignes 285 à 298 | Trancher ou renvoyer aux fiches indiquées. |
| 2.16 | **Renvois partiels à confirmer.** Lot 1 : 60 identifiants renvoyés vers 42 fiches existantes. Lot 2 : 53 renvois partiels. Lot 3 : 25 fiches existantes, dont certaines en renvoi partiel. | Registre lot 1, section « Résultat », lignes 5 à 14 ; registre lot 2, section « Résultat », lignes 5 à 12 ; registre lot 3, section « Résultat », lignes 5 à 13 | Confirmer ou créer une fiche distincte pour chaque renvoi partiel. |

---

## 3. Doublons de paramètres à fusionner

Fichier : `03-plateforme/administration/parametres-candidats.md`. Les fusions ne sont pas faites, sauf pour PT-99 et PT-100 (voir dernière ligne).

| Paramètres | Lignes | Sujet | Ce qui reste à faire | Où décidé |
|---|---|---|---|---|
| PT-59 et PT-87 | 71 et 99 | Seuil d'alerte d'expiration et délai avant expiration d'un document réglementaire | Fusionner | J1 ligne 23 |
| PT-50, PT-104 et PT-105 | 62, 116 et 117 | Relance et suspension ; délai de relance et fréquence des relances des clients en retard | Fusionner (vérifier que la portée est la même) | J1 ligne 24 |
| PT-03 et PT-78 | 15 et 90 | Fenêtre de pointage du responsable de tour ; fenêtre de résolution de l'heure d'arrivée | Fusionner | J1 ligne 25 |
| PT-39 et PT-61 | 51 et 73 | Seuil de stock bas ; seuils de réapprovisionnement et d'inventaire | Fusionner | J1 ligne 26 |
| PT-35 et PT-90 | 47 et 102 | Seuil de hausse brutale de livraison ; fenêtre de rapprochement avec la hausse de mesure | Fusionner | J1 ligne 27 |
| PT-99 et PT-100 (fusionnés dans PT-75 et PT-77) | 111, 112 ; cibles 87 et 89 | Délai et fréquence des courriels de notification | Portée différente : PT-99 et PT-100 sont de portée station, PT-75 et PT-77 de portée organisation. Trancher la portée de la cible. | J1 ligne 41 (point 1) ; D9 ligne 17 |

---

## 4. Passages absents des sources

Ces points ne peuvent pas être complétés depuis les sources. Il faut les demander au client ou les retrouver ailleurs.

| Réf. | Ce qui manque | Où c'est consigné |
|---|---|---|
| 4.1 | **Fonction 165 (contrôle interne) : tableau des quatre documents de croisement.** Le cahier annonce « les quatre documents de croisement » avec un tableau « Document, contenu, croisé avec », mais les lignes du tableau sont absentes. La recommandation provisoire est pointage, bons, inventaire et caisse. | `07-questions/modules/liquid-caisse/QST-460-quatre-documents-de-croisement-du-controle-interne.md` ; source : `00-pilotage/perimetre-declaratif/preuves/cahier-gerant-moitie-1/03-passages-non-rattaches.md` lignes 643 à 648 ; archive : `00-pilotage/perimetre-declaratif/preuves-originaux-archive/cahier-gerant-moitie-1.md` lignes 1728 à 1734 ; cas d'usage : `04-modules/zylo-liquid/flux/FLX-265-controle-interne-croisement-pointages-bons-inventaires.md` ligne 209 |
| 4.2 | **Fonction 169 (équipements de caisse de la boutique) : paragraphes sur le terminal de carte, le tiroir-caisse, l'imprimante et la tablette.** Les cahiers ne décrivent ni tiroir, ni imprimante, ni tablette (ligne 1089). Il n'y a pas de bloc « Fonction n° 169 » dans les preuves. Seuls des titres et des principes existent. | Source : `00-pilotage/perimetre-declaratif/preuves-originaux-archive/roles-produits-ventes-controles.md` lignes 1089 et 5863 à 5887 ; cas d'usage : `04-modules/zylo-liquid/flux/FLX-269-equipements-de-caisse-boutique.md` lignes 221 et 227 ; questions : `07-questions/plateforme/integrations/QST-141-mode-de-branchement-des-appareils-de-vente.md`, `07-questions/plateforme/integrations/QST-478-terminal-de-carte-relie-a-l-application-ou-reference-saisie-a-la-main.md`, `07-questions/plateforme/integrations/QST-479-statut-d-un-appareil-de-vente-reseau-de-la-tablette-et-notification-de-panne.md` |
| 4.3 | **Lot 1 : recommandations absentes ou faibles** (QST-141, 142, 143, 168, 174, 175, 191, 194, 195, plus QST-006 et QST-303 partiellement). Par exemple : pas de fournisseur ni de budget pour les appareils de vente ; pas de source pour la trace d'enregistrement ; pas de date d'effet pour le grant individuel. | Registre lot 1, section « Questions dont la recommandation est absente ou faible », lignes 179 à 196 |
| 4.4 | **Lot 2 : 27 identifiants dont la source est absente ou ne dit rien.** Par exemple : montant du fond de caisse (QST-099), catalogue (QST-296), registre des écarts. | Registre lot 2, section « Faibles », lignes 371 à 402 ; cas non classés, lignes 417 à 426 |
| 4.5 | **Lot 3 : 76 lignes de la liste « Faibles » (source absente, ou ne dit rien ; certaines sont des renvois).** Ce sont surtout des notifications, des exports, l'impression, les caisses, la tablette, le poids, la restauration, le dossier du personnel et le coffre. | Registre lot 3, section « Faibles », lignes 202 à 280 ; cas non classés, lignes 311 à 339 |
| 4.6 | **Fonction 171 (stock de cartes, bons, casiers) : réception, achat, stock et reprise des bons valeur non décrits ; montant de la consigne d'un casier absent.** | `04-modules/zylo-liquid/flux/FLX-271-stock-cartes-bons-casiers.md` lignes 72, 163, 169 et 249 ; QST-489 (`07-questions/modules/liquid-caisse/QST-489-montant-de-la-consigne-d-un-casier.md`) |
| 4.7 | **Fonction 96 (fond de caisse minimal) : montant absent des sources.** | `04-modules/zylo-liquid/flux/FLX-196-fond-de-caisse-minimal.md` lignes 187 et 213 |

---

## 5. Écrans et fichiers à définir

| Réf. | Ce qui manque | Où c'est consigné |
|---|---|---|
| 5.1 | **Écran de réception.** La fonction 115 ne peut pas être finalisée tant que l'écran n'est pas défini. Les sources ne disent rien sur cet écran (gérant, point 25, relevé produits). | `04-modules/zylo-liquid/flux/FLX-115-reception-declarer-le-bon-de-livraison.md` lignes 186 et 212 ; J2 lignes 76 à 80 (point A9, rien modifié) |
| 5.2 | **FLX-244 : mention de l'écran de réception.** La recherche « écran de réception » ne trouve rien dans ce fichier. À vérifier ce qui est visé. | `04-modules/zylo-liquid/flux/FLX-244-modifier-entete-declaration-livraison.md` |
| 5.3 | **OBJ-16 : mention de l'écran de réception.** La recherche « écran de réception » ne trouve rien dans ce fichier. À vérifier ce qui est visé. | `04-modules/zylo-liquid/objets/OBJ-16-reception-declaree.md` |

---

## 6. Restes de forme

| Réf. | Point | Où c'est consigné |
|---|---|---|
| 6.1 | **Deux fichiers `08-a-trancher.md` portant le même nom.** Le choix par thème a été fait vers `roles-metier/produits-et-stock/08-a-trancher.md`. Pour QST-297, QST-317 et QST-319, le « point 2 » ne correspond pas au sujet : à vérifier. Le cas de QST-141 (« 07-a-trancher ligne 70 », sans dossier) reste à confirmer. | `roles-metier/produits-et-stock/08-a-trancher.md` ; `roles-metier/responsable-de-tour/08-a-trancher.md` ; J3 lignes 91 à 105 (ambiguïtés A1 et A5) |
| 6.2 | **Mentions « README » génériques dans la règle de rédaction.** Ligne 670 (« registre-ecarts/README » n'existe pas à la racine), ligne 712 (« methode/README » n'existe pas à la racine), lignes 698, 704 et 706 (« README » seul, sans chemin). | `00-pilotage/perimetre-declaratif/conventions.md` lignes 670, 698, 704, 706 et 712 ; J3 lignes 102 à 104 |
| 6.3 | **Féminin « désactivée » : 16 lignes laissées.** Ce sont les cas (déduction optionnelle, options d'interface, etc.) listés dans la passe C. Ce qui reste à décider : étendre la règle « suspendue » au féminin ou non. | J3 ligne 126 et ligne 131 (C-c) ; J2 lignes 253 à 261 (exceptions) |
| 6.4 | **Trois formules laissées.** FLX-101 ligne 75 (« désactivé », action), OBJ-05 ligne 21 (« désactivé seulement »), FLX-206 ligne 104 (« seulement désactivé » devenu « seulement suspendu »). La même formule est traitée différemment. | J3 ligne 130 (C-b) ; `04-modules/zylo-liquid/flux/FLX-101-definir-les-tours.md` ligne 75 ; `04-modules/zylo-liquid/objets/OBJ-05-modele-de-tour.md` ligne 21 ; `03-plateforme/organisation/FLX-206-catalogue-lubrifiants.md` ligne 104 |
| 6.5 | **FLX-273, FLX-274 et FLX-275 hors tranches.** Ils existent mais ne sont rattachés à aucune tranche de lot. | `00-pilotage/ETAT-DU-TRAVAIL.md` ligne 76 ; `03-plateforme/organisation/FLX-273-paiement-fournisseur.md` ; `03-plateforme/integrations-externes/FLX-274-reception-mesures-ventes-systemes-externes.md` ; `03-plateforme/integrations-externes/FLX-275-couche-integration.md` |
| 6.6 | **Anomalies de références de flux à corriger plus tard.** Une référence cite le numéro 57 ; une autre écrit 061 ; 40 numéros de flux sont cités sans fichier ; le numéro 132 est cité dans la fonction 119. | `00-pilotage/perimetre-declaratif/plan-implementation.md` ligne 699 |
| 6.7 | **Forme des identifiants de règles et de critères.** 4 règles et 56 critères n'ont pas les deux chiffres ; 53 numéros sont en collision entre le sens de la liste et le sens du flux. | `00-pilotage/perimetre-declaratif/plan-implementation.md` lignes 715 à 720 |
| 6.8 | **FLX-259 : renvois à corriger.** Les lignes 94 et 208 de `03-plateforme/administration/FLX-259-import-stations-et-rapports.md` renvoient à FLX-142 (qui est un refus de crédit) ; la bonne cible est FLX-242 pour l'import des ventes. Le registre lot 3 cite les lignes 23, 31 et 190 : ces numéros ne correspondent plus au fichier, à vérifier. | `00-pilotage/ETAT-DU-TRAVAIL.md` ligne 72 ; registre lot 3, section « Corrections de renvois (lot 3) », ligne 300 |
| 6.9 | **Erreurs de titres dans les fiches du lot 1.** Les titres (H1) de QST-125 à QST-135 portent d'autres numéros que le nom du fichier (ex. QST-125 titre « QST-164 ») ; le nom de fichier et l'index sont corrects. | Registre lot 2, section « Points relevés hors registre », ligne 429 |
| 6.10 | **Titre de la mission.** Il contient le nom de méthode interdit. C'est le texte de l'utilisateur, gardé tel quel. | `00-pilotage/ETAT-DU-TRAVAIL.md` ligne 73 ; `00-pilotage/perimetre-declaratif/mission-definition-metier.md` |
| 6.11 | **Renvois dans le plan vers des identifiants provisoires du lot 2.** Le registre lot 2 signale que le plan cite encore des identifiants « QST-LOT2-* ». | Registre lot 2, section « Points relevés hors registre », ligne 428 |

---

## 7. Archives

| Réf. | Point | Où c'est consigné |
|---|---|---|
| 7.1 | **11 originaux de plus de 1 700 lignes gardés tels quels** dans `00-pilotage/perimetre-declaratif/preuves-originaux-archive/` (12 fichiers au total). Décision de l'utilisateur. | `00-pilotage/ETAT-DU-TRAVAIL.md` lignes 28 et 62 à 63 ; `00-pilotage/perimetre-declaratif/plan-implementation.md` lignes 778 à 782 |
| 7.2 | **9 fichiers archivés** dans `99-archive/obsoletes-2026-10-10/` (liste complète). | `00-pilotage/ETAT-DU-TRAVAIL.md` ligne 36 ; `99-archive/README.md` |
| 7.3 | **Dossier `99-archive/methode-definition/` « renommé ».** Le dossier existe, il est vide, et son nom est toujours `methode-definition`. `99-archive/README.md` ligne 11 dit « vidé, contenu déplacé vers `00-pilotage/methode/` ». Aucun renommage n'est visible. | `99-archive/methode-definition/` ; `99-archive/README.md` ligne 11 ; à confirmer par l'utilisateur |
| 7.4 | **73 renvois vers les archives.** Ce chiffre est donné par l'utilisateur ; il n'est pas consigné dans les fichiers lus. | Non consigné dans les fichiers lus ; à confirmer |

---

## 8. Validation par l'utilisateur

Aucun lot n'est validé à ce jour. Procédure : `00-pilotage/perimetre-declaratif/plan-implementation.md` lignes 468 à 485.

| Lot | Nombre de fonctions | Où c'est consigné |
|---|---|---|
| Lot 1 | 82 fonctions | `00-pilotage/ETAT-DU-TRAVAIL.md` lignes 42 et 56 |
| Lot 2 | 75 fonctions | `00-pilotage/ETAT-DU-TRAVAIL.md` lignes 44 et 56 |
| Lot 3 | 18 fonctions | `00-pilotage/ETAT-DU-TRAVAIL.md` lignes 46 et 56 |

---

## 9. Reste hors définition

| Réf. | Point | Où c'est consigné |
|---|---|---|
| 9.1 | **Restauration du 21:09 (neuf fichiers).** Les modifications faites après 21:09 sont à vérifier. Le détail de la modification concurrente n'a pas pu être reconstitué. | `00-pilotage/ETAT-DU-TRAVAIL.md` ligne 74 ; `00-pilotage/perimetre-declaratif/registre-questions-lot1.md` section « Incident de traitement », lignes 16 à 21 |
| 9.2 | **OBJ-89-absence-planifiee a disparu et est remplacé par OBJ-91-absence-planifiee.** À confirmer. Le fichier `04-modules/zylo-liquid/objets/OBJ-91-absence-planifiee.md` existe. | `00-pilotage/ETAT-DU-TRAVAIL.md` ligne 75 |
| 9.3 | **Interface et code non commencés.** Cette information n'est écrite dans aucun fichier lu ; à confirmer par l'utilisateur. | Non consigné dans les fichiers lus |
| 9.4 | **Tâches du propriétaire : purge du dump.** Décision déjà prise (purge autorisée). | Mémoire utilisateur : `/home/remy/.claude/projects/-home-remy-Desktop-travail-dashtech-zylo-projet-en-cours-zylo-office-office/memory/project-decisions-2026-10-09.md` |
| 9.5 | **Tâches du propriétaire : rotation des secrets.** | Chemin non retrouvé |
| 9.6 | **Tâches du propriétaire : branches de nettoyage.** Suppression locale des branches fusionnées, après tri des branches `backup/*` et `wip/*`. Aucune suppression distante. | `00-pilotage/nettoyage/audit-espace-partie-2.md` lignes 67 et 68 |

---

## Règles transverses

Les règles transverses de Zylo Liquid et Zylo Office (langue, droits, constats, décisions à trancher, règles de forme) sont dans `00-pilotage/regles-transverses.md`, à lire avant toute tâche.

Décisions à trancher par le propriétaire (section D de ce fichier-là) :

1. Cumul d'un rôle réseau et d'un rôle station : autorisé ou non.
2. Un utilisateur peut-il avoir plusieurs stations.
3. Qui reçoit les droits d'un module à l'activation (propriétaire seul ou attribution explicite).
4. L'activation d'un module exige-t-elle un abonnement actif.
5. Les valeurs de portée sont-elles une liste fermée plutôt que du texte libre.

Décisions d'implémentation (shadcn, duplication, ordre) : voir decisions-implementation.md.

## Back-end : plan implementation-backend (2026-11-03)

Statut : recommandation appliquée, réponse différée. Aucune question n'est validée.
Les 251 questions QE-<CODE>-nn du plan back-end (245 tâches BE-001 à BE-263, BE-261 fusionnée dans BE-024) sont listées en entier dans `implementation-backend/POINTS-OUVERTS.md`. Chaque entrée porte sa recommandation appliquée. Décisions de cadrage à prendre par le propriétaire : frontière tenant/organisation (QE-SOC), décisions finance et PSP (QE-FAC), politique d'accès support (QE-ADM, QE-MOD).

## Points ouverts issus de la mise en œuvre backend (2026-11-05)

Statut : recommandation appliquée, réponse différée. Aucune question n'est validée.

- NON DÉFINI : Recommandation appliquée : sans déclaration de capacité, la garde de module exige un abonnement (fail closed) ; les propriétaires sans abonnement sont refusés sur les routes de module (BE-054). | QE-MOD-14
- NON DÉFINI : Recommandation appliquée : les routes `/organizations/current/modules/{module_id}/...` lisent le tenant dans l'en-tête ; elles restent exceptions explicites du test d'inventaire (BE-054). | QE-BE054-01
- NON DÉFINI : Recommandation appliquée : `/modules/organizations/{id}/activate|deactivate` désignent le module dans le corps ; exception explicite du test d'inventaire (BE-054). | QE-BE054-02
- NON DÉFINI : Recommandation appliquée : 31 tests existants de test_be047, test_be048, test_be050, test_be051 et test_be055 échouent en 403 faute d'abonnement (QE-MOD-14) ; ils seront adaptés par montage d'abonnement, attendus inchangés, à la phase transverse de fin de chantier (BE-054). | QE-BE054-03

- NON DÉFINI : Recommandation appliquée : « sensible » se lit comme le drapeau `sensitive` existant des paramètres ; la permission d'approbation est `settings.approve` ; la section BE-159 n'ayant pas de ligne « Code existant », la réutilisation se fait d'après le code réel (BE-157, BE-154). | QE-PAR-31

## QE-POR-04 : création d'organisation sans rôle Owner (décision appliquée, 2026-11-06)
- Question : POST /api/v1/organizations doit-il attribuer un rôle Owner au créateur ?
- Recommandation (fiche BE-102, « NON DÉFINI : Recommandation appliquée ») : non. POST /api/v1/organizations n'attribue aucun rôle Owner ; un doublon (même nom normalisé, même créateur) retourne 409. Aucun rôle Owner par invitation ; aucun transfert Owner implicite (BE-105, CA-5).
- Décision : appliquée. Le service de production ne crée plus le rôle Owner ; les fixtures de test qui ont besoin d'un propriétaire l'affectent explicitement.
- Conséquence : BE-102 débloqué, puis BE-103 et BE-104.

## QE-SEC-01 : identifiants réels dans l'historique public du back-end (2026-11-13)
- Question : que faire des identifiants commités dans l'historique de `zylo-office-backend` ?
- Constat : le dépôt GitHub `dashtech25/zylo-office-backend` est PUBLIC. Le commit `29aea1b` (« first commit ») contient le `.env` : identifiants de la base Neon, mot de passe de synchronisation Holykell, clé privée VAPID. Ils figurent aussi dans `cd9dd89` et `dd2215d`. La branche `develop` (`ebc7ad0`) est déjà sur GitHub avec cet historique.
- Recommandation (appliquée) : aucun push supplémentaire. Tant que la rotation n'est pas faite, aucun déploiement ni push.
- Décision à prendre par le propriétaire : (1) révoquer et renouveler immédiatement ces identifiants (Neon, Holykell, VAPID) ; (2) passer le dépôt en privé dans l'attente ; (3) décider de la réécriture d'historique (`git filter-repo`, puis force-push), hors mandat actuel.
- Correction 2026-11-13 : le .env de 29aea1b ne contient que APP_NAME, ENVIRONMENT, PORT, CORS_ORIGINS ; aucun identifiant Neon/VAPID trouvé ; Holykell est une simulation. Pas de rotation requise.

## QE-SEC-02 : mot de passe de démonstration en clair dans un script suivi
- Question : `scripts/bootstrap_demo_org.py` contient un mot de passe de démonstration codé en dur (valeur non reproduite ici) dans le dépôt suivi.
- Recommandation (non appliquée, changement de code) : lire ce mot de passe depuis une variable d'environnement sans valeur par défaut, et le faire tourner s'il a servi hors local.

## QE-DEP-01 : port publié incohérent
- Question : quel port publier pour le back-end ?
- Constat : l'image écoute sur `PORT` (3002 par défaut, `EXPOSE 3002`). La doc de production parle de 3004 derrière Dokploy. Le `docker-compose.yml` racine publie `3007:3007`.
- Recommandation (appliquée dans PREREQUIS-DEPLOIEMENT.md) : le port du conteneur est `PORT` ; la publication est fixée par la plateforme. Corriger le mapping du compose racine en `3007:3002` lors de la prochaine modification de ce fichier.

## QE-DEP-02 : ENVIRONMENT en local
- Question : quelle valeur d'ENVIRONMENT pour les tests et le local ?
- Constat : `ENVIRONMENT=dev` est refusé par la configuration (démarrage stoppé faute de secrets propres).
- Recommandation (appliquée) : `ENVIRONMENT=development` en local et pour la suite de tests.

## QE-DEP-03 : version de Python
- Question : Python 3.12 (image) ou 3.13 (venv local) ?
- Recommandation (appliquée) : 3.12 fait foi pour la production ; le venv local peut rester en 3.13 tant que la suite passe.

## QE-SUI-01 : statuts contradictoires dans SUIVI.md
- Question : quel statut retenir pour BE-039, BE-054 et BE-102 ?
- Constat : 223 tâches fusionnées dans SUIVI.md contre 229 motifs de fusion dans l'historique ; BE-039 « en cours » mais fusionné sur une autre ligne ; BE-054 rejeté ; BE-102 suspendu puis remplacé.
- Recommandation (appliquée dans ETAT-GEL-2026-11-13.md) : l'historique git et DEPENDANCES.md font foi ; réconcilier SUIVI.md lors de la prochaine mise à jour.

## QE-SUI-02 : dossier de travail non ignoré
- Question : faut-il ignorer `worktrees/` dans le dépôt back-end ?
- Constat : dossier non suivi de 680 Mo, absent du `.gitignore`.
- Recommandation (non appliquée, pour éviter un changement de hash de gel) : ajouter `/worktrees/` au `.gitignore` lors du prochain commit.

## QE-SUI-03 : compte des fusions et totaux de l'ETAT-GEL (2026-11-13)
- Question : quel compte de tâches fusionnées retenir ? L'ETAT-GEL-2026-11-13.md donne 223 fusionnées, compte BE-133 comme restante et donne des totaux par domaine faux (abonnements-facturation : 40 au lieu de 30).
- Constat : SUIVI.md trace 224 fusions (dont BE-133) ; l'historique git ajoute 6 fusions (BE-196, BE-198, BE-201, BE-203, BE-204, BE-214). Total : 230 fusionnées, 15 restantes.
- Recommandation (appliquée) : SUIVI.md, complété par les motifs de fusion git, fait foi ; section « Audit du 2026-11-13 » ajoutée. ETAT-GEL-2026-11-13.md n'est pas modifié (gel). QE-SUI-01 est résolue : BE-039 fusionnée ; BE-054 et BE-102 fusionnées en v2.

## QE-SUI-04 : fusions tracées dans git et absentes de SUIVI.md (2026-11-13)
- Question : BE-196, BE-198, BE-201, BE-203, BE-204 et BE-214 ont des merges sur develop mais aucune ligne dans SUIVI.md.
- Recommandation (appliquée) : comptées fusionnées (merge présent sur develop, prérequis fusionnés). Les lignes seront ajoutées à SUIVI.md lors de la prochaine mise à jour ; le compte est déjà consolidé dans la section d'audit.

## QE-SUI-05 : BE-209 commitée sur develop sans fusion ni prérequis (2026-11-13)
- Question : BE-209 a des commits `feat(BE-209)` (654d379) et `test(BE-209)` (b221cd2) directement sur develop, alors que son prérequis BE-206 n'est pas fusionnée.
- Recommandation (appliquée) : BE-209 est comptée non fusionnée (restante, bloquée par BE-206). Ces commits sont à rattacher au lot be-209-lot. Le propriétaire doit vérifier, avant déploiement, qu'aucune fonctionnalité de BE-209 n'est mise en service sans son prérequis.

## QE-SUI-06 : BE-197 annoncée fusionnée à tort (2026-11-13)
- Question : Audit-PLAN-INTERFACES-BE-routage.md (2026-11-12) indique BE-197 fusionnée. Les commits 714cc9f, e0b1584 et b27d78b ne sont que sur la branche be-197-lot.
- Recommandation (appliquée) : BE-197 est comptée non fusionnée et prête (prérequis BE-196 fusionnée). Fusion après QE-BE-197-ROUTES (routes HTTP ou service interne). En-tête de l'audit corrigé.

## QE-SUI-07 : BE-261 et BE-279 comptées à tort (2026-11-13)
- Question : BE-261 (fusionnée dans BE-024) est comptée restante dans l'ETAT-GEL, et sa section subsiste dans tasks-fondation-recensement.md. BE-279 est cité comme restante dans l'ETAT-GEL et dans la plage du fichier fondation ; il n'existe pas.
- Recommandation (appliquée) : BE-261 n'est pas comptée (245 tâches) ; BE-279 est sans objet. Retrait de la section BE-261 résiduelle de tasks-fondation-recensement.md à faire lors de la prochaine modification de ce fichier.

## QE-SUI-08 : audits antérieurs au 2026-11-13 (2026-11-13)
- Question : Audit-chaines-dependances.md (lots BE-196 à BE-209 « en attente »), Audit-test-compliance-transversale.md (226 fusionnées sur 245) et Audit-PLAN-INTERFACES-BE-routage.md (BE-197 fusionnée) ne sont plus à jour.
- Recommandation (appliquée) : un en-tête « obsolète » ou « correction » est ajouté à chacun, avec renvoi à SUIVI.md, section « Audit du 2026-11-13 ». Le contenu n'est pas réécrit.

## QE-SUI-09 : résultats de la suite complète non consignés (2026-11-13)
- Question : SUIVI.md ne contient aucun résultat de la suite complète (« à compléter ») et plusieurs lots ont été fusionnés sans relance des tests transverses.
- Recommandation (appliquée au plan, non exécutée) : un run unique de la suite sur la base jetable zylo_t900_test, décidé par le propriétaire, avant déploiement ; résultat à consigner dans SUIVI.md. L'audit du 2026-11-13 n'a lancé aucun test.

## QE-SUI-10 : compte de QE et doublons de ce fichier (2026-11-13)
- Question : la ligne « Back-end : plan implementation-backend » annonçait 199 questions et « 246 tâches BE-001 à BE-279 ». Ce fichier contenait deux exemplaires des blocs QE-SEC-01, QE-SEC-02, QE-DEP-01 à 03, QE-SUI-01 et QE-SUI-02.
- Constat : implementation-backend/POINTS-OUVERTS.md compte 251 QE distinctes ; le plan compte 245 tâches (BE-001 à BE-263, BE-261 fusionnée).
- Recommandation (appliquée) : compte corrigé à 251 QE et 245 tâches ; second exemplaire des blocs supprimé.
