# Performance API — concernes FastAPI/transport

Date : 2026-09-11. Fait suite à `phase-1-audit.md` et `phase-2-architecture-decision.md`. Ce document couvre ce qui se passe au niveau HTTP/FastAPI, séparément du problème SQL traité dans `database-performance.md` — les deux sont liés (moins de requêtes SQL = réponses plus rapides à mettre en cache), mais les leviers sont distincts.

## 1. Aucun en-tête `Cache-Control`

Vérifié en Phase 1 : `grep` sur `Cache-Control` dans `app/` → 0 résultat. Vérifié à nouveau au moment de ce document : toujours 0 résultat, y compris dans le travail en cours d'une session parallèle (`app/modules/zylo_liquid/router.py`, `app/core/`) — aucun endpoint ne pose d'en-tête de cache HTTP. Chaque requête, y compris sur des données quasi statiques (produits carburant, villes, devises, config organisation), est recalculée entièrement à chaque appel.

Ceci n'a **pas** été corrigé aujourd'hui, et ce n'est pas la priorité retenue (Phase 2 §3.3) : l'architecture E privilégie un cache serveur en mémoire pour les données quasi statiques plutôt que des en-têtes HTTP côté client, car ce dernier ne réduit pas la charge quand plusieurs clients (utilisateurs) tapent le même endpoint — seul un cache côté serveur bénéficie à tous les appelants. Ajouter `Cache-Control` reste pertinent en complément pour les cas où un même client re-fetch une ressource identique (navigation arrière, re-render), mais c'est un axe secondaire, non entamé.

## 2. Taille des payloads non plafonnée

Aucun mécanisme systématique ne limite la taille d'une réponse (pas de troncature de champs, pas de `response_model` avec projection réduite pour les listes). Le contrôle en place aujourd'hui est indirect et incomplet : `limit: 100` côté frontend (cf. `pagination.md`) borne le nombre de lignes demandées sur les endpoints de liste, mais rien côté serveur n'empêche une requête sans paramètre `limit` de retourner un volume arbitraire, et aucun endpoint ne fixe de plafond dur (`max limit` serveur). Non mesuré comme cause de lenteur actuelle (Phase 1 : le goulot est le nombre d'allers-retours SQL, pas le volume transféré, cf. §5 de `phase-1-audit.md`) — mais c'est un risque de stabilité à couvrir avant que le volume de données ne grandisse, en particulier en même temps que la correction de `pagination.md`.

## 3. `ENVIRONMENT=development` → double logging SQL synchrone

`app/core/database.py:18` :

```python
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    pool_size=20,
    max_overflow=20,
)
```

`echo=True` fait journaliser SQLAlchemy chaque requête deux fois (texte + JSON via son propre logger), en écriture synchrone sur disque — une surcharge réelle mais secondaire par rapport au N+1 (Phase 1, problème #8, classé P1). Recommandation : passer `ENVIRONMENT` à autre chose que `development` (ou introduire un flag dédié, ex. `SQL_ECHO`, découplé de l'environnement applicatif) en dehors des sessions de debug SQL actif — garder `echo=True` disponible à la demande, pas allumé par défaut en dev courant.

## 4. Pool de connexions — configuré, mais ce n'était pas la cause

`app/core/database.py:8-16` (commentaire daté 2026-09-11) : `pool_size=20, max_overflow=20` (40 connexions max), ajusté depuis les valeurs par défaut de SQLAlchemy (`pool_size=5, max_overflow=10`, soit 15 max) qui saturaient dès qu'une seule page station chargeait ses ~15-20 appels en parallèle. L'endpoint Neon utilisé est déjà le pooler (`pgbouncer`, suffixe `-pooler`), largement dimensionné pour ce nombre de connexions applicatives.

**Point de clarification important (Phase 1, confirmé par les mesures)** : ce changement de taille de pool corrige un symptôme de saturation sous charge parallèle, mais **n'était pas la cause de la lenteur mesurée sur `network/summary` et la caisse**. Même avec un pool large, chaque requête individuelle restait lente parce que le nombre d'allers-retours séquentiels par cuve/station était le vrai goulot (cf. `database-performance.md` §1-2) — un pool plus grand permet plus de requêtes *en parallèle*, il n'accélère aucune requête individuelle ni ne réduit leur nombre. Les deux correctifs sont complémentaires, pas substituables l'un à l'autre.

## 5. Ce qui reste à faire

- Décider d'un TTL et d'une politique `Cache-Control` pour les endpoints à données quasi statiques (produits, villes, devises), en complément du cache serveur en mémoire (Phase 2 §3.3) — pas encore commencé.
- Fixer un plafond serveur dur sur les paramètres `limit` des endpoints de liste (indépendamment de la vraie pagination, cf. `pagination.md`), pour qu'aucune requête sans paramètre explicite ne puisse retourner un volume non borné.
- Découpler `echo=True` de `ENVIRONMENT=development` pour éviter la surcharge de logging par défaut.
