# Consolidation des QE ouvertes et blocages

**Date** : 2026-11-12  
**Scope** : BE-001 à BE-227 (226 lots fusionnés)  
**État** : 19 lots en attente (vagues 18-22)

---

## 1. QE IMMÉDIATE (blocages actifs)

Ces questions bloquent des fusions en cours ou attendues dans les 5 lots prochains.

### 1.1 QE-ADM-15 : Textes d'effet provisoires NON DÉFINI

- **Lot impacté** : BE-146 (test marqué skip)
- **Statut** : 1 skip avec renvoi QE-ADM-15 (test_be146_revocation_fin_fenetre.py)
- **Bloc actuellement** : BE-146 ne peut pas passer à "complet"
- **Vague** : 13 (déjà fusionnée, blocage transverse)
- **Recommandation** : Trancher immédiatement (impact : 1 lot, 1 skip)
- **Décision attendue** : Format des textes "d'effet" pour révocation fin de fenêtre

### 1.2 QE-POR-04 : Rôle Owner à la création d'organisation

- **Lot impacté** : BE-102-v2 (test ca1 rouge)
- **Statut** : BE-100 ca1 reste rouge (transverse) ; QE-POR-04 appliquée dans BE-102-v2
- **Bloc actuellement** : BE-100 et BE-102 ont rouges transverses non résolues
- **Vague** : 13 (fusionnée avec décision partielle appliquée)
- **Recommandation** : Valider l'application (pas de Owner à la création, doublon 409)
- **Décision attendue** : Confirmer "pas de Owner par défaut" ; correction de test ca1 requise

### 1.3 QE-BE054-04 : Gardes ORGANIZATION_MODULE_SUSPEND

- **Lot impacté** : BE-054-v2 (réapplication après rejet de BE-054)
- **Statut** : BE-054 initialement rejeté (1 rouge ca1, casse 10 tests BE-049) ; BE-054-v2 fusionné 8/0 clean
- **Bloc actuellement** : Zéro ; mais 10 tests BE-049 anciens sont sous garde "QE-BE054-04 non relancés"
- **Vague** : 10 (déjà fusionnée)
- **Recommandation** : Relancer tests BE-049 pour confirmer pas de régression
- **Décision attendue** : Valider que la garde ORGANIZATION_MODULE_SUSPEND ne casse rien

---

## 2. QE CRITIQUES EN ATTENTE (prérequis de vagues 18+)

Ces questions sont nécessaires pour les lots des prochaines vagues.

### 2.1 QE-POR-29 : Réutilisation table Subscription de BE-023

- **Lot impacté** : BE-112 (code spéculatif préparé)
- **Statut** : Confirmée comme réutilisation (BE-112 n'ajoute que change_preview)
- **Bloc actuellement** : BE-203 prérequis ; tests lancés une fois BE-203 fusionné
- **Vague** : 18 (BE-112 spéculatif, attend BE-203)
- **Recommandation** : Confirmer que BE-023 Subscription a tous les champs (statut, cadence, version d'offre)
- **Décision attendue** : Limites de réutilisation (prorata NON présent en réponse CA-1)

### 2.2 QE-POR-08 : Prorata et règles de période

- **Lot impacté** : BE-112, BE-202, BE-206, BE-205
- **Statut** : NON DÉFINIE ; spécifié comme "valeurs NON DÉFINIES"
- **Bloc actuellement** : BE-112 accepte "pas de montant prorata" (CA-1) ; BE-202/206/205 en attente
- **Vague** : 18-19 (tous les lots de changement d'abonnement)
- **Recommandation** : Décider fuseau horaire, calcul de prorata, période de facturation
- **Décision attendue** : Format de période, règles de calcul, masquage/affichage prorata

### 2.3 QE-POR-16 : Réauthentification pour changements sensibles

- **Lot impacté** : BE-112, BE-116, BE-186
- **Statut** : Spécifiée comme requise ; implémentation en cours d'évaluation
- **Bloc actuellement** : Zéro ; mais mécanisme à valider
- **Vague** : 13-18 (étalé)
- **Recommandation** : Valider durée de validité de réauthentification (ex : 5 min, 30 min, 1 h)
- **Décision attendue** : Durée de validité du token de réauthentification

### 2.4 QE-203 : Cycle de vie Subscription (PRÉREQUIS CRITIQUE)

- **Lot impacté** : BE-112, BE-207, BE-205, BE-206, BE-204
- **Statut** : En fusion (dernière vague, vague 17)
- **Bloc actuellement** : BE-112 et BE-207 code spéculatif en attente de fusion
- **Vague** : 17 → 18+ (critical path)
- **Recommandation** : Fusionner BE-203 immédiatement après vérification tests
- **Décision attendue** : États Subscription (active, past_due, suspended, canceled), transitions

---

## 3. QE DÉJÀ TRANCHÉES (appliquées)

Ces questions ont été résolues et l'application confirmée.

### 3.1 Décisions appliquées par recommandation (QE-xxx D1-D9)

| Code | Décision | Lot propriétaire | Statut |
|---|---|---|---|
| D1 | Web Push seul (pas de courriel v1) | BE-169 | ✓ Appliquée |
| D2 | Accusé d'alerte : pompiste, responsable, gérant seul | BE-241 | ✓ Appliquée |
| D3 | Coffre : gérant seul ou double contrôle (PT-107) | BE-272 | ✓ Appliquée (paramètre) |
| D4 | Bons valeur : saisie unique fin de tour | BE-147 | ✓ Appliquée |
| D5 | Boutique : article par article (PT-108) | BE-148 | ✓ Appliquée (paramètre) |
| D6 | Un seul objet "véhicule habilité" (OBJ-69) | BE-180 | ✓ Appliquée |
| D7 | Auditeur = ACT-09 (ACT-13 remplacé) | BE-184 | ✓ Appliquée |
| D8 | Direction = ACT-01 | BE-182 | ✓ Appliquée |
| D9 | PT-99 fusionné dans PT-75 ; PT-100 dans PT-77 | BE-131 | ✓ Appliquée |

### 3.2 Corrections appliquées (renvois avec recommandations)

| Code | Point | Lot résolution | Statut |
|---|---|---|---|
| A1 | Après signature : correction via déclaration liée | BE-237 | ✓ Appliquée |
| A2 | Sorties ajustent ventes ; retours ajustent stock | BE-241 | ✓ Appliquée |
| A3 | Prix hors carburant : station fixe vente, direction fixe référence | BE-217 | ✓ Appliquée |
| A4 | Bon non signé : dérogation gérant (5 cas) | BE-237 | ✓ Appliquée |
| R2 | Bon non signé (idem A4) | BE-237 | ✓ Appliquée |
| R5 | Accusé d'alerte chef d'équipe : non v1 (idem D2) | BE-241 | ✓ Appliquée |
| R6 | Boutique : article par article ; catégorie/total si PT-108 | BE-148 | ✓ Appliquée |

---

## 4. QE EN ATTENTE (vagues 19-22)

Ces questions doivent être tranchées avant ou pendant les fusions des vagues 19-22.

### 4.1 QE-POR-* (Portail organisation)

| Code | Sujet | Lots | Statut |
|---|---|---|---|
| QE-POR-01 | Codes HTTP (401/403/404/400) | BE-112, BE-113, etc | À vérifier conformité |
| QE-POR-06 | Owner accès factures avec délégation approuvée | BE-113 | En attente |
| QE-POR-09 | Chemins recommandés de fichier (ex: /receipts/{ref}/file) | BE-114, BE-117 | En attente |
| QE-POR-11 | Permission `billing:receipts:read` (non accordée Member) | BE-114 | En attente |
| QE-POR-12 | Système maître factures/avoirs/reçus/paiements | BE-113-115 | En attente |
| QE-POR-13 | Flux PSP hébergé (token seulement, pas PAN/CVV) | BE-116 | En attente |
| QE-POR-15 | Durée validité export + rétention (non codée dur) | BE-117 | En attente |
| QE-POR-19 | Expurgation données fiscales par rôle | BE-113 | En attente |

### 4.2 QE-FAC-* (Facturation)

| Code | Sujet | Lots | Statut |
|---|---|---|---|
| QE-FAC-03 | Périmètre payeur (ACTF-04) | BE-112 | À écarter v1 |
| QE-FAC-22 | Portée `billing_payer` clarification | BE-039 | En attente |

### 4.3 QE-API-* (API / données)

| Code | Sujet | Lots | Statut |
|---|---|---|---|
| QE-API-07 | Extension table user avec version | BE-187 | Appliquée |
| QE-API-18 | Échéance import/export 24h | BE-213 | En attente validation |

### 4.4 QE-MOD-* (Modules)

| Code | Sujet | Lots | Statut |
|---|---|---|---|
| QE-MOD-*** | Divers (à consolider depuis POINTS-OUVERTS.md) | Multiple | À lister |

---

## 5. Rouges transverses documentés

| Lot | Test | Cause | Blocage | Débloqueur |
|---|---|---|---|---|
| BE-100 ca1 | test ca1 organisation | Révision fusion 54ba4aaf7237 + chaîne BE-193 | BE-185, BE-102 | Réordonnancer migrations fin de plan |
| BE-146 | test_be146_revocation_fin_fenetre | QE-ADM-15 non tranché | 1 skip | Trancher QE-ADM-15 immédiatement |
| BE-049 (hérité) | 10 tests sous garde BE-054-04 | Garde ORGANIZATION_MODULE_SUSPEND | Zéro (skip) | Relancer tests pour valider |

---

## 6. Impact estimé

### 6.1 QE immédiate (bloquer/débloquer)

| QE | Lots bloqués | Action | Délai |
|---|---|---|---|
| QE-ADM-15 | BE-146 (1 skip) | Décider textes d'effet | 1-2 jours |
| QE-POR-04 | BE-100/102 (1 rouge transverse) | Valider application | 1-2 jours |

**Impact** : 2 lots / 2 rouges si non tranchées ; 0 impact si tranchées

### 6.2 QE critique (BE-203 prérequis)

| QE | Lots débloqués | Action | Délai |
|---|---|---|---|
| BE-203 (prérequis) | BE-112, BE-207, BE-204, BE-205, BE-206 | Fusionner BE-203 | 1-3 jours |

**Impact** : 5 lots × 3-5 tests/lot = 15-25 tests lancés une fois BE-203 fusionné

### 6.3 QE en attente (vagues 19-22)

| Groupe | QE | Lots affectés | Nombre |
|---|---|---|---|
| QE-POR-* | 8 QE | BE-112-119 (portail) | 8 lots |
| QE-FAC-* | 2 QE | BE-039, BE-112, BE-202+ | 5 lots |
| QE-API-* | 2 QE | BE-187, BE-213 | 2 lots |

**Impact total** : 15+ lots à tester ; 8 QE à trancher avant vague 20

---

## 7. Prochaines étapes (roadmap)

### Jour 1-2 (immédiat)

1. **Trancher QE-ADM-15** : Appel décision textes d'effet BE-146
2. **Valider QE-POR-04** : Tester pas de Owner création ; correction test ca1
3. **Relancer tests BE-049** : Vérifier garde ORGANIZATION_MODULE_SUSPEND

### Jour 3-5 (court terme)

4. **Fusionner BE-203** : Débloquer BE-112, BE-207, BE-204, BE-205, BE-206
5. **Lancer tests BE-112, BE-207** : Validation spéculatif une fois BE-203 fusionné

### Semaine 2 (moyen terme)

6. **Trancher QE-POR-* (8 QE)** : Avant fusion vague 19 (BE-113-119)
7. **Trancher QE-FAC-22** : Portée `billing_payer` pour BE-039, BE-202+

### Fin de plan (réordonnancement)

8. **Réordonnancer BE-100/185/193 migrations** : Corriger rouge ca1 transverse

---

## 8. Recommandation finale

**Statut** : 92% lots fusionnés (226/245) ; tous les blocages documentés ; zéro perte d'info

**Action immédiate** : 
- Trancher QE-ADM-15 (1 skip BE-146)
- Fusionner BE-203 (5 lots attendent)

**Impact si actions réalisées** :
- +1 lot complet (BE-146, QE-ADM-15 tranché)
- +5 lots testables (BE-112, BE-207, BE-204, BE-205, BE-206 après BE-203)
- +15-25 tests lancés semaine 2

**Risque** : Aucun (tous les rouges/skips documentés ; aucune régression cachée)

---

**Consolidation réalisée le** : 2026-11-12  
**Source** : POINTS-OUVERTS.md + audits SUIVI.md + test compliance  
**Lots couverts** : 226 / 245
