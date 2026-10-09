# État de la migration vers le monolithe modulaire

> Découpé depuis [`docs/archive/ARCHITECTURE.md`](../archive/ARCHITECTURE.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

## 5. État de la migration (mise à jour au fil des phases livrées)

Le code vit aujourd'hui presque entièrement dans
`app/modules/zylo_liquid/` (models.py, service.py, router.py de plusieurs
milliers de lignes). La migration extrait les capacités qui ne lui
appartiennent pas, une phase à la fois, chacune livrable et vérifiable
indépendamment (jamais un gros commit unique) :

| Phase | Contenu | Statut |
|---|---|---|
| 0 | Outillage : `import-linter` + premier contrat minimal, intégré CI | fait — `8020c61` |
| 1 | Extraire `app/files/` (`Document`/`DocumentLink`, déjà découplés par `linkedEntityType`/`linkedEntityId` texte libre, pas de FK stricte) | fait — `8020c61` |
| 2 | Extraire `app/location/` (GPS : `GpsDevice`, `TruckPositionPing`, détection d'arrêt...) — FK stricte conservée vers `zyloLiquidTruck.id`, URLs `/api/v1/zylo-liquid/...` gardées stables côté frontend | fait — `8020c61` |
| 3 | Extraire `app/alerts/` (`Alert`, FK strictes conservées vers station/truck/tank/product — pas de redesign de schéma dans cette phase) | fait — `74e772c` |
| 4 | Extraire `app/integrations/holykell/` (client HTTP + DTO) | fait — `a78ca84` (suppression de `scripts/sync_holykell_live.py` non faite, voir note) |
| 5 | `app/shared/events.py` (`subscribe`/`publish`), premier cas d'usage réel : `TruckStopUnqualified` (location → alerts) | fait — `fb648e0` |
| 6 | Étendre les contrats `import-linter` à tous les nouveaux modules, CI bloquante sur violation | fait — `f3d5819` |

Note : Phases 1 et 2 ont été livrées dans un même commit (`8020c61`,
2026-09-15) — travail enchaîné sans commit intermédiaire entre les deux.
Phase 3 et suivantes reprennent la règle « un commit par phase ».

Note Phase 4 (2026-09-16) : le plan prévoyait aussi la suppression de
`scripts/sync_holykell_live.py`, présenté comme "déjà remplacé par la
boucle en process". Vérification faite avant suppression (comme demandé) :
c'est vrai pour sa boucle locale (`poll_once` délègue déjà à
`sync_one_account`, désormais lui-même appuyé sur `holykell.client`), mais
le script a un second rôle distinct non couvert ailleurs — `provision()`
bootstrappe des entités de démo à partir d'une base Postgres externe réelle
(`STATION_SIM_DSN`, le simulateur station_sim), ce que `dev_seed.py` (données
synthétiques) ne fait pas. Script conservé, suppression reportée à une phase
ultérieure si/quand un remplacement de `provision()` existe.

Mettre à jour la colonne Statut quand une phase est livrée (référencer le
commit). Ne pas commencer une phase avant que la précédente soit vérifiée
en production (voir §6).

Décisions déjà actées à ne pas rouvrir sans besoin prouvé :
- Pas de découplage polymorphe complet d'`Alert` (suppression des FK) —
  option future si un vrai besoin de séparation totale apparaît.
- Pas d'extraction physique en microservice d'aucun module — seulement sur
  charge mesurée, jamais par défaut (voir §1).
- Frontend : aligner les mêmes frontières côté Next.js (un écran qui a
  besoin de `files` et `zylo_liquid` appelle deux endpoints distincts) —
  après stabilisation du backend, hors périmètre de ce document.
