"""Cycle de vie de l'organisation : états et transitions (BE-036).

Module de domaine `identity`. Une organisation (tenant racine, BE-002) porte un
statut stocké dans `organization.status`. Ce module est la seule porte d'entrée
qui modifie ce statut après la création : aucune route ni aucun autre service
ne doit écrire la colonne directement.

États et transitions (recommandation QE-SOC-10, appliquée faute de décision) :

- `active`    : état normal. Peut passer à `suspended` (suspension) ou `closed` (clôture).
- `suspended` : accès suspendu. Peut revenir à `active` (réactivation) ou passer à `closed`.
- `closed`    : état terminal. Aucune transition n'en sort.

Toute autre transition est refusée en 409 `organization_transition_invalide`,
sans écriture ni trace d'audit. Les états stockés gardent le vocabulaire déjà
présent dans le code (`active`, `suspended`, `closed`, cf. BE-002) : la
définition les nomme `actif`, `suspendu`, `clôturé`, mais renommer la valeur
existante imposerait une migration de données sans bénéfice fonctionnel.

Effets (QE-SOC-11) : une suspension ne modifie ni l'abonnement ni la facturation
et ne crée aucune facture. Le blocage de l'ouverture des modules pour une
organisation suspendue relève de la garde d'accès module (BE-025) et n'est pas
câblé ici.

Chaque transition réussie écrit une entrée d'audit dans la même transaction que
la mutation (BE-007), avec l'état avant et après dans `changes`.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.errors import AppError
from app.identity.models import Organization

STATUT_ACTIVE = "active"
STATUT_SUSPENDED = "suspended"
STATUT_CLOSED = "closed"

CODE_TRANSITION_INVALIDE = "organization_transition_invalide"


@dataclass(frozen=True)
class Transition:
    """Une arête de la table d'états : depuis quels statuts, vers lequel, et l'action d'audit."""

    depuis: frozenset[str]
    cible: str
    action_audit: str
    resume: str


# Table unique des transitions. Ajouter une transition ici suffit à l'accepter,
# mais la route correspondante doit aussi être déclarée dans le router.
TRANSITIONS: dict[str, Transition] = {
    "suspension": Transition(
        depuis=frozenset({STATUT_ACTIVE}),
        cible=STATUT_SUSPENDED,
        action_audit="identity.organization.suspend",
        resume="Suspension de l'organisation",
    ),
    "reactivation": Transition(
        depuis=frozenset({STATUT_SUSPENDED}),
        cible=STATUT_ACTIVE,
        action_audit="identity.organization.reactivate",
        resume="Réactivation de l'organisation",
    ),
    "closure": Transition(
        depuis=frozenset({STATUT_ACTIVE, STATUT_SUSPENDED}),
        cible=STATUT_CLOSED,
        action_audit="identity.organization.close",
        resume="Clôture de l'organisation",
    ),
}


async def transitionner_organisation(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, transition: str
) -> Organization:
    """Applique la transition `transition` à l'organisation `organization_id`.

    Contrat :
    - `transition` doit être une clé de `TRANSITIONS` (appel programmatique) ;
      toute autre valeur lève une erreur de programmation, pas une réponse HTTP.
    - L'organisation doit exister (404 `organization_not_found`), mais le contrôle
      d'appartenance et de permission est fait par la route, en amont.
    - Si le statut courant n'est pas dans `Transition.depuis`, 409
      `organization_transition_invalide` : aucune ligne ni audit n'est écrit.

    Garantie de concurrence : la mise à jour est conditionnée au statut source
    (`WHERE status IN depuis`). Si deux requêtes concurrentes tentent la même
    transition, une seule réussit ; l'autre reçoit 409. Le compteur `version`
    (BE-233) est incrémenté à chaque mutation réussie.

    Renvoie l'organisation relue après commit.
    """
    regle = TRANSITIONS[transition]
    organisation = await db.get(Organization, organization_id)
    if organisation is None:
        raise AppError(code="organization_not_found", message="Organisation introuvable.", status_code=404)
    statut_avant = organisation.status
    if statut_avant not in regle.depuis:
        raise AppError(
            code=CODE_TRANSITION_INVALIDE,
            message=f"Transition « {transition} » impossible depuis le statut « {statut_avant} ».",
            status_code=409,
        )

    resultat = await db.execute(
        update(Organization)
        .where(Organization.id == organization_id, Organization.status.in_(regle.depuis))
        .values(status=regle.cible, version=Organization.version + 1)
        .execution_options(synchronize_session=False)
    )
    if resultat.rowcount != 1:
        # Une autre requête a changé le statut entre la lecture et l'écriture.
        await db.rollback()
        raise AppError(
            code=CODE_TRANSITION_INVALIDE,
            message=f"Transition « {transition} » impossible : le statut a changé entre-temps.",
            status_code=409,
        )

    await record_audit_event(
        db,
        organisation.id,
        actor_user_id,
        action=regle.action_audit,
        entity_type="Organization",
        entity_id=organisation.id,
        summary=f"{regle.resume} ({statut_avant} → {regle.cible})",
        changes={"status": {"before": statut_avant, "after": regle.cible}},
    )
    await db.commit()
    await db.refresh(organisation)
    return organisation
