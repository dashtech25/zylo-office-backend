# Endpoint 6 : synchronisation Holykell (`holykell-accounts/{id}/sync-status`)

> Découpé depuis [`docs/archive/zylo-liquid/phase-2-api.md`](../../../archive/zylo-liquid/phase-2-api.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

### Endpoint 6 — État de synchronisation Holykell (`holykell-accounts/{id}/sync-status`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 2.1.

| Méthode | Route | Permission |
|---|---|---|
| GET | `/api/v1/zylo-liquid/holykell-accounts/{id}/sync-status` | `zyloLiquid.holykellAccount.read` |

**Écart documenté entre le contrat et le modèle réel (§9.3, issue #33)** :
Point 2 §2.1 affirme « chaque organisation a exactement un compte Holykell
(contrainte déjà en base) » — vérifié faux : aucune `UniqueConstraint` sur
`HolykellAccount.organizationId`. L'endpoint reste correct malgré tout
(adressé par son identifiant explicite dans le chemin, pas déduit de
l'organisation courante), mais l'affirmation du contrat est erronée et
n'a pas été corrigée arbitrairement — si un jour une organisation doit
strictement n'avoir qu'un compte, la contrainte devra être ajoutée après
validation métier explicite, pas devinée ici.

Tests : `tests/test_zylo_liquid_holykell_sync_status.py` (5 cas, incluant
isolation tenant stricte : compte d'une autre organisation → 404).
Preuve à 3 niveaux : `validation_log.md`.
