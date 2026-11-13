"""Enregistrement et publication des versions de module (BE-042).

Ce service porte les commandes d'écriture de la console plateforme du catalogue :

- `creer_module` : crée une fiche de module en `draft` (table `module`, réutilisée de BE-040) ;
- `creer_version` : crée une version en `draft` (table `module_version`) ;
- `publier_version` : fait passer une version `draft` -> `review` -> `published` ;
- `rejeter_version` : fait repasser une version `review` en `draft`, motif conservé.

Règles de publication, dans l'ordre :

1. version absente (ou rattachée à un autre module) -> `MODULE_VERSION_NOT_FOUND` (404) ;
2. version déjà `published` :
   - si la clé d'idempotence est déjà journalisée pour cette version, la publication est un rejeu :
     la version est renvoyée telle quelle (même résultat, aucun second effet) ;
   - sinon -> `MODULE_VERSION_ALREADY_PUBLISHED` (409) ;
3. `stateVersion` fourni différent du compteur courant -> `MODULE_STATE_VERSION_CONFLICT` (409) ;
4. version sans `digest` ou sans `provenance` -> `MODULE_VERSION_INCOMPLETE` (422), vérifié par
   `catalogue.verifier_publiable` avant toute écriture : la version reste dans son état ;
5. transitions journalisées : `draft -> review` (si besoin) puis `review -> published`. Chaque
   transition écrit une ligne de `module_state_transitions` (sujet `module_version`, origine
   `platform`, acteur obligatoire) et avance `stateVersion` de 1. La date `publishedAt` est renseignée
   par `catalogue.publier_version`.
6. événement `ModuleVersionPublished` émis dans les journaux, avec l'acteur et le `correlationId`
   de la requête. Le bus d'événements n'existe pas encore (BE-056) : le journal applicatif porte
   l'événement, et BE-056 le reprendra sans changer ce contrat.

Pourquoi deux lignes de journal pour une publication : chaque ligne est une transition de la
matrice d'états ; un audit doit voir l'état intermédiaire `review`. La clé d'idempotence de la
commande est portée par la ligne finale ; la ligne intermédiaire reçoit une clé dérivée, car la
contrainte d'unicité du journal interdit deux lignes de même clé pour un sujet.

Les fonctions ne font que `flush` : la route valide la transaction, comme dans `catalogue.py`.
Les contrôles de droit plateforme sont faits par la route avant d'appeler ce service
(`platform_rights.exiger_droit_plateforme`).
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules_registry import catalogue
from app.modules_registry.models import Module, ModuleStateTransition, ModuleVersion
from app.modules_registry.transitions import TYPE_SUJET_VERSION, transition_autorisee

logger = logging.getLogger("app.modules_registry.catalogue_publication")

ORIGINE_PLATEFORME = "platform"


async def creer_module(db: AsyncSession, *, code: str, name: str, description: str | None) -> Module:
    """Crée la fiche d'un module en `draft`, masquée (`visibility` = hidden).

    Lève `MODULE_CODE_EXISTS` (409) si `code` (clé stable du catalogue) existe déjà."""
    existant = (await db.execute(select(Module.id).where(Module.code == code))).scalar_one_or_none()
    if existant is not None:
        raise AppError(code="MODULE_CODE_EXISTS", message=f"Module déjà enregistré : {code}.", status_code=409)
    module = Module(code=code, name=name, description=description, publicationState="draft", visibility="hidden")
    db.add(module)
    await db.flush()
    return module


async def lire_module(db: AsyncSession, module_id: uuid.UUID) -> Module:
    """Renvoie la fiche du module, ou lève `MODULE_NOT_FOUND` (404)."""
    module = await db.get(Module, module_id)
    if module is None:
        raise AppError(code="MODULE_NOT_FOUND", message="Module introuvable.", status_code=404)
    return module


async def creer_version(
    db: AsyncSession,
    *,
    module_id: uuid.UUID,
    version: str,
    digest: str | None,
    provenance: str | None,
    licence: str | None,
    compatibility: dict | None,
    prerequisites: list | None,
) -> ModuleVersion:
    """Crée une version en `draft`, numéro `stateVersion` = 1.

    Lève `MODULE_NOT_FOUND` (404) si le module n'existe pas, et `MODULE_VERSION_EXISTS` (409) si
    `(moduleId, version)` est déjà pris (contrainte d'unicité de BE-040)."""
    await lire_module(db, module_id)
    existante = (
        await db.execute(
            select(ModuleVersion.id).where(ModuleVersion.moduleId == module_id, ModuleVersion.version == version)
        )
    ).scalar_one_or_none()
    if existante is not None:
        raise AppError(code="MODULE_VERSION_EXISTS", message=f"Version déjà enregistrée : {version}.", status_code=409)
    ligne = ModuleVersion(
        moduleId=module_id,
        version=version,
        digest=digest,
        provenance=provenance,
        licence=licence,
        compatibility=compatibility,
        prerequisites=prerequisites,
        stateVersion=1,
        publicationState="draft",
        publishedAt=None,
    )
    db.add(ligne)
    await db.flush()
    return ligne


async def lire_version(db: AsyncSession, module_id: uuid.UUID, version_id: uuid.UUID) -> ModuleVersion:
    """Renvoie la version `version_id` si elle appartient au module `module_id`, sinon 404."""
    ligne = (
        await db.execute(
            select(ModuleVersion).where(ModuleVersion.id == version_id, ModuleVersion.moduleId == module_id)
        )
    ).scalar_one_or_none()
    if ligne is None:
        raise AppError(code="MODULE_VERSION_NOT_FOUND", message="Version introuvable.", status_code=404)
    return ligne


async def _journaliser(
    db: AsyncSession,
    version: ModuleVersion,
    *,
    vers_etat: str,
    acteur_id: uuid.UUID,
    cle: str,
    motif: str | None = None,
) -> None:
    """Applique une transition de version : contrôle la table, écrit la ligne, avance le compteur.

    Lève `MODULE_TRANSITION_NOT_ALLOWED` (409) si la transition n'est pas dans
    `transitions.TRANSITIONS_AUTORISEES`. Aucune ligne n'est écrite dans ce cas."""
    de_etat = version.publicationState
    if not transition_autorisee(TYPE_SUJET_VERSION, de_etat, vers_etat):
        raise AppError(
            code="MODULE_TRANSITION_NOT_ALLOWED",
            message=f"Transition de version non autorisée : {de_etat} -> {vers_etat}.",
            status_code=409,
        )
    avant = version.stateVersion
    db.add(
        ModuleStateTransition(
            subjectType=TYPE_SUJET_VERSION,
            subjectId=version.id,
            fromState=de_etat,
            toState=vers_etat,
            actorId=acteur_id,
            organizationId=None,
            origin=ORIGINE_PLATEFORME,
            reason=motif,
            operationId=uuid.uuid4(),
            idempotencyKey=cle,
            stateVersionBefore=avant,
            stateVersionAfter=avant + 1,
        )
    )
    version.publicationState = vers_etat
    version.stateVersion = avant + 1
    await db.flush()


async def _cle_deja_journalisee(db: AsyncSession, version: ModuleVersion, cle: str) -> bool:
    """Vrai si une transition de cette version porte déjà la clé d'idempotence `cle`."""
    ligne = (
        await db.execute(
            select(ModuleStateTransition.id).where(
                ModuleStateTransition.subjectType == TYPE_SUJET_VERSION,
                ModuleStateTransition.subjectId == version.id,
                ModuleStateTransition.idempotencyKey == cle,
            )
        )
    ).scalar_one_or_none()
    return ligne is not None


async def publier_version(
    db: AsyncSession,
    version: ModuleVersion,
    *,
    acteur_id: uuid.UUID,
    state_version: int,
    cle: str | None,
    correlation_id: str | None,
) -> ModuleVersion:
    """Publie la version (voir la docstring du module pour l'ordre des contrôles).

    `cle` est la clé d'idempotence de la commande ; `None` est remplacée par une clé unique, donc
    sans rejeu possible. `correlation_id` est reporté dans l'événement `ModuleVersionPublished`."""
    cle = cle or str(uuid.uuid4())
    if version.publicationState == "published":
        if await _cle_deja_journalisee(db, version, cle):
            return version
        raise AppError(
            code="MODULE_VERSION_ALREADY_PUBLISHED",
            message="Version déjà publiée.",
            status_code=409,
        )
    if state_version != version.stateVersion:
        raise AppError(
            code="MODULE_STATE_VERSION_CONFLICT",
            message=f"Version d'état attendue {state_version}, courante {version.stateVersion}.",
            status_code=409,
        )
    catalogue.verifier_publiable(version)

    if version.publicationState == "draft":
        await _journaliser(db, version, vers_etat="review", acteur_id=acteur_id, cle=f"{cle}#review")
    await _journaliser(db, version, vers_etat="published", acteur_id=acteur_id, cle=cle)
    await catalogue.publier_version(db, version)

    logger.info(
        "ModuleVersionPublished",
        extra={"correlation_id": correlation_id, "actor_id": str(acteur_id), "version_id": str(version.id)},
    )
    return version


async def rejeter_version(
    db: AsyncSession, version: ModuleVersion, *, acteur_id: uuid.UUID, motif: str
) -> ModuleVersion:
    """Rejet d'une version en revue : `review -> draft`, avec le motif conservé dans le journal.

    Le motif est obligatoire (chaîne non vide) : un rejet sans explication n'est pas un audit.
    Lève `MODULE_TRANSITION_NOT_ALLOWED` (409) si la version n'est pas en `review`."""
    if not motif or not motif.strip():
        raise AppError(code="MODULE_REJECT_REASON_REQUIRED", message="Motif de rejet obligatoire.", status_code=422)
    await _journaliser(
        db, version, vers_etat="draft", acteur_id=acteur_id, cle=f"rejet:{uuid.uuid4()}", motif=motif.strip()
    )
    return version
