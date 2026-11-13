"""Registre des connecteurs et machine d'états (BE-160).

Rôle : tenir la liste des connecteurs d'un tenant ou de la plateforme, leur état et leur
version de configuration, et garantir trois règles :
- chaque changement d'état (création, activation, suspension, révocation) et chaque
  reprise de configuration écrit une entrée d'audit `EVT-INT-01` (CA-1) ;
- une transition absente de `TRANSITIONS_CONNECTEUR` est refusée en 409 sans rien écrire
  (CA-2) ;
- une reprise de configuration n'a lieu que si la configuration est validée (CA-3) ;
- un connecteur tenant n'est jamais visible ni modifiable depuis un autre tenant, et un
  connecteur global n'est modifiable que par l'administration plateforme (CA-4).

Ce module ne porte aucun droit propre (définition : « aucun droit propre (service) ») :
l'appelant, c'est-à-dire la route de BE-162, décide si l'identité est administratrice
plateforme et le transmet dans `est_admin_plateforme`. Le service applique seulement la
règle de portée. Les secrets ne passent jamais par ce registre.

Écriture d'audit : les mutations de tenant passent par `executer_mutation_sensible`
(BE-153), qui ouvre un savepoint commun à la mutation et à l'audit. Les connecteurs
globaux n'ont pas d'organisation : leur entrée est écrite avec `sans_organisation=True`
(portée plateforme, BE-121 CA-4), dans le même savepoint (`_mutation_globale`).

Transitions : la définition laisse les transitions à valider (QE-PAR-08). Recommandation
appliquée : `création` vers `activé` ou `révoqué` ; `activé` vers `suspendu` ou
`révoqué` ; `suspendu` vers `activé` ou `révoqué` ; `révoqué` est terminal.

Erreurs : le catalogue BE-151 ne contient pas de code pour une transition interdite ni
pour une configuration non validée. Ces deux erreurs sont des `AppError` locales en 409,
avec des codes propres au registre. Ajout au catalogue à trancher (QE-BE160-01).

Documentation de module : `app/integrations/registre.md`.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice, executer_mutation_sensible
from app.audit.service import record_audit_event
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.core.errors import AppError
from app.integrations.models import PORTEE_GLOBAL, PORTEE_TENANT, Connecteur

ETAT_CREATION = "création"
ETAT_ACTIVE = "activé"
ETAT_SUSPENDU = "suspendu"
ETAT_REVOQUE = "révoqué"

# Transitions autorisées. Une cible absente de l'ensemble associé est refusée (CA-2).
# `révoqué` n'a aucune sortie : une révocation est définitive.
TRANSITIONS_CONNECTEUR: dict[str, frozenset[str]] = {
    ETAT_CREATION: frozenset({ETAT_ACTIVE, ETAT_REVOQUE}),
    ETAT_ACTIVE: frozenset({ETAT_SUSPENDU, ETAT_REVOQUE}),
    ETAT_SUSPENDU: frozenset({ETAT_ACTIVE, ETAT_REVOQUE}),
    ETAT_REVOQUE: frozenset(),
}

# Action d'audit par événement. Le libellé `EVT-INT-01` est porté par `changes.evenement`.
ACTION_PAR_ETAT: dict[str, str] = {
    ETAT_CREATION: "connecteur.creation",
    ETAT_ACTIVE: "connecteur.activation",
    ETAT_SUSPENDU: "connecteur.suspension",
    ETAT_REVOQUE: "connecteur.revocation",
}
ACTION_REPRISE = "connecteur.reprise_configuration"
EVENEMENT = "EVT-INT-01"
TYPE_ENTITE = "Connecteur"


class TransitionConnecteurInterdite(AppError):
    """Transition d'état absente de `TRANSITIONS_CONNECTEUR` (CA-2). HTTP 409, rien n'est écrit."""

    def __init__(self, etat_depart: str, cible: str) -> None:
        super().__init__(
            code="CONNECTEUR_TRANSITION_INTERDITE",
            message="Transition d'état de connecteur interdite.",
            status_code=409,
        )
        self.etat_depart = etat_depart
        self.cible = cible


class ConfigurationConnecteurNonValidee(AppError):
    """Reprise de configuration refusée car la version n'est pas validée (CA-3). HTTP 409."""

    def __init__(self) -> None:
        super().__init__(
            code="CONNECTEUR_CONFIGURATION_NON_VALIDEE",
            message="Reprise refusée : la configuration n'est pas validée.",
            status_code=409,
        )


def _erreur_introuvable() -> AppError:
    return AppError(code="connecteur_introuvable", message="Connecteur introuvable.", status_code=404)


def verifier_portee(
    identite: IdentiteEmettrice | None,
    portee: str,
    organization_id: uuid.UUID | None,
    est_admin_plateforme: bool,
) -> None:
    """Contrôle d'accès commun aux écritures (CA-4).

    - identité absente : refus `PERMISSION_DENIED` 403 ;
    - connecteur global : seule l'administration plateforme peut écrire (sinon 403 `PERMISSION_DENIED`) ;
    - connecteur tenant : l'identité doit appartenir au tenant du connecteur (sinon `TENANT_MISMATCH`).

    Appelée avant toute lecture modifiante ou écriture, donc un refus n'a aucun effet de bord.
    """
    if identite is None:
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail="écriture de connecteur sans identité")
    if portee == PORTEE_GLOBAL:
        if not est_admin_plateforme:
            raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail="connecteur global : administration plateforme requise")
        return
    if identite.organization_id != organization_id:
        raise ErreurCatalogue(CodeErreur.TENANT_MISMATCH, detail="connecteur d'un autre tenant")


async def _mutation_globale(
    db: AsyncSession,
    identite: IdentiteEmettrice,
    action: str,
    entity_id: uuid.UUID,
    resume: str,
    mutation,
    changes: dict,
):
    """Mutation d'un connecteur global et son audit, dans un savepoint (portée plateforme).

    Même garantie que `executer_mutation_sensible` (BE-153) : si l'audit échoue, la mutation
    est annulée et `AUDIT_WRITE_FAILED` est levé. Les connecteurs globaux n'ont pas
    d'organisation, d'où l'écriture directe avec `sans_organisation=True`.
    """
    async with db.begin_nested():
        resultat = await mutation(db)
        try:
            await record_audit_event(
                db,
                None,
                identite.user_id,
                action,
                TYPE_ENTITE,
                entity_id,
                resume,
                changes,
                sans_organisation=True,
            )
        except Exception as exc:
            raise ErreurCatalogue(CodeErreur.AUDIT_WRITE_FAILED, detail=f"{type(exc).__name__}: {exc}") from exc
    return resultat


async def ecrire_mutation_connecteur(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    connecteur: Connecteur,
    action: str,
    resume: str,
    mutation,
    changes: dict,
):
    """Route la mutation vers l'écriture tenant (BE-153) ou globale selon la portée."""
    changes = {"evenement": EVENEMENT, **changes}
    if connecteur.portee == PORTEE_GLOBAL:
        return await _mutation_globale(db, identite, action, connecteur.id, resume, mutation, changes)
    return await executer_mutation_sensible(
        db, identite, connecteur.organizationId, action, TYPE_ENTITE, connecteur.id, resume, mutation, changes
    )


async def charger_connecteur(db: AsyncSession, connecteur_id: uuid.UUID) -> Connecteur:
    connecteur = await db.get(Connecteur, connecteur_id)
    if connecteur is None:
        raise _erreur_introuvable()
    return connecteur


async def creer_connecteur(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    *,
    portee: str,
    nom: str,
    organization_id: uuid.UUID | None,
    est_admin_plateforme: bool = False,
    version_configuration: int = 1,
) -> Connecteur:
    """Crée un connecteur à l'état `création` et écrit son audit `EVT-INT-01` (CA-1).

    Paramètres :
    - `portee` : `tenant` (avec `organization_id`) ou `global` (`organization_id` = None,
      administration plateforme requise) ;
    - `nom` : libellé affiché, non vide ;
    - `version_configuration` : version initiale, au moins 1.

    Un `portee` inconnu lève `ValueError` avant toute écriture. Le connecteur est
    rattaché à `organization_id` et l'identité doit appartenir à ce tenant.

    Retour : le connecteur ajouté à la session. L'appelant doit `commit()`.
    """
    if portee not in (PORTEE_TENANT, PORTEE_GLOBAL):
        raise ValueError(f"portée de connecteur inconnue : {portee!r}")
    if portee == PORTEE_TENANT and organization_id is None:
        raise ValueError("un connecteur tenant exige une organisation")
    if portee == PORTEE_GLOBAL:
        organization_id = None
    verifier_portee(identite, portee, organization_id, est_admin_plateforme)

    connecteur_id = uuid.uuid4()
    connecteur = Connecteur(
        id=connecteur_id,
        portee=portee,
        organizationId=organization_id,
        nom=nom,
        etat=ETAT_CREATION,
        versionConfiguration=version_configuration,
    )

    async def mutation(session: AsyncSession) -> Connecteur:
        session.add(connecteur)
        await session.flush()
        return connecteur

    changes = {"etat_apres": ETAT_CREATION, "portee": portee, "versionConfiguration": version_configuration}
    return await ecrire_mutation_connecteur(
        db, identite, connecteur, ACTION_PAR_ETAT[ETAT_CREATION], f"Création du connecteur {nom}", mutation, changes
    )


async def changer_etat(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    connecteur_id: uuid.UUID,
    cible: str,
    *,
    est_admin_plateforme: bool = False,
) -> Connecteur:
    """Applique une transition d'état autorisée et écrit son audit `EVT-INT-01` (CA-1).

    Ordre de contrôle, sans écriture avant la fin :
    1. connecteur introuvable : 404 ;
    2. droits de portée (`verifier_portee`) : 403 ou `TENANT_MISMATCH` ;
    3. transition absente de `TRANSITIONS_CONNECTEUR` : `TransitionConnecteurInterdite` (409, CA-2).

    Une cible identique à l'état courant n'est pas une transition : elle est refusée.
    Retour : le connecteur mis à jour. L'appelant doit `commit()`.
    """
    connecteur = await charger_connecteur(db, connecteur_id)
    verifier_portee(identite, connecteur.portee, connecteur.organizationId, est_admin_plateforme)

    etat_depart = connecteur.etat
    if cible not in TRANSITIONS_CONNECTEUR.get(etat_depart, frozenset()):
        raise TransitionConnecteurInterdite(etat_depart, cible)

    async def mutation(session: AsyncSession) -> Connecteur:
        connecteur.etat = cible
        await session.flush()
        return connecteur

    changes = {"etat_avant": etat_depart, "etat_apres": cible, "portee": connecteur.portee}
    return await ecrire_mutation_connecteur(
        db,
        identite,
        connecteur,
        ACTION_PAR_ETAT[cible],
        f"Connecteur {connecteur.nom} : {etat_depart} vers {cible}",
        mutation,
        changes,
    )


async def reprendre_configuration(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    connecteur_id: uuid.UUID,
    version: int,
    *,
    validee: bool,
    est_admin_plateforme: bool = False,
) -> Connecteur:
    """Reprend une version de configuration, seulement si elle est validée (CA-3).

    `validee` est fourni par le service de validation des paramètres (BE-155) : le registre
    ne valide rien lui-même. Si `validee` est faux, `ConfigurationConnecteurNonValidee`
    (409) est levée avant toute écriture. Un connecteur `révoqué` ne reprend plus rien
    (`TransitionConnecteurInterdite`, états terminaux).

    `version` doit être au moins 1. Retour : le connecteur ; l'audit porte l'ancienne et la
    nouvelle version. L'appelant doit `commit()`.
    """
    if version < 1:
        raise ValueError("version de configuration invalide")
    connecteur = await charger_connecteur(db, connecteur_id)
    verifier_portee(identite, connecteur.portee, connecteur.organizationId, est_admin_plateforme)
    if connecteur.etat == ETAT_REVOQUE:
        raise TransitionConnecteurInterdite(connecteur.etat, "reprise_configuration")
    if not validee:
        raise ConfigurationConnecteurNonValidee()

    version_avant = connecteur.versionConfiguration

    async def mutation(session: AsyncSession) -> Connecteur:
        connecteur.versionConfiguration = version
        await session.flush()
        return connecteur

    changes = {"versionConfiguration_avant": version_avant, "versionConfiguration_apres": version, "portee": connecteur.portee}
    return await ecrire_mutation_connecteur(
        db, identite, connecteur, ACTION_REPRISE, f"Reprise de configuration du connecteur {connecteur.nom}", mutation, changes
    )


async def lister_connecteurs(db: AsyncSession, organization_id: uuid.UUID) -> Sequence[Connecteur]:
    """Liste les connecteurs visibles par un tenant : les siens et les globaux (CA-4).

    Un connecteur d'un autre tenant n'est jamais renvoyé. Les connecteurs globaux le sont
    pour tous les tenants, car ils sont en lecture publique du catalogue ; leur modification
    reste réservée à la plateforme (`verifier_portee`).
    """
    resultat = await db.execute(
        select(Connecteur)
        .where(or_(Connecteur.organizationId == organization_id, Connecteur.portee == PORTEE_GLOBAL))
        .order_by(Connecteur.createdAt, Connecteur.id)
    )
    return list(resultat.scalars().all())
