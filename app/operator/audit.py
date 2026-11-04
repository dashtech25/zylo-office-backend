"""Journal des lectures sensibles de la console opérateur (BE-030).

Décision D2 : il n'existe qu'une table d'audit, `audit_event` (propriétaire
BE-007). La table `operatorAuditLog` est retirée par la migration de BE-030 ;
ses lignes ont été reprises dans `audit_event`. Chaque lecture opérateur y
produit exactement une entrée, dont l'action est préfixée `operator.`.

Correspondance des colonnes :
- `actorUserId` : l'opérateur qui consulte ;
- `scopeResourceType` : la portée, `platform` ou `organization` ;
- `scopeResourceId` : l'organisation consultée (portée `organization`), sinon nul ;
- `action` : `operator.<action>`, ex. `operator.organization.read` ;
- `entityType` / `entityId` : la cible consultée ;
- `result` : `success`, `refused` (consultation refusée) ou `error` ;
- `request_id` : identifiant de corrélation de la requête ;
- `changes` : `{"outcome": ...}` seulement, jamais de charge utile de réponse.

Garanties (CA-4) : ni contenu client, ni PII, ni corps de réponse n'est
stocké ; le résumé est un texte fixe construit à partir des codes d'action.

Pourquoi une écriture directe et non `record_audit_event` : ce service exige
une organisation (BE-007 CA-3), or une lecture de portée plateforme (liste des
organisations, statut) n'en a pas. L'entrée est donc construite ici, avec les
mêmes règles que le service (`eventId` unique, request ID, `schemaVersion` 1).
L'écriture valide sa propre transaction (`commit`), car les routes lèvent
parfois une erreur (404) juste après la lecture, et la trace doit subsister.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent

PREFIXE_ACTION = "operator."
PORTEE_PLATEFORME = "platform"
PORTEE_ORGANISATION = "organization"
RESULTATS_REFUS = ("refused", "refus")
RESULTATS_ERREUR = ("error",)


def _resultat(outcome: str) -> str:
    """Traduit l'issue lue par la route en valeur de `audit_event.result`.

    Toute issue inconnue reste une lecture réussie : seul un refus ou une
    erreur change le résultat, pour que le journal ne masque jamais un refus."""
    if outcome in RESULTATS_REFUS:
        return "refused"
    if outcome in RESULTATS_ERREUR:
        return "error"
    return "success"


async def record_operator_read(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    scope: str,
    action: str,
    target_type: str,
    outcome: str,
    request_id: str,
    target_id: uuid.UUID | None = None,
) -> AuditEvent:
    """Ajoute exactement une entrée opérateur dans `audit_event`.

    `scope` vaut `platform` ou `organization` ; pour la portée organisation,
    `target_id` est l'identifiant de l'organisation consultée. `outcome` est
    l'issue métier (`success`, `found`, `not_found`, `refused`...) ; elle est
    conservée dans `changes` sans aucune donnée de réponse. Ne fait pas de
    valide l'entrée par `commit` : une route peut lever une erreur (404) juste
    après la lecture, et la trace doit subsister."""
    entree = AuditEvent(
        organizationId=None,
        actorUserId=actor_user_id,
        action=f"{PREFIXE_ACTION}{action}",
        entityType=target_type,
        entityId=target_id,
        scopeResourceType=scope,
        scopeResourceId=target_id if scope == PORTEE_ORGANISATION else None,
        summary=f"Lecture opérateur : {action} ({target_type}), issue {outcome}.",
        changes={"outcome": outcome},
        request_id=request_id,
        result=_resultat(outcome),
        eventId=str(uuid.uuid4()),
        actorType="humain",
        schemaVersion=1,
    )
    db.add(entree)
    await db.commit()
    return entree
