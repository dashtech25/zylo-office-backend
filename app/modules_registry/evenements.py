"""Publication des événements de transition de module (BE-056).

Rôle : chaque transition réussie de la machine d'états (`transitions.transitionner`, BE-041)
produit exactement un événement, écrit dans la table unique `audit_event` (BE-007) dans la
même transaction que la transition. Un événement porte : le nom (`eventName`), le sujet
(`subjectType`, `subjectId`), le scope (`scopeResourceType = 'module'`, `scopeResourceId`), l'acteur
(`actorUserId`), l'origine, un `correlationId` et une charge utile minimale (`payloadMinimal`).

Invariants :
- aucun secret ni contenu métier dans la charge utile : une clé sensible (mot de passe, jeton,
  secret, condensat, cookie, clé d'API) est REJETÉE avant toute écriture (`EVENEMENT_PAYLOAD_SENSIBLE`).
  Contrairement au journal d'audit métier (qui masque silencieusement), un événement est refusé
  entièrement : une erreur de publication doit se voir, pas être corrigée en silence ;
- pas de `commit` ici : l'appelant (la transition) valide la transaction ;
- une organisation nulle est acceptée pour une transition de plateforme (`organizationId` nullable).

Noms d'événements (définition BE-056) : `ModuleVersionPublished` (BE-042, non émis ici),
`TenantModuleAvailabilityChanged`, `ModuleInstallationStateChanged`, `EntitlementAllocationChanged`
(BE-045, non émis ici), `ModuleSuspended`, `ModuleReactivated`, `ModuleUninstalled`.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.audit.service import _CLE_SENSIBLE
from app.core.errors import AppError
from app.core.logging import request_id_ctx
from app.modules_registry.models import ModuleStateTransition
from app.modules_registry.notifications import notifier_destinataires_evenement

EVENEMENT_MODULE_SUSPENDU = "ModuleSuspended"
EVENEMENT_MODULE_REACTIVE = "ModuleReactivated"
EVENEMENT_MODULE_DESINSTALLE = "ModuleUninstalled"
EVENEMENT_DISPONIBILITE_CHANGEE = "TenantModuleAvailabilityChanged"
EVENEMENT_ETAT_INSTALLATION_CHANGE = "ModuleInstallationStateChanged"

EVENEMENTS_MODULE: tuple[str, ...] = (
    "ModuleVersionPublished",
    "TenantModuleAvailabilityChanged",
    "ModuleInstallationStateChanged",
    "EntitlementAllocationChanged",
    "ModuleSuspended",
    "ModuleReactivated",
    "ModuleUninstalled",
)

# États d'installation qui rendent le module disponible ou indisponible pour le tenant.
_ETATS_DISPONIBILITE = frozenset({"active", "inactive"})


def nom_evenement_transition(de_etat: str, vers_etat: str) -> str:
    """Nom de l'événement produit par la transition `de_etat -> vers_etat`.

    Règles, de la plus spécifique à la plus générale :
    - passage à `suspended` : `ModuleSuspended` ;
    - sortie de `suspended` vers `active` : `ModuleReactivated` ;
    - passage à `removed` : `ModuleUninstalled` ;
    - passage entre `active` et `inactive` : `TenantModuleAvailabilityChanged` ;
    - toute autre transition : `ModuleInstallationStateChanged`.
    """
    if vers_etat == "suspended":
        return EVENEMENT_MODULE_SUSPENDU
    if de_etat == "suspended" and vers_etat == "active":
        return EVENEMENT_MODULE_REACTIVE
    if vers_etat == "removed":
        return EVENEMENT_MODULE_DESINSTALLE
    if de_etat in _ETATS_DISPONIBILITE and vers_etat in _ETATS_DISPONIBILITE:
        return EVENEMENT_DISPONIBILITE_CHANGEE
    return EVENEMENT_ETAT_INSTALLATION_CHANGE


def _cle_sensible_dans(valeur: Any) -> str | None:
    """Renvoie la première clé sensible trouvée, en parcourant récursivement dicts et listes."""
    if isinstance(valeur, dict):
        for cle, sous_valeur in valeur.items():
            if _CLE_SENSIBLE.search(str(cle)):
                return str(cle)
            trouvee = _cle_sensible_dans(sous_valeur)
            if trouvee is not None:
                return trouvee
    elif isinstance(valeur, list):
        for element in valeur:
            trouvee = _cle_sensible_dans(element)
            if trouvee is not None:
                return trouvee
    return None


async def publier_evenement(
    db: AsyncSession,
    *,
    nom: str,
    organisation_id: uuid.UUID | None,
    acteur_id: uuid.UUID,
    type_sujet: str,
    id_sujet: uuid.UUID,
    origine: str,
    payload: dict,
    module_id: uuid.UUID | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    """Écrit exactement un événement dans `audit_event` et le renvoie.

    Lève `AppError` `EVENEMENT_PAYLOAD_SENSIBLE` (422) si `payload` contient une clé sensible, à
    n'importe quel niveau ; dans ce cas, aucune ligne n'est ajoutée à la session.
    Le `correlationId` est la valeur passée, sinon l'identifiant de requête courant, sinon un
    identifiant nouveau. `module_id`, quand il est donné, devient le scope de l'événement, ce qui
    permet le filtre `moduleId` de la lecture.
    """
    cle = _cle_sensible_dans(payload)
    if cle is not None:
        raise AppError(
            code="EVENEMENT_PAYLOAD_SENSIBLE",
            message=f"Événement {nom} refusé : la charge utile contient une clé sensible ({cle}).",
            status_code=422,
        )

    evenement = AuditEvent(
        organizationId=organisation_id,
        actorUserId=acteur_id,
        action=nom,
        entityType=type_sujet,
        entityId=id_sujet,
        scopeResourceType="module" if module_id is not None else None,
        scopeResourceId=module_id,
        summary=f"Événement {nom} sur {type_sujet}",
        changes=None,
        request_id=request_id_ctx.get() or f"sans-requete-{uuid.uuid4()}",
        result="success",
        eventId=str(uuid.uuid4()),
        actorType="humain",
        schemaVersion=1,
        subjectType=type_sujet,
        subjectId=id_sujet,
        eventName=nom,
        origin=origine,
        correlationId=correlation_id or request_id_ctx.get() or str(uuid.uuid4()),
        payloadMinimal=payload,
    )
    db.add(evenement)
    await db.flush()
    return evenement


async def publier_evenement_transition(
    db: AsyncSession,
    ligne: ModuleStateTransition,
    *,
    module_id: uuid.UUID | None,
) -> AuditEvent:
    """Publie l'événement d'une transition réussie (appelé par `transitionner`, une seule fois).

    La charge utile ne contient que des états et des versions, jamais d'acteur en clair ni de motif
    libre (le motif peut contenir du texte saisi par l'utilisateur).
    """
    evenement = await publier_evenement(
        db,
        nom=nom_evenement_transition(ligne.fromState, ligne.toState),
        organisation_id=ligne.organizationId,
        acteur_id=ligne.actorId,
        type_sujet=ligne.subjectType,
        id_sujet=ligne.subjectId,
        origine=ligne.origin,
        payload={
            "fromState": ligne.fromState,
            "toState": ligne.toState,
            "stateVersionAfter": ligne.stateVersionAfter,
        },
        module_id=module_id,
        correlation_id=request_id_ctx.get() or str(ligne.operationId),
    )
    # BE-057 : même transaction que la transition ; l'idempotence est portée par create_inbox_item.
    await notifier_destinataires_evenement(db, evenement)
    return evenement
