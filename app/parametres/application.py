"""Application, rétablissement du défaut et restauration d'une valeur de paramètre (BE-157).

Trois opérations publiques, toutes écrivent une NOUVELLE version et ne réécrivent jamais une
version existante (BE-154) :

- `appliquer_valeur` : écrit `value` comme version appliquée ;
- `restaurer_version` : recopie la valeur d'une version antérieure dans une nouvelle version ;
- `retablir_defaut` : écrit `setting_definition.defaultValue` comme nouvelle version.

Règle d'application : une seule version est appliquée par (clé, portée, scopeId). À chaque
écriture, la version appliquée précédente passe à `applied = false`. Seul ce drapeau change
sur elle ; sa valeur et son numéro ne bougent pas.

Garanties (définition BE-157) :
- CA-1 : la nouvelle version, le changement de drapeau et l'entrée d'audit `EVT-SET-01` sont
  écrits dans un même savepoint (`executer_mutation_sensible`, BE-153). L'appelant fait le
  `commit()`.
- CA-2 : si l'audit échoue, le savepoint est annulé : ni nouvelle version, ni drapeau modifié ;
  la version précédente reste appliquée. `AUDIT_WRITE_FAILED` (500) est renvoyé.
- CA-3 : la restauration suit exactement la même écriture que l'application.
- CA-4 : sans permission `PARAMETRE_APPLIQUER` sur l'organisation, `PERMISSION_DENIED` (403).
  La vérification a lieu dans le savepoint, avant toute écriture.
- CA-5 : l'organisation visée doit être celle de l'identité (`TENANT_MISMATCH`, 404, contrôlé
  par `executer_mutation_sensible` avant tout accès). Toutes les lectures et écritures filtrent
  sur `scopeId`.

Verrou : la ligne `setting_definition` est verrouillée (`FOR UPDATE`) pendant le calcul de la
version suivante, ce qui sérialise les écritures concurrentes sur une même clé. La contrainte
d'unicité `(definitionKey, scopeKind, scopeId, version)` reste l'arbitre final.

Diff expurgé : pour un paramètre `sensitive`, les valeurs avant et après sont remplacées par
`[masqué]` dans l'audit ; sinon elles sont journalisées. `record_audit_event` masque en plus les
clés aux noms sensibles (mot de passe, jeton, etc.).

Hypothèses (points NON DÉFINI, à confirmer en QE) :
- QE-PAR-03 : la permission `parametres.setting.apply` sert de critère d'administration du scope ;
- une version source inconnue lève `SCHEMA_INVALID` (422), faute de code « introuvable » dans le
  catalogue BE-151 ;
- une raison vide lève `SCHEMA_INVALID` (422), avant toute écriture.

Documentation de module : app/parametres/application.md.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice, executer_mutation_sensible
from app.audit.service import REDACTION
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.parametres.models import SettingDefinition, SettingValue
from app.parametres.permissions import PARAMETRE_APPLIQUER, PARAMETRE_APPROUVER
from app.rbac.service import user_has_permission

# Événement de domaine journalisé à chaque nouvelle version (catalogue des événements).
EVENEMENT_CHANGEMENT = "EVT-SET-01"
# Action d'audit commune aux trois opérations ; le détail `operation` les distingue.
ACTION_AUDIT = "parametre.valeur.appliquer"
ENTITE_AUDIT = "setting_value"


@dataclass(frozen=True)
class _Ecriture:
    """Résultat interne d'une écriture, transmis à la construction du détail d'audit."""

    ligne: SettingValue
    valeur_precedente: object
    definition: SettingDefinition


ValeurDe = Callable[[AsyncSession, SettingDefinition], Awaitable[object]]


async def _ecrire_nouvelle_version(
    db: AsyncSession,
    identite: IdentiteEmettrice,
    organisation_id: uuid.UUID,
    definition_key: str,
    scope_kind: str,
    scope_id: uuid.UUID,
    reason: str,
    valeur_de: ValeurDe,
    identifiant: uuid.UUID,
    permission: str = PARAMETRE_APPLIQUER,
) -> _Ecriture:
    """Crée la version suivante et désactive l'appliquée précédente, dans le savepoint de l'appelant.

    Ordre : permission (403), verrou de la définition (422 si absente), valeur à écrire
    (`valeur_de`), numéro de version suivant, désactivation de l'appliquée, insertion.
    Toute exception annule la mutation : aucune ligne ne reste.
    """
    if not await user_has_permission(db, identite.user_id, organisation_id, permission):
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED)

    definition = await db.get(SettingDefinition, definition_key, with_for_update=True)
    if definition is None:
        raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="clé de paramètre non déclarée")

    valeur = await valeur_de(db, definition)

    filtre = (
        SettingValue.definitionKey == definition_key,
        SettingValue.scopeKind == scope_kind,
        SettingValue.scopeId == scope_id,
    )
    precedente = (
        await db.execute(select(SettingValue).where(*filtre, SettingValue.applied.is_(True)))
    ).scalar_one_or_none()
    derniere = (await db.execute(select(func.max(SettingValue.version)).where(*filtre))).scalar_one()

    await db.execute(
        update(SettingValue)
        .where(*filtre, SettingValue.applied.is_(True))
        .values(applied=False)
        .execution_options(synchronize_session=False)
    )
    ligne = SettingValue(
        id=identifiant,
        definitionKey=definition_key,
        scopeKind=scope_kind,
        scopeId=scope_id,
        version=(derniere or 0) + 1,
        value=valeur,
        applied=True,
        createdBy=identite.user_id,
        reason=reason,
    )
    db.add(ligne)
    await db.flush()
    return _Ecriture(ligne=ligne, valeur_precedente=precedente.value if precedente is not None else None, definition=definition)


def _detail_audit(ecriture: _Ecriture, definition_key: str, scope_kind: str, scope_id: uuid.UUID, operation: str) -> dict:
    """Détail `EVT-SET-01` : clé, version, portée, clés modifiées, diff expurgé.

    Pour un paramètre sensible, le diff ne contient aucune valeur, ni avant ni après.
    """
    if ecriture.definition.sensitive:
        diff = {"avant": REDACTION, "apres": REDACTION}
    else:
        diff = {"avant": ecriture.valeur_precedente, "apres": ecriture.ligne.value}
    return {
        "evenement": EVENEMENT_CHANGEMENT,
        "cle": definition_key,
        "version": ecriture.ligne.version,
        "portee": scope_kind,
        "scopeId": str(scope_id),
        "operation": operation,
        "clesModifiees": [definition_key],
        "diff": diff,
    }


async def _appliquer(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    organisation_id: uuid.UUID,
    *,
    definition_key: str,
    scope_kind: str,
    scope_id: uuid.UUID,
    reason: str,
    operation: str,
    valeur_de: ValeurDe,
    permission: str = PARAMETRE_APPLIQUER,
) -> SettingValue:
    """Enveloppe commune : raison, puis mutation et audit `EVT-SET-01` dans un même savepoint.

    L'identifiant de la nouvelle ligne est fixé avant l'écriture pour servir d'`entity_id` à
    l'audit (la ligne ne peut pas être créée deux fois).
    """
    if not reason or not reason.strip():
        raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="raison de changement vide")
    identifiant = uuid.uuid4()

    async def mutation(session: AsyncSession) -> _Ecriture:
        return await _ecrire_nouvelle_version(
            session, identite, organisation_id, definition_key, scope_kind, scope_id, reason, valeur_de, identifiant,
            permission,
        )

    ecriture = await executer_mutation_sensible(
        db,
        identite,
        organisation_id,
        ACTION_AUDIT,
        ENTITE_AUDIT,
        identifiant,
        f"{operation} du paramètre {definition_key}",
        mutation,
        changes=lambda resultat: _detail_audit(resultat, definition_key, scope_kind, scope_id, operation),
        motif=reason,
    )
    return ecriture.ligne


async def appliquer_valeur(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    organisation_id: uuid.UUID,
    *,
    definition_key: str,
    scope_kind: str,
    scope_id: uuid.UUID,
    value: object,
    reason: str,
) -> SettingValue:
    """Écrit `value` comme nouvelle version appliquée pour (clé, portée, scopeId).

    Retourne la ligne créée. L'appelant doit faire `commit()` : rien n'est persisté avant.
    Erreurs : `TENANT_MISMATCH` (404), `PERMISSION_DENIED` (403), `SCHEMA_INVALID` (422),
    `AUDIT_WRITE_FAILED` (500). Dans tous les cas, aucune version n'est écrite.
    """

    async def valeur_de(_session: AsyncSession, _definition: SettingDefinition) -> object:
        return value

    return await _appliquer(
        db, identite, organisation_id,
        definition_key=definition_key, scope_kind=scope_kind, scope_id=scope_id,
        reason=reason, operation="application", valeur_de=valeur_de,
    )


async def restaurer_version(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    organisation_id: uuid.UUID,
    *,
    definition_key: str,
    scope_kind: str,
    scope_id: uuid.UUID,
    version: int,
    reason: str,
) -> SettingValue:
    """Restaure la valeur de `version` en créant une nouvelle version appliquée (CA-3).

    La version source doit exister pour la même (clé, portée, scopeId) ; sinon
    `SCHEMA_INVALID` (422) et rien n'est écrit. La version source n'est jamais modifiée.
    Erreurs communes à `appliquer_valeur`.
    """

    async def valeur_de(session: AsyncSession, _definition: SettingDefinition) -> object:
        source = (
            await session.execute(
                select(SettingValue).where(
                    SettingValue.definitionKey == definition_key,
                    SettingValue.scopeKind == scope_kind,
                    SettingValue.scopeId == scope_id,
                    SettingValue.version == version,
                )
            )
        ).scalar_one_or_none()
        if source is None:
            raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail=f"version source {version} inconnue")
        return source.value

    return await _appliquer(
        db, identite, organisation_id,
        definition_key=definition_key, scope_kind=scope_kind, scope_id=scope_id,
        reason=reason, operation="restauration", valeur_de=valeur_de,
    )


async def retablir_defaut(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    organisation_id: uuid.UUID,
    *,
    definition_key: str,
    scope_kind: str,
    scope_id: uuid.UUID,
    reason: str,
) -> SettingValue:
    """Écrit `defaultValue` de la définition comme nouvelle version appliquée.

    L'ancienne valeur reste dans l'historique ; le défaut n'est jamais « effacé ».
    Erreurs communes à `appliquer_valeur`.
    """

    async def valeur_de(_session: AsyncSession, definition: SettingDefinition) -> object:
        return definition.defaultValue

    return await _appliquer(
        db, identite, organisation_id,
        definition_key=definition_key, scope_kind=scope_kind, scope_id=scope_id,
        reason=reason, operation="defaut", valeur_de=valeur_de,
    )


async def appliquer_valeur_approuvee(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    organisation_id: uuid.UUID,
    *,
    definition_key: str,
    scope_kind: str,
    scope_id: uuid.UUID,
    value: object,
    reason: str,
) -> SettingValue:
    """Écrit `value` comme nouvelle version appliquée, à la suite d'une approbation (BE-159, CA-2).

    Même écriture et même audit `EVT-SET-01` que `appliquer_valeur`, mais la permission exigée
    est `settings.approve` (`PARAMETRE_APPROUVER`) et non `parametres.setting.apply` : l'approbateur
    n'a pas à détenir le droit de proposer une valeur. Réservé à `app.parametres.approbation`,
    qui vérifie avant l'appel que l'approbateur n'est pas le demandeur et que la demande est en attente.
    Erreurs : `PERMISSION_DENIED` (403), `SCHEMA_INVALID` (422), `AUDIT_WRITE_FAILED` (500).
    """

    async def valeur_de(_session: AsyncSession, _definition: SettingDefinition) -> object:
        return value

    return await _appliquer(
        db, identite, organisation_id,
        definition_key=definition_key, scope_kind=scope_kind, scope_id=scope_id,
        reason=reason, operation="approbation", valeur_de=valeur_de, permission=PARAMETRE_APPROUVER,
    )
