# Audit des chaînes critiques et dépendances
## BE-196 à BE-209, BE-111 à BE-137

> **Obsolète au 2026-11-13.** BE-196, 198, 201, 203, 204 et 214 sont fusionnées ; BE-209 ne l'est pas. Statut à jour : SUIVI.md, section « Audit du 2026-11-13 » (QE-SUI-08).

Date d'audit : 2026-11-12
Vague maximale dans les lots lancés : 22 (BE-115, BE-114)
Vague de BE-209 : 19

---

## Chaîne critique principale vers BE-209 (Webhook PSP entrant)

### Chemin le plus long (vague critique = 19)

```
Vague 1  : BE-001, BE-221
Vague 2  : BE-002, BE-003, BE-032, BE-070, BE-220, BE-223
Vague 3  : BE-004, BE-005, BE-007, BE-021, BE-023, BE-040, BE-072, BE-222, BE-224, BE-232, BE-233, BE-242, BE-256
Vague 4  : BE-024
Vague 5  : BE-073, BE-075, BE-079
Vague 6  : BE-076, BE-078, BE-090, BE-120, BE-150, BE-180
Vague 7  : BE-181, BE-191
Vague 8  : BE-182
Vague 9  : BE-183, BE-184, BE-185, BE-187
Vague 10 : BE-186, BE-188
Vague 11 : BE-189
Vague 12 : BE-190, BE-194, BE-210
Vague 13 : BE-195, BE-200
Vague 14 : BE-196
Vague 15 : BE-197, BE-198, BE-199, BE-201, BE-202
Vague 16 : BE-203
Vague 17 : BE-204
Vague 18 : BE-205, BE-206
Vague 19 : BE-207, BE-208, BE-209, BE-263
```

### Hiérarchie simplifiée (branche BE-206 → BE-209)

```
BE-209 (Webhook PSP entrant)
├── BE-193 (Inbox consommateur)
│   └── BE-192 (Outbox producteur)
│       └── BE-182 (Scope tenant et identifiants)
│           └── BE-181 (Contexte de requête)
│               └── BE-180 (Enveloppe d'erreur et codes HTTP)
│                   └── BE-001 (Vague 1)
│
└── BE-206 (Tentative et paiement) ⚠️ CRITIQUE
    ├── BE-183 (Idempotence)
    │   └── (dépend de BE-180, BE-181, BE-182)
    │       └── BE-001 (Vague 1)
    │
    └── BE-204 (Facture/Invoice)
        ├── BE-183 (Idempotence)
        │   └── ...
        │
        └── BE-203 (Cycle de vie Subscription et commandes)
            ├── BE-023 (Subscription)
            │   └── BE-002
            │       └── BE-001
            │
            ├── BE-192 (Outbox)
            │   └── BE-182
            │       └── BE-181
            │           └── BE-180
            │               └── BE-001
            │
            ├── BE-201 (Entitlements et décision d'accès)
            │   ├── BE-024
            │   ├── BE-190 (RBAC)
            │   ├── BE-196 (Cycle de vie OrganizationModule)
            │   └── BE-200 (Plan et PlanVersion)
            │
            └── BE-202 (Devis, checkout et consentement)
                ├── BE-183
                ├── BE-189 (Membership)
                ├── BE-190 (RBAC)
                └── BE-200 (Plans)
```

**Étapes critiques (ordre de fusion) :**
1. BE-001 (Vague 1) → 0 étapes
2. BE-180 à BE-182 (Vagues 6-8) → 3-5 étapes
3. BE-183 (Vague 9) → 6 étapes
4. BE-192 (Vague 12) → 7 étapes
5. BE-193 (Vague 13) → 8 étapes
6. BE-023 (Vague 3) → 1 étape
7. BE-024 (Vague 4) → 2 étapes
8. BE-190, BE-194, BE-200 (Vague 12) → 7 étapes
9. BE-196, BE-201, BE-202 (Vague 14-15) → 8-9 étapes
10. BE-203 (Vague 16) → 10 étapes
11. **BE-204 (Vague 17) → 11 étapes** ⚠️ CRITIQUE POUR BE-206, BE-207, BE-208, BE-209
12. **BE-206 (Vague 18) → 12 étapes** ⚠️ CRITIQUE POUR BE-207, BE-208, BE-209, BE-111, BE-115
13. BE-207, BE-208, BE-209 (Vague 19) → 13 étapes

---

## Lots bloqués et prérequis manquants (BE-196 à BE-209, BE-111 à BE-137)

### Tableau des blocages

| Lot | Vague | Prérequis critiques | État | Étapes avant lancement |
|---|---|---|---|---|
| BE-196 | 14 | BE-183, BE-189, BE-190, BE-192, BE-195 | EN ATTENTE | 8-9 |
| BE-197 | 16 | BE-180, BE-196 | EN ATTENTE | 9 |
| BE-198 | 16 | BE-183, BE-196 | EN ATTENTE | 9 |
| BE-199 | 16 | BE-190, BE-196 | EN ATTENTE | 9 |
| BE-201 | 15 | BE-024, BE-190, BE-196, BE-200 | EN ATTENTE | 8-9 |
| BE-202 | 15 | BE-183, BE-189, BE-190, BE-200 | EN ATTENTE | 8-9 |
| BE-203 | 16 | BE-023, BE-192, BE-201, BE-202 | EN ATTENTE | 9-10 |
| **BE-204** | **17** | **BE-183, BE-203** | **⚠️ BLOQUÉ** | **10-11** |
| BE-205 | 18 | BE-204 | ⚠️ BLOQUÉ | 11-12 |
| **BE-206** | **18** | **BE-183, BE-204** | **⚠️ BLOQUÉ** | **10-11** |
| BE-207 | 19 | BE-206 | ⚠️ BLOQUÉ | 12-13 |
| BE-208 | 19 | BE-206 | ⚠️ BLOQUÉ | 12-13 |
| BE-209 | 19 | BE-193, BE-206 | ⚠️ BLOQUÉ | 12-13 |
| BE-111 | 21 | BE-110, BE-206 | ⚠️ BLOQUÉ | 12-13 |
| BE-113 | 19 | BE-101, BE-204, BE-205 | ⚠️ BLOQUÉ | 11-12 |
| BE-114 | 20 | BE-101, BE-113, BE-207 | ⚠️ BLOQUÉ | 13-14 |
| **BE-115** | **22** | **BE-101, BE-113, BE-114, BE-206** | **⚠️ BLOQUÉ** | **13-14** |

### États des prérequis critiques

#### Fusion complète (prêts)
- ✅ Vague 1-2 (BE-001, etc.)
- ✅ BE-183 (Idempotence, Vague 9)
- ✅ BE-192 (Outbox, Vague 12)
- ✅ BE-193 (Inbox, Vague 13)

#### Fusion en cours ou à lancer
- 🔄 BE-190 (RBAC, Vague 12) - supposé en cours ou prêt
- 🔄 BE-200 (Plans, Vague 13) - supposé prêt
- 🔄 BE-201, BE-202 (Entitlements/Devis, Vague 15) - supposés à lancer

#### Fusion critique pour les lots spéculatifs
- ⏳ **BE-204 (Facture/Invoice, Vague 17)** - CRITIQUE pour BE-206, BE-207, BE-208, BE-209, BE-111, BE-115
- ⏳ **BE-206 (Paiements, Vague 18)** - CRITIQUE pour BE-207, BE-208, BE-209, BE-111, BE-115

---

## Dépendances parallèles (peuvent être fusionnées ensemble)

### Groupe A : Modules de plateforme (Vague 12-14)
Peuvent être lancés en parallèle (sans dépendances inter-groupe) :
- BE-190 (RBAC) + BE-194 (Catalogue Module) + BE-210 (Configuration intégration)
- BE-200 (Plans) + BE-195 (Manifeste) [BE-195 dépend de BE-194]
- BE-196 (Cycle de vie OrganizationModule) [dépend du groupe précédent]

### Groupe B : Facturation (Vague 14-18)
Dépend du groupe A et doit être séquentiel :
- BE-201 (Entitlements) + BE-202 (Devis) [dépendent de Group A, peuvent être parallèles]
- BE-203 (Cycle Subscription) [dépend de BE-201 + BE-202]
- **BE-204 (Facture)** [dépend de BE-203, puis tout bloque]
- BE-205 (Avoir) [dépend de BE-204]
- **BE-206 (Paiements)** [dépend de BE-204]

### Groupe C : Paiements et portail (Vague 18-22)
Tous dépendent de BE-206 :
- BE-207 (Reçu) + BE-208 (Remboursement) + BE-209 (Webhook PSP)
- BE-111 (Lecture tentatives) + BE-115 (Liste paiements)

---

## Chaînes secondaires et chemins alternatifs

### BE-115 (Paiements : liste et lecture) — Vague 22
**Chemin court vers BE-115 :**

```
BE-115 dépend de : BE-101, BE-113, BE-114, BE-206

BE-114 dépend de : BE-101, BE-113, BE-207
  BE-207 dépend de : BE-206
    BE-206 dépend de : BE-183, BE-204
      BE-204 dépend de : BE-183, BE-203
        BE-203 dépend de : BE-023, BE-192, BE-201, BE-202
          ...

BE-113 dépend de : BE-101, BE-204, BE-205
  BE-204, BE-205 dépendent de : BE-204 (récursif)
    BE-204 dépend de : BE-183, BE-203
      ...
```

**Analyse :**
- BE-115 a 5 niveaux de dépendances
- Chemin critique = BE-204 (vague 17)
- Étapes avant BE-115 : 11-13 (jusqu'à BE-204 + BE-206 + BE-207 + BE-114)

### BE-111 (Lecture des tentatives de paiement) — Vague 21
**Chemin court vers BE-111 :**

```
BE-111 dépend de : BE-110, BE-206
  BE-110 dépend de : BE-101, BE-102, BE-103, BE-200, BE-202
    BE-200, BE-202 dépendent de : BE-200 (vague 13)
  BE-206 dépend de : BE-183, BE-204
    BE-204 dépend de : BE-183, BE-203
      BE-203 dépend de : BE-023, BE-192, BE-201, BE-202
        ...
```

**Analyse :**
- BE-111 a 4 niveaux de dépendances critiques
- Chemin critique = BE-204 (vague 17)
- Étapes avant BE-111 : 11-12 (jusqu'à BE-204 + BE-206)

---

## Lots non-critiques pour BE-209 (mais dépendants)

| Lot | Vague | Prérequis | Dépendants | Statut |
|---|---|---|---|---|
| BE-197 | 16 | BE-180, BE-196 | aucun | Feuille |
| BE-198 | 16 | BE-183, BE-196 | aucun | Feuille |
| BE-199 | 16 | BE-190, BE-196 | aucun | Feuille |
| BE-205 | 18 | BE-204 | BE-113 | Nécessaire pour BE-113 |
| BE-208 | 19 | BE-206 | aucun | Feuille |

---

## Récapitulatif des chaînes critiques

### Chaîne critique unique jusqu'à BE-204
```
BE-001 → BE-002/003 → BE-004/005/007 → BE-024 → BE-071/023/040 
→ BE-072/070 → BE-180 → BE-181 → BE-182 → BE-183 → BE-192 
→ BE-201/202 → BE-203 → BE-204 (BLOQUEUR PRINCIPAL)
```

### Branches parallèles post-BE-204
```
BE-204 →  BE-205  (Avoirs)
          BE-206  (Paiements) ← CRITIQUE pour 7 lots (BE-111, BE-115, BE-207, BE-208, BE-209, BE-263)
          BE-213, BE-214 (API, rétention)

BE-206 →  BE-111, BE-115 (Portail)
          BE-207 (Reçus) → BE-114 (Moyens paiement portail)
          BE-208 (Remboursement)
          BE-209 (Webhook PSP)
          BE-263 (Profil tenant factuel)
```

---

## Code de démarrage spéculatif (statut actuel)

| Lot | Worktree | Branche | Status | Commit |
|---|---|---|---|---|
| BE-206 | BE-206-back | be-206-lot | WIP code spéculatif | 4288072 |
| BE-115 | BE-115-back | be-115-lot | WIP code spéculatif | 7893570 |

---

## Estimation du chemin critique vers BE-209 vert

**Nombre de fusions séquentielles avant BE-209 entièrement vert :**
- Vague 1-9 : 9 fusions (fondation, idempotence, outbox)
- Vague 10-13 : 4 fusions (infrastructure RBAC, plans, modules)
- Vague 14-15 : 2 fusions (entitlements, devis)
- Vague 16 : 1 fusion (abonnements)
- **Vague 17 : 1 fusion (Facture/BE-204)** ⚠️ PIVOT CRITIQUE
- **Vague 18 : 1 fusion (Paiements/BE-206)** ⚠️ DÉVERROUILLE 7 LOTS
- Vague 19 : 3 fusions (Webhook, Reçu, Remboursement)

**Total : 21 fusions pour BE-209 complètement vert (tests + code)**

---

## Recommandations

### Actions immédiatement possibles
1. ✅ Code spéculatif BE-206 déjà préparé (commit 4288072)
2. ✅ Code spéculatif BE-115 déjà préparé (commit 7893570)
3. ⏳ Attendre fusion BE-204 (Invoice) — PIVOT CRITIQUE

### Après fusion BE-204
1. Tester BE-206 avec l'infrastructure Invoice réelle
2. Fusionner BE-206 dès qu'il passe les tests
3. Déverrouille 7 lots : BE-207, BE-208, BE-209, BE-111, BE-115, BE-213, BE-263

### Après fusion BE-206
1. Tester BE-115 avec Payment réel
2. Tester BE-207, BE-208, BE-209 en parallèle
3. Fusionner dans l'ordre : BE-207 → BE-114 → BE-115

---

## Fichier généré
- Audit date : 2026-11-12 16:55 UTC
- Lots lancés : BE-196 à BE-209, BE-111 à BE-137 (49 lots)
- Lots bloqués : 16 lots (BE-204 et dépendants)
- Chaîne critique vers BE-209 : 19 vagues = 21 fusions
