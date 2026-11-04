"""Machine à états générique et journal de transitions (BE-041).

Ce module est le seul point d'écriture des transitions d'état d'un sujet (aujourd'hui : l'installation
d'un module pour un tenant, type `tenant_module`). Il ne connaît pas la table métier du sujet : l'état
courant se lit dans le journal `module_state_transitions` (dernière ligne par `stateVersionAfter`).
Un sujet sans ligne est dans l'état initial `not_installed`, à la version 0.

Ordre des vérifications d'une commande (`transitionner`) :

1. acteur absent -> `MODULE_ACTOR_REQUIRED` (401). Aucune transition sans acteur identifié.
2. origine hors `ORIGINES_TRANSITION` -> `MODULE_TRANSITION_ORIGIN_INVALID` (422).
3. clé d'idempotence déjà journalisée pour ce sujet -> renvoie la ligne initiale, sans effet.
   Cette étape passe avant le contrôle de version : un rejeu envoie la version qu'il avait vue
   avant la première exécution, et doit recevoir le résultat initial, pas un conflit.
4. `version_attendue` différente de la version courante -> `MODULE_STATE_VERSION_CONFLICT` (409).
5. transition absente de `TRANSITIONS_AUTORISEES` pour le type -> `MODULE_TRANSITION_NOT_ALLOWED`
   (409). Aucune ligne n'est créée dans les cas 1, 2, 4 et 5.
6. écriture d'une ligne de journal (acteur, origine, `operationId`, versions avant et après).

Les fonctions ne font que `flush` : c'est à l'appelant de valider la transaction, comme dans
`catalogue.py`. Les erreurs sont des `AppError` (contrat de `core/errors.py`).

Hors périmètre de ce module : les transitions de BE-042 (publication de version), BE-047 (installation
technique), BE-049 (suspension), BE-050 (désinstallation) et la réconciliation BE-052 ne sont pas
listées ici comme *effets* ; elles appellent `transitionner` et fournissent leurs propres gardes. Les
transitions de sortie de `unknown` et `reconciliation_required` sont volontairement absentes : leur
issue dépend de la comparaison des sources d'autorité (BE-052), pas d'une règle générique.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules_registry.evenements import publier_evenement_transition
from app.modules_registry.models import ORIGINES_TRANSITION, ModuleStateTransition

TYPE_SUJET_INSTALLATION = "tenant_module"
ETAT_INITIAL_INSTALLATION = "not_installed"

# États d'une installation tenant-module (matrice-etats-modules-et-droits.md, section 2).
ETATS_INSTALLATION: tuple[str, ...] = (
    "not_installed",
    "provisioning",
    "failed",
    "installed",
    "active",
    "inactive",
    "suspended",
    "removing",
    "removed",
    "unknown",
    "reconciliation_required",
)

# Transitions de l'installation. Chaque couple correspond à une ligne de la matrice ; la matrice
# ne tranche pas les gardes (elles sont à la charge du service appelant). `installed -> inactive`
# est l'état par défaut après installation (« Installed/inactive » dans la matrice).
_TRANSITIONS_INSTALLATION: frozenset[tuple[str, str]] = frozenset(
    {
        ("not_installed", "provisioning"),
        ("provisioning", "installed"),
        ("provisioning", "failed"),
        ("failed", "provisioning"),
        ("installed", "inactive"),
        ("installed", "active"),
        ("inactive", "active"),
        ("active", "inactive"),
        ("active", "suspended"),
        ("suspended", "active"),
        ("installed", "removing"),
        ("inactive", "removing"),
        ("removing", "removed"),
    }
    # « Any -> unknown / reconciliation_required » : toute transition depuis un état vivant.
    | {
        (etat, cible)
        for etat in ETATS_INSTALLATION
        if etat != "removed"
        for cible in ("unknown", "reconciliation_required")
    }
)

# Table des transitions autorisées, par type de sujet. Un type absent n'a aucune transition.
# Publication d'une version de module (BE-042) : draft -> review -> published, et rejet review -> draft.
TYPE_SUJET_VERSION = "module_version"
_TRANSITIONS_VERSION: frozenset[tuple[str, str]] = frozenset(
    {("draft", "review"), ("review", "published"), ("review", "draft")}
)

TRANSITIONS_AUTORISEES: dict[str, frozenset[tuple[str, str]]] = {
    TYPE_SUJET_INSTALLATION: _TRANSITIONS_INSTALLATION,
    TYPE_SUJET_VERSION: _TRANSITIONS_VERSION,
}


def transition_autorisee(type_sujet: str, de_etat: str, vers_etat: str) -> bool:
    """Vrai si la table `TRANSITIONS_AUTORISEES` contient la transition `de_etat -> vers_etat`.

    Fonction pure, sans accès base. Un type de sujet inconnu n'autorise rien."""
    return (de_etat, vers_etat) in TRANSITIONS_AUTORISEES.get(type_sujet, frozenset())


async def _derniere_ligne(
    db: AsyncSession, type_sujet: str, id_sujet: uuid.UUID
) -> ModuleStateTransition | None:
    """Renvoie la ligne de journal de version la plus haute du sujet, ou None."""
    return (
        await db.execute(
            select(ModuleStateTransition)
            .where(
                ModuleStateTransition.subjectType == type_sujet,
                ModuleStateTransition.subjectId == id_sujet,
            )
            .order_by(ModuleStateTransition.stateVersionAfter.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def etat_courant(db: AsyncSession, type_sujet: str, id_sujet: uuid.UUID) -> tuple[str, int]:
    """Renvoie `(état, version)` courant d'un sujet, lus dans le journal.

    Sans ligne : `(not_installed, 0)` pour `tenant_module`. Pour un type sans état initial connu,
    l'état est la chaîne vide et la version 0 : toute transition sera alors refusée."""
    derniere = await _derniere_ligne(db, type_sujet, id_sujet)
    if derniere is None:
        etat_initial = ETAT_INITIAL_INSTALLATION if type_sujet == TYPE_SUJET_INSTALLATION else ""
        return etat_initial, 0
    return derniere.toState, derniere.stateVersionAfter


async def _ligne_par_cle(
    db: AsyncSession, type_sujet: str, id_sujet: uuid.UUID, cle: str
) -> ModuleStateTransition | None:
    return (
        await db.execute(
            select(ModuleStateTransition).where(
                ModuleStateTransition.subjectType == type_sujet,
                ModuleStateTransition.subjectId == id_sujet,
                ModuleStateTransition.idempotencyKey == cle,
            )
        )
    ).scalar_one_or_none()


async def transitionner(
    db: AsyncSession,
    *,
    type_sujet: str,
    id_sujet: uuid.UUID,
    vers_etat: str,
    version_attendue: int,
    acteur_id: uuid.UUID | None,
    origine: str,
    cle_idempotence: str,
    organisation_id: uuid.UUID | None = None,
    motif: str | None = None,
    operation_id: uuid.UUID | None = None,
    module_id: uuid.UUID | None = None,
) -> ModuleStateTransition:
    """Applique la transition du sujet vers `vers_etat` et l'inscrit dans le journal.

    Paramètres :
    - `version_attendue` : version d'état que l'appelant a lue (0 pour un sujet neuf) ;
    - `acteur_id` : utilisateur ou identité de service qui agit, obligatoire ;
    - `origine` : une valeur de `ORIGINES_TRANSITION` ;
    - `cle_idempotence` : clé fournie par l'appelant, unique par sujet ;
    - `operation_id` : identifiant de l'opération, généré si absent (renvoyé par la ligne) ;
    - `module_id` : module auquel se rapporte l'installation (BE-056) ; devient le scope de
      l'événement publié et permet le filtre `moduleId` de la lecture d'audit.

    Renvoie la ligne de journal créée, ou la ligne initiale en cas de rejeu. Une transition réussie
    publie exactement un événement (BE-056, `evenements.publier_evenement_transition`) dans la même
    transaction ; un rejeu ou une transition refusée n'en publie aucun. Lève `AppError` :
    `MODULE_ACTOR_REQUIRED` (401), `MODULE_TRANSITION_ORIGIN_INVALID` (422),
    `MODULE_STATE_VERSION_CONFLICT` (409), `MODULE_TRANSITION_NOT_ALLOWED` (409).

    Concurrence : deux commandes concurrentes qui voient la même version tentent d'écrire la même
    `stateVersionAfter` ; la contrainte unique du journal en fait échouer une, qui reçoit un conflit
    de version. Un rejeu concurrent avec la même clé renvoie la ligne déjà écrite.
    """
    if acteur_id is None:
        raise AppError(
            code="MODULE_ACTOR_REQUIRED",
            message="Transition refusée : aucun acteur authentifié.",
            status_code=401,
        )
    if origine not in ORIGINES_TRANSITION:
        raise AppError(
            code="MODULE_TRANSITION_ORIGIN_INVALID",
            message=f"Origine de transition inconnue : {origine}.",
            status_code=422,
        )

    deja = await _ligne_par_cle(db, type_sujet, id_sujet, cle_idempotence)
    if deja is not None:
        return deja

    etat_actuel, version_actuelle = await etat_courant(db, type_sujet, id_sujet)
    if version_attendue != version_actuelle:
        raise AppError(
            code="MODULE_STATE_VERSION_CONFLICT",
            message=f"Version d'état attendue {version_attendue}, courante {version_actuelle}.",
            status_code=409,
        )
    if not transition_autorisee(type_sujet, etat_actuel, vers_etat):
        raise AppError(
            code="MODULE_TRANSITION_NOT_ALLOWED",
            message=f"Transition non autorisée : {etat_actuel} -> {vers_etat}.",
            status_code=409,
        )

    ligne = ModuleStateTransition(
        subjectType=type_sujet,
        subjectId=id_sujet,
        fromState=etat_actuel,
        toState=vers_etat,
        actorId=acteur_id,
        organizationId=organisation_id,
        origin=origine,
        reason=motif,
        operationId=operation_id or uuid.uuid4(),
        idempotencyKey=cle_idempotence,
        stateVersionBefore=version_actuelle,
        stateVersionAfter=version_actuelle + 1,
    )
    try:
        # Savepoint : une violation d'unicité annule cette insertion seule, pas la transaction de l'appelant.
        async with db.begin_nested():
            db.add(ligne)
            await db.flush()
    except IntegrityError:
        # Course perdue : une autre commande a pris la version, ou a déjà journalisé cette clé.
        rejeu = await _ligne_par_cle(db, type_sujet, id_sujet, cle_idempotence)
        if rejeu is not None:
            return rejeu
        raise AppError(
            code="MODULE_STATE_VERSION_CONFLICT",
            message="Version d'état modifiée par une autre commande concurrente.",
            status_code=409,
        )
    await publier_evenement_transition(db, ligne, module_id=module_id)
    return ligne
