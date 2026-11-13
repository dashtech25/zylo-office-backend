# Phase 12 — Audit de conformité offline/synchronisation

> Vérifie que les prérequis posés en Phase 1 (grande_phases.md §11) sont bien
> respectés dans le code réellement écrit (Phases 3 à 10) — aucune
> implémentation du mode offline lui-même dans cette phase.

## Checklist

| Prérequis | Vérification | Résultat |
|---|---|---|
| UUID généré côté application, jamais un ID auto-incrémenté | Tous les modèles héritent de `UUIDPrimaryKeyMixin` (`app/shared/models.py`), `default=uuid.uuid4` — vérifié par `grep -rL UUIDPrimaryKeyMixin app/*/models.py` → aucun fichier de modèles ne l'omet | ✅ |
| `createdAt`/`updatedAt` en `TIMESTAMPTZ` sur toutes les tables | Tous les modèles héritent de `TimestampMixin` (`DateTime(timezone=True)`) — même vérification, aucune omission | ✅ |
| Toute écriture passe par un service métier unique, jamais un accès direct à la base depuis le frontend | Le frontend n'a aucun accès direct à PostgreSQL — tout passe par `core/api/client.ts` → API REST. Côté backend, `grep db.add(\|db.commit(` sur tous les `router.py` : une seule occurrence trouvée hors service (`billing/router.py`, `create_plan`) — **corrigée dans cette phase** : le commit est maintenant dans `billing/service.get_or_create_plan`, le router ne fait plus d'accès DB direct | ✅ (après correction) |
| Stratégie de résolution de conflit non figée au niveau du socle | Aucun mécanisme de résolution de conflit n'a été codé en dur dans le socle — chaque futur module reste libre de sa propre stratégie au moment de son implémentation, conformément à la décision de la Phase 1 | ✅ |

## Écart trouvé et corrigé

`app/billing/router.py::create_plan` appelait `await db.commit()` directement
après le service, au lieu de laisser `billing/service.get_or_create_plan`
gérer sa propre transaction — la seule occurrence de ce type dans tout le
projet. Corrigé pour respecter strictement le principe de point d'écriture
unique, indispensable pour qu'une future file d'opérations hors-ligne puisse
intercepter tous les writes au même endroit sans exception à gérer.

Vérifié en réel après correction : `POST /api/v1/billing/plans` retourne
toujours `201` avec le plan créé.

## Conclusion

Le socle actuel (Phases 3 à 10) respecte les prérequis posés pour une future
implémentation du mode offline. Aucune fonctionnalité offline n'est
implémentée à ce stade (conforme à la décision de la Phase 1) ; rien dans le
code actuel ne l'empêche.
