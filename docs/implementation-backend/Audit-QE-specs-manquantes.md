# Audit : Spécifications manquantes dans definition-travail/

**Date :** 2026-11-12  
**Domaine :** Backend Zylo Office, lots BE-111 à BE-137 et BE-196 à BE-209  
**Statut :** Audit en cours — spécifications à intégrer dans definition-travail/

## Résumé

- **Lots audités :** 41 (BE-111 à BE-137, BE-196 à BE-209)
- **Spécifications dans implementation-backend/tasks-*.md :** 41/41 ✓
- **Spécifications dans definition-travail/03-plateforme/ :** 2/41 ✗
- **Spécifications manquantes :** 39/41
- **QE créées :** 39 (QE-BE-111-01 à QE-BE-137-01, QE-BE-196-01 à QE-BE-209-01)

## Lots avec spécifications complètes ✓

### BE-119 : Portail organisation — fermeture
- **Spec présente :** `/definition-travail/03-plateforme/portail-organisation-fermeture-BE-119.md`
- **État :** Spec écrite dans definition-travail/
- **Statut :** ✓ COMPLET

### BE-204 : Facture (Invoice)
- **Spec présente :** `/definition-travail/03-plateforme/abonnements-facturation/05-BE-204-facture-api.md`
- **État :** Spec écrite dans definition-travail/
- **Statut :** ✓ COMPLET

## Lots avec spécifications manquantes (à créer) ✗

### Domaine : Portail Organisation (BE-111 à BE-118)

| Lot | Titre | Description | QE Créée |
|-----|-------|-------------|----------|
| **BE-111** | Étapes de cycle de vie (visibilité frontend) | Lire dans definition-travail/ | QE-BE-111-01 |
| **BE-112** | Entitlements affectés (liste et allocation) | Lire dans definition-travail/ | QE-BE-112-01 |
| **BE-113** | Factures : liste et lecture | Lire dans definition-travail/ | QE-BE-113-01 |
| **BE-114** | Reçus : liste et accès | Lire dans definition-travail/ | QE-BE-114-01 |
| **BE-115** | Paiements : liste et lecture | Lire dans definition-travail/ | QE-BE-115-01 |
| **BE-116** | Moyens de paiement : ajout, remplacement, sélection | Lire dans definition-travail/ | QE-BE-116-01 |
| **BE-117** | Demandes de remboursement : création et suivi | Lire dans definition-travail/ | QE-BE-117-01 |
| **BE-118** | Cas d'assistance : ouverture et suivi | Lire dans definition-travail/ | QE-BE-118-01 |

### Domaine : Socle & Administration (BE-120 à BE-137)

| Lot | Titre | Description | QE Créée |
|-----|-------|-------------|----------|
| **BE-120** | Socle | Lire dans definition-travail/ | QE-BE-120-01 |
| **BE-121** | Affectations de rôle globales et temporaires | Lire dans definition-travail/ | QE-BE-121-01 |
| **BE-122** | Journal d'audit append-only | Lire dans definition-travail/ | QE-BE-122-01 |
| **BE-123** | Cas d'intervention (ticket de support) | Lire dans definition-travail/ | QE-BE-123-01 |
| **BE-124** | Modèle de commande opérateur et idempotence | Lire dans definition-travail/ | QE-BE-124-01 |
| **BE-125** | Prévisualisation et confirmation des commandes | Lire dans definition-travail/ | QE-BE-125-01 |
| **BE-126** | Garde de commande (pipeline d'exécution) | Lire dans definition-travail/ | QE-BE-126-01 |
| **BE-127** | Registre des classes d'action sensible (fiche standard) | Lire dans definition-travail/ | QE-BE-127-01 |
| **BE-128** | Approbation distincte (double validation) | Lire dans definition-travail/ | QE-BE-128-01 |
| **BE-129** | Recherche client et organisation | Lire dans definition-travail/ | QE-BE-129-01 |
| **BE-130** | Vue synthèse des états de compte | Lire dans definition-travail/ | QE-BE-130-01 |
| **BE-131** | Listes filtrées des objets de support | Lire dans definition-travail/ | QE-BE-131-01 |
| **BE-132** | Parcours guidé de diagnostic paiement | Lire dans definition-travail/ | QE-BE-132-01 |
| **BE-133** | Parcours guidé de diagnostic abonnement | Lire dans definition-travail/ | QE-BE-133-01 |
| **BE-134** | Suspension et rétablissement d'un tenant | Lire dans definition-travail/ | QE-BE-134-01 |
| **BE-135** | Commande d'entitlement et de module | Lire dans definition-travail/ | QE-BE-135-01 |
| **BE-136** | Préparation d'opérations financières (sans exécution PSP) | Lire dans definition-travail/ | QE-BE-136-01 |
| **BE-137** | Export, suppression et restauration (commandes bloquées) | Lire dans definition-travail/ | QE-BE-137-01 |

### Domaine : Backend Facturation (BE-196 à BE-209)

| Lot | Titre | Description | QE Créée |
|-----|-------|-------------|----------|
| **BE-196** | Cycle de vie OrganizationModule | Lire dans definition-travail/ | QE-BE-196-01 |
| **BE-197** | Hooks de module | Lire dans definition-travail/ | QE-BE-197-01 |
| **BE-198** | Migration de module | Lire dans definition-travail/ | QE-BE-198-01 |
| **BE-199** | Navigation et configuration de module | Lire dans definition-travail/ | QE-BE-199-01 |
| **BE-200** | Plan et PlanVersion | Lire dans definition-travail/ | QE-BE-200-01 |
| **BE-201** | Entitlements et décision d'accès | Lire dans definition-travail/ | QE-BE-201-01 |
| **BE-202** | Devis, checkout et consentement | Lire dans definition-travail/ | QE-BE-202-01 |
| **BE-203** | Cycle de vie Subscription et commandes | Lire dans definition-travail/ | QE-BE-203-01 |
| **BE-205** | Avoir (CreditNote) | Lire dans definition-travail/ | QE-BE-205-01 |
| **BE-206** | Tentative et paiement (PaymentAttempt, Payment) | Lire dans definition-travail/ | QE-BE-206-01 |
| **BE-207** | Reçu (Receipt) | Lire dans definition-travail/ | QE-BE-207-01 |
| **BE-208** | Remboursement et litige (Refund, Dispute) | Lire dans definition-travail/ | QE-BE-208-01 |
| **BE-209** | Webhook PSP entrant | Lire dans definition-travail/ | QE-BE-209-01 |

## Questions d'Équipe créées (QE-BE-xxx-01)

Toutes les QE sont créées avec la recommandation suivante :

**Pattern recommandé :**
```
QE-BE-XXX-01 : Spécification manquante dans definition-travail/

Problème : BE-XXX a une description détaillée dans 
implementation-backend/tasks-*.md mais manque une fiche de 
spécification formelle dans definition-travail/03-plateforme/.

Recommandation : Créer le fichier 
`definition-travail/03-plateforme/[domaine]/XX-BE-XXX-[slug].md`

Format attendu :
- Titre : BE-XXX : [Titre complet]
- Routes API (si applicable)
- Modèles de données (migrations, tables)
- Droits et permissions
- Critères d'acceptation (test d'abord)
- Documentation (docstrings, module doc)
- Source : lien vers tasks-*.md correspondant

Responsable : créateur du lot BE-XXX ou lead backend
```

## Recommandations

### 1. PRIORITÉ HAUTE : Créer les spécifications prioritaires

**Lots critiques pour la cohérence :**
- **BE-200** (Plan et PlanVersion) : Bloc transversal facturation
- **BE-201** (Entitlements) : Bloc transversal facturation
- **BE-203** (Subscription) : Bloc transversal facturation
- **BE-204** ✓ (facture) : Déjà fait
- **BE-205** (Avoir) : En cours (BE-205-back)
- **BE-206** (Payment) : Bloc transversal facturation
- **BE-207** (Receipt) : Bloc transversal facturation

**Action :** Créer les specs de BE-200, 201, 203, 206, 207 en parallèle (blocs facturation).

### 2. PRIORITÉ MOYENNE : Spécifications frontend/portail

**Lots frontaux pour cohérence portail :**
- BE-111 à BE-118 : Portail organisation (dépend des blocs facturation)
- BE-119 ✓ : Déjà fait
- BE-120 à BE-137 : Admin/socle (après blocs facturation)

**Action :** Créer les specs portail après les blocs facturation.

### 3. PROCESSUS À METTRE EN PLACE

**Règle :** Tout lot BE-xxx DOIT avoir une fiche spec dans definition-travail/ 
AVANT de lancer le code spéculatif.

**Flux recommandé :**
1. Écrire la spec dans definition-travail/03-plateforme/
2. Créer la QE de validation si manquement détecté
3. Valider la spec avec l'équipe
4. Créer le lot (worktree, test d'abord, code spéculatif)
5. Fusionner la spec + code en parallèle

## Fichiers à créer

- [ ] `definition-travail/03-plateforme/abonnements-facturation/XX-BE-200-plan.md`
- [ ] `definition-travail/03-plateforme/abonnements-facturation/XX-BE-201-entitlements.md`
- [ ] `definition-travail/03-plateforme/abonnements-facturation/XX-BE-203-subscription.md`
- [ ] `definition-travail/03-plateforme/abonnements-facturation/XX-BE-206-payment.md`
- [ ] `definition-travail/03-plateforme/abonnements-facturation/XX-BE-207-receipt.md`
- [ ] `definition-travail/03-plateforme/portail-organisation/XX-BE-111-etapes.md`
- [ ] ... (autres fiches par domaine)

## Impact

**Bilan :** 39 spécifications à formaliser dans definition-travail/  
**QE créées :** QE-BE-111-01 à QE-BE-137-01, QE-BE-196-01 à QE-BE-209-01 (39 au total)  
**Recommandation :** Créer d'abord les 5 blocs critiques (BE-200, 201, 203, 206, 207), puis portail (BE-111–137)
