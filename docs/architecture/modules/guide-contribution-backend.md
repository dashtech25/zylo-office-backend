# Guide de contribution backend d’un module

- **Statut** : guide opérationnel fondé sur les conventions et mécanismes actuellement présents dans le backend.
- **Périmètre** : ajout d’une capacité métier appartenant à un module. Ce guide ne crée aucune permission, règle métier ou politique de facturation. Chaque module doit définir ces éléments dans sa propre tâche approuvée.
- **Sources de référence** : [`convention-module.md`](../convention-module.md), [`conventions-api.md`](../conventions-api.md), [`matrice-dependances.md`](matrice-dependances.md), [`modèle organisations et rôles`](../securite/modele-organisations-roles.md), [`règles de sécurité du module`](../securite/roles-par-module.md).

## 1. Vérifications avant de coder

1. Confirmer que le changement appartient au module concerné et qu’aucune capacité existante de `app/shared/` ou transverse (`app/files/`, `app/alerts/`, `app/location/`) ne possède déjà cette responsabilité.
2. Lire les contrats publics existants avant de les étendre. Le socle ne doit pas importer les modèles ou la logique interne d’un module métier. Consulter [`matrice-dependances.md`](matrice-dependances.md) et le contrat `import-linter` du dépôt.
3. Vérifier l’inventaire des routes, la matrice de permissions, les tests et les migrations déjà présentes. Ajouter seulement les éléments justifiés par le besoin validé.
4. Identifier les décisions manquantes (permission, portée de ressource, audit, unicité, suppression, rétention, migration). Les consigner comme **question ouverte + recommandation**, sans transformer la recommandation en règle métier implicite.

## 2. Structure et responsabilités

Convention attendue, conforme à [`convention-module.md`](../convention-module.md) :

```text
app/modules/<module_code>/
├── models.py       # modèles SQLAlchemy possédés par le module
├── schemas.py      # DTO d’entrée et de sortie Pydantic
├── service.py      # cas d’usage, requêtes et règles validées
├── router.py       # HTTP, dépendances, validation/serialization
├── permissions.py # constantes de permissions approuvées pour ce module
├── seed.py         # registre des permissions déclarées, si le module en a
├── roles_seed.py   # rôles initiaux seulement si spécifiés/approuvés
└── algorithms.py   # fonctions pures, si nécessaires
```

- **Router** : traduit HTTP en appel de service. Il ne contient ni requêtes SQL ni logique de domaine. Déclare explicitement `response_model`, code de succès, pagination et dépendances d’accès.
- **Service** : porte l’opération, reçoit `AsyncSession`, `organization_id` et l’identité de l’acteur lorsqu’ils sont nécessaires. Il applique les vérifications de portée requises même si le router possède déjà des guards. Les autres modules ne consomment que ses fonctions publiques, jamais ses modèles.
- **Repository** : aucun pattern repository séparé n’est établi comme convention obligatoire dans le backend actuel. Les services existants construisent directement des requêtes SQLAlchemy. Recommander une couche repository seulement si la tâche en fixe le besoin et ses interfaces; ne pas l’introduire automatiquement.
- **Modèles** : noms de tables camelCase, noms de champs métier anglais selon convention existante; contraintes en base pour les invariants de données réellement décidés. Toute table métier tenant-scoped porte la clé d’organisation et les requêtes doivent la filtrer.
- **DTO** : utiliser des modèles Pydantic dédiés à la requête et à la réponse. Les champs serveur (identifiant, organisation, horodatages/auteur) ne doivent pas être acceptés en entrée sauf contrat explicite. Réponses SQLAlchemy utilisent `model_config = {"from_attributes": True}` comme dans `app/modules/zylo_tanker/schemas.py`.

Exemples réels de découpage : [`zylo_tanker/router.py`](../../../app/modules/zylo_tanker/router.py), [`zylo_tanker/service.py`](../../../app/modules/zylo_tanker/service.py), [`zylo_tanker/schemas.py`](../../../app/modules/zylo_tanker/schemas.py), [`zylo_tanker/models.py`](../../../app/modules/zylo_tanker/models.py).

## 3. Authentification, organisation, permissions et module actif

### Contexte d’identité et de tenant

- L’identité authentifiée vient de `app.core.security.get_current_user`; ne décoder ni interpréter le JWT dans le module.
- `get_current_organization_id` dans `app/rbac/service.py` lit `X-Organization-Id` (ou valide sa concordance avec le paramètre de chemin `organization_id`) puis appelle la vérification d’appartenance active. L’en-tête est un **sélecteur**, pas une preuve d’autorité.
- Pour les routes de ressource, passer l’organisation validée jusqu’au service et inclure `Model.organizationId == organization_id` dans la lecture ou mutation. Un identifiant global seul (`db.get(Model, id)`) ne suffit pas à prouver l’appartenance au tenant. Les lectures d’un objet étranger/inexistant renvoient le comportement uniforme déjà adopté dans le module (ex. 404 opaque), sauf contrat existant contraire.
- `require_organization_member` vérifie l’appartenance active au tenant, mais ne vérifie pas une permission fonctionnelle. C’est utilisé, par exemple, pour consulter la liste des modules installés.

### Guards de module et permission

- Les routes d’un module activable sont gardées au niveau `APIRouter` par `Depends(require_module_active("<module_code>"))`, comme dans `app/modules/zylo_tanker/router.py` et `app/modules/zylo_liquid/router.py`. Cette garde vérifie que l’installation est active/trial et ensuite l’accès à l’entitlement via `modules_registry.service`.
- La compatibilité legacy `not_configured` n’autorise l’accès que lorsqu’aucune ligne d’entitlement explicite n’existe. Tout statut explicite inconnu échoue en mode fermé. Voir le contrat de [garde-fous de l’affectation par module](../../modules/affectation-par-module/garde-fous.md); ne pas déduire de nouveaux états de ce résumé.
- L’accès à une opération doit aussi porter la dépendance `Depends(require_permission(<CONSTANTE>))` quand une permission approuvée s’applique. Les constantes sont importées depuis le `permissions.py` du module; la permission doit être enregistrée par `seed.py`, sinon `require_permission()` ne pourra pas l’accorder et l’accès échouera.
- `require_permission_scoped*` existe pour des permissions liées à une ressource; employer la variante existante lorsque la tâche exige une portée fine, et suivre ses contrats dans `app/rbac/service.py`. Ne pas créer un mécanisme d’autorisation parallèle.
- Il n’existe pas un ordre de réponse HTTP garanti à exploiter entre toutes les dépendances déclarées sur le routeur et la route. Le graphe FastAPI vérifie les dépendances, avec mise en cache des dépendances partagées. Donc écrire des tests pour les états pertinents (non authentifié, non membre, module inactif/entitlement refusé, permission absente, ressource hors organisation, autorisé) et ne pas faire dépendre le contrat d’une erreur particulière lorsque plusieurs gardes échoueraient simultanément.

Ordre conceptuel des conditions à satisfaire (pas une promesse d’ordre de réponse du framework) :

1. identité authentifiée;
2. organisation sélectionnée, active et accessible par l’utilisateur;
3. module installé/entitled si la route appartient à un module activable;
4. permission nécessaire à l’opération;
5. portée d’une ressource et invariants métier dans le service.

Pour les opérations transverses réellement partagées entre modules, `require_module_active_any(...)` existe; ne l’utiliser que si la route est effectivement montée sous plusieurs préfixes de module et que la règle « un des modules actifs suffit » est conforme au besoin validé.

### Squelette illustratif non enregistré

Ce fragment montre uniquement les points d’intégration. Il n’ajoute volontairement aucune permission, règle métier, modèle, endpoint ou politique; les noms entre chevrons sont des placeholders. Il n’est pas branché à `app/main.py` ou à `app/api/v1/router.py`.

```python
# app/modules/<module_code>/permissions.py
# Déclarer ici seulement les permissions qui ont été approuvées.

# app/modules/<module_code>/router.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.modules_registry.service import require_module_active
from app.rbac.service import get_current_organization_id, require_permission
from app.modules.<module_code> import service
from app.modules.<module_code>.permissions import <APPROVED_PERMISSION>
from app.modules.<module_code>.schemas import <RequestDTO>, <ResponseDTO>

router = APIRouter(dependencies=[Depends(require_module_active("<module_code>"))])

@router.post(
    "/<resource>",
    response_model=<ResponseDTO>,
    status_code=201,
    dependencies=[Depends(require_permission(<APPROVED_PERMISSION>))],
)
async def create_resource(
    data: <RequestDTO>,
    current_user: User = Depends(get_current_user),
    organization_id = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    return await service.create_resource(db, organization_id, current_user.id, data)
```

Avant de le rendre réel, remplacer les placeholders selon le contrat accepté et brancher les hooks/route/seed requis dans les points de composition existants. L’exemple de route active réelle se trouve dans `app/modules/zylo_tanker/router.py`.

## 4. Erreurs, pagination, request ID et audit

- Lever `AppError(code=..., message=..., status_code=..., details=..., field_errors=...)` pour les erreurs attendues du domaine. Les handlers centralisés de `app/core/errors.py` produisent `{error:{code,message,field_errors,details}, request_id}`. Ne pas renvoyer d’exception brute ou de réponse d’erreur ad hoc.
- Les erreurs Pydantic deviennent `validation_error` (422). L’enveloppe n’inclut pas `input` ou `ctx`, pour éviter de refléter les valeurs soumises. Consulter `app/shared/schemas.py` et `docs/architecture/conventions-api.md`.
- Le `RequestIdMiddleware` de `app/core/middleware.py` accepte un ID de corrélation borné ou en génère un et pose `X-Request-Id` et `X-Correlation-Id` sur les réponses. Une route ne génère pas son propre identifiant parallèle.
- Toute liste suit `Page[T]` avec `{data, meta:{total,limit,offset}}` via `app/shared/pagination.py`, sauf si le contrat d’API historique du endpoint impose autre chose.
- `app/audit/service.py::record_audit_event` est utilisé par les opérations de gestion du socle (ex. activation/désactivation des modules). Documenter et appliquer l’audit seulement si la décision de domaine/architecture exige une trace; ne pas inventer une politique globale de journalisation. Quand requis, enregistrer l’acteur, l’organisation, l’action et la cible dans la même transaction que la mutation lorsque cela convient au cas d’usage.

## 5. Enregistrement et migrations

Le module n’est disponible qu’après son enregistrement explicite dans les mécanismes de composition présents : router dans `app/api/v1/router.py`, imports de modèles requis par `app/main.py`/métadonnées Alembic, permissions `seed.py` appelé depuis la composition existante, et entrée de registre du module si celui-ci est activable. Vérifier les hooks de démarrage plutôt que d’ajouter des imports circulaires. Ajouter/mettre à jour les frontières `.importlinter` avant le premier import inter-modules.

Pour une évolution de schéma :

1. migration Alembic dédiée sous `alembic/versions/`; migration **additive**, sans réécriture destructive implicite;
2. relire manuellement `upgrade()` et `downgrade()`; autogenerate est une aide, pas une revue;
3. vérifier que la migration descend de la tête courante et que `alembic heads` retourne exactement une tête (`docs/plans/PLAN_REMISE_SUR_PIED.md` §2);
4. exécuter montée puis downgrade sur base jetable lorsque la tâche le prévoit, puis vérifier la remontée;
5. éviter plusieurs branches de migration simultanées dans une même vague. Si elles existent, rebaser/fusionner explicitement et contrôler à nouveau la tête unique.

`alembic/versions/1ede243704c7_modules_registry_tables.py` et `a6c4753043f0_zylo_tanker_vessel_et_generalisation_.py` sont des exemples historiques de migrations de module/capacité; ne pas réutiliser leurs révisions ni supposer que toute vieille migration illustre l’état cible.

## 6. Tests et inventaires attendus

Créer des tests ciblés de route et de service. Les tests HTTP sont le moyen de vérifier la composition réelle des guards. Suivre les patrons existants dans `tests/test_zylo_tanker_module.py`, `tests/test_isolation_organisations.py`, `tests/test_gardes_permissions_routes.py`, `tests/test_route_inventory.py` et `tests/test_authorization_matrix.py`.

Vérifier selon le changement :

- auth manquante/refusée et contexte d’organisation manquant ou incohérent;
- membre actif autorisé au tenant; utilisateur non membre ou membre inactif refusé;
- lecture et mutation ne franchissent pas les frontières entre organisations, y compris avec un identifiant de ressource appartenant à une autre organisation;
- module inactif refusé; entitlement explicitement refusé conforme au comportement de `modules_registry.service`; module actif avec permission permise fonctionne;
- membre sans permission refusé, et rôle/grant autorisé ne dépasse pas la portée décidée;
- validations d’entrée, codes HTTP, DTO de sortie, pagination et format d’erreur/request ID;
- contraintes d’unicité/concurrence importantes testées au niveau base/service;
- audit testé lorsqu’il est exigé par le contrat;
- route présente dans l’inventaire et protégée; matrice de permissions/documentation régénérée si nécessaire; aucune nouvelle exception dans `route_baseline_sans_permission.txt` sans justification approuvée;
- contrats `lint-imports` satisfaits; aucune dépendance interne croisée hors interface publique.

`tests/test_route_inventory.py` contrôle l’appartenance tenant/opérateur, le registre des routes publiques et le baseline de routes sans permission. `tests/test_gardes_permissions_routes.py` vérifie l’accès/refus sur les gardes observées. Leur réussite ne remplace pas les tests du comportement métier et de l’isolation par ressource.

## 7. Critères d’acceptation d’une contribution backend

Une contribution est prête à revue quand tous les points applicables sont prouvés par le diff ou les commandes/tests consignés :

- [ ] responsabilité du module et interfaces publiques identifiées; aucun import interne interdit;
- [ ] endpoint enregistré uniquement dans le routeur/API composition approuvé;
- [ ] guards d’identité, organisation, module activable et permission présentes selon le contrat;
- [ ] toutes les requêtes/écritures tenant-scoped portent explicitement l’organisation validée; ressource d’un autre tenant non révélée/modifiée;
- [ ] DTO d’entrée/sortie explicites, pagination et erreurs conformes;
- [ ] permissions déclarées dans les constantes du module et seedées si et seulement si approuvées;
- [ ] audit appliqué uniquement lorsqu’exigé et vérifié;
- [ ] tests couvrent autorisé, refus d’accès, isolation inter-organisation, validation et cas métier pertinents;
- [ ] inventaire des routes, matrice, import-linter et documentation cohérents;
- [ ] si migration : upgrade/downgrade revus, migration additive, tête unique et preuve de test selon le plan de travail.

Tout item non applicable doit être marqué « N/A » avec une raison; toute décision non définie est une question ouverte, non un critère satisfait par défaut.

## 8. Questions ouvertes à trancher par le contrat de tâche

Les sources actuelles ne définissent pas une règle unique pour les points suivants. Recommandation de cadrage, sans prétendre que ce soit déjà une politique du produit :

| Question à documenter | Recommandation avant implémentation |
|---|---|
| Une mutation doit-elle être auditée et quels champs sont conservés? | Définir événements, acteur, organisation, cible, rétention et données exclues; appeler `record_audit_event` seulement après accord. |
| Les suppressions sont-elles physiques, logiques ou interdites? | Choisir selon contraintes de conservation et dépendances référentielles; documenter l’effet sur les exports et l’audit. |
| Une entité possède-t-elle une portée plus fine que l’organisation? | Nommer la ressource et utiliser les guards scoped existants avec filtrage service correspondant; éviter une permission org-wide par défaut si le besoin exige une restriction. |
| Les permissions changent-elles l’accès au module ou seulement les opérations? | Garder les responsabilités distinctes : module actif/entitlement via `require_module_active`, autorisation d’action via permission; toute exception doit être explicitement décidée. |
| Quel est le comportement d’idempotence/concurrence des commandes? | Définir la clé d’unicité, le conflit et la politique de retry avant d’exposer la mutation. Le request ID n’est pas une clé d’idempotence. |

