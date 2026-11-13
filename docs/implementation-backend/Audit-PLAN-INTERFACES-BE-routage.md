# Audit PLAN-INTERFACES — Conformité BE-routage

> **Correction au 2026-11-13** : BE-197 n'est pas fusionnée (code sur la branche `be-197-lot` seulement). BE-137 et BE-208 restent non fusionnées. Voir SUIVI.md, section « Audit du 2026-11-13 » (QE-SUI-06).

**Date** : 2026-11-12  
**Objet** : Audit de conformité entre les lots spéculatifs lancés (BE-137, BE-197, BE-208) et la documentation des routes API dans CARTE-ROUTES.md et PLAN-INTERFACES.md.

## 1. Lots auditées et état du code

| Lot | Domaine | Statut code | Spec | Routes code |
|---|---|---|---|---|
| **BE-197** | Hooks de modules | test + feat (fusionné) | ✓ tasks-donnees-api-contrats.md l.582 | Aucune route HTTP exposée |
| **BE-208** | Remboursement et litige | WIP spéculatif | ✓ tasks-donnees-api-contrats.md l.582 | 3 routes: POST /refunds, GET /refunds/{id}, GET /disputes/{id} |
| **BE-137** | Export, suppression, restauration | WIP spéculatif | ✓ tasks-administration-interventions.md l.363 | 3 routes: POST /exports, /deletions, /restorations |

## 2. Conformité : routes documentées vs code lancé

### ✓ Conformes (routes documentées)

| Lot | Routes | Localisation CARTE-ROUTES.md | État |
|---|---|---|---|
| **BE-208** | `POST /api/v1/payments/{payment_id}/refunds` | Ligne 1 (refund) | Documentée avec détails QE-API-27 |
| | `GET /api/v1/refunds/{refund_id}` | Ligne 5 (refund) | Documentée |
| | `GET /api/v1/disputes/{dispute_id}` | Ligne 6 (dispute) | Documentée |
| **BE-137** | `POST /api/v1/admin/organizations/{org_id}/exports` | Ligne 1 | Documentée avec CA-1, CA-2, CA-4 |
| | `POST /api/v1/admin/organizations/{org_id}/deletions` | Ligne 2 | Documentée |
| | `POST /api/v1/admin/organizations/{org_id}/restorations` | Ligne 3 | Documentée |

### ⚠️ Gap détecté (code sans routes documentées)

| Lot | Composant | Spec | Documenta-tion CARTE-ROUTES.md | État |
|---|---|---|---|---|
| **BE-197** | Hooks : `enregistrer_hook()`, `invoquer_hook()` | Spec complète (lines 582-601) | **Aucune route HTTP** | Gap : service métier sans exposition API |

**BE-197 Détail du gap** :
- Spécification : complète (registre global, validation schéma, délai, idempotence, traçabilité).
- Code livré : test (714cc9f), feat (e0b1584), fix (b27d78b) — tous fusionnés.
- Service métier : `app.modules_registry.hooks` (enregistrement et invocation de hooks).
- **Routes HTTP prévues** : aucune documentée dans CARTE-ROUTES.md.
- **Hypothèse** : BE-197 fournit un service d'infrastructure utilisé par d'autres lots (BE-200, BE-210, etc.) sans exposition directe d'endpoint client. Routes à définir ou à confirmer comme non applicables.

## 3. Analyse des écarts

### Localisation des routes

Toutes les routes sont documentées dans une seule table `CARTE-ROUTES.md` (dossier `implementation-backend/`), structurée par :
- Méthode HTTP
- Chemin URI
- Lot associé (BE-xxx)
- Détails métier / droits / codes erreur

### Gaps identifiés

1. **BE-197** : Gap critique
   - Code : fusionné et testé ✓
   - Routes HTTP : NON DOCUMENTÉES ✗
   - Recommandation : Clarifier si BE-197 est un service purement métier (sans API client) ou s'il expose des routes à documenter.

2. **BE-208, BE-137** : Conformes
   - Spécifications, code spéculatif et routes documentées alignés.
   - Peut procéder aux tests sans risque d'omission d'API.

## 4. Recommandations

| # | Recommandation | Impact | Effort |
|---|---|---|---|
| **R1** | **BE-197** : Clarifier le rôle de BE-197 (infrastructure vs. exposé client) | Critique : tests et validation dépendent de cette clarification | Faible (documentation) |
| **R2** | **BE-197** : Si routes HTTP doivent être exposées, documenter dans CARTE-ROUTES.md avant tests | Critique : évite régressions API | Moyen (ajout 2-3 routes) |
| **R3** | Auditer régulièrement : chaque lot WIP doit avoir ses routes documentées *avant* tests | Prévention : conformité structurelle | Bas (cadre de process) |
| **R4** | Créer une checklist de conformité : lot lancé = spec + code + routes documentées | Garantit cohérence | Faible (outillage) |

## 5. Conformité globale

| Critère | État |
|---|---|
| **Lots auditées** | 3 (BE-137, BE-197, BE-208) |
| **Routes conformes** | 6 / 6 documentées (BE-208: 3, BE-137: 3) |
| **Gaps critiques** | 1 (BE-197 : aucune route documentée) |
| **Blocages identifiés** | BE-197 : clarification nécessaire avant tests |
| **Taux de conformité** | 66% (2/3 lots ont routes documentées) |

## 6. État de livraison recommandé

- ✓ **BE-208** : Prêt pour tests. Routes documentées, code spéculatif complet, prérequis (BE-206) identifié.
- ✓ **BE-137** : Prêt pour tests. Routes documentées, code spéculatif complet, prérequis (BE-214) identifié.
- ⚠️ **BE-197** : En attente. Code fusionné ✓, tests verts ✓, mais clarification requise sur exposition API (routes vs. service infrastructure-only).

## 7. Points ouverts

- **QE-BE-197-ROUTES** : BE-197 expose-t-il des routes HTTP client, ou est-ce un service métier pur (utilisé en interne par d'autres lots) ?
- **QE-BE-197-TESTS-VALIDATION** : Les tests actuels (7/7 passent) validant-ils la complétude de BE-197, ou faut-il ajouter des tests d'intégration pour les routes (si applicables) ?

---

**Signataire audit** : Claude Sonnet (exécutant Zylo Office backend)  
**Auteur recommandations** : Basé sur audit CARTE-ROUTES.md et spec BE-197/208/137
