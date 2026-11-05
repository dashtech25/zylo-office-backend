"""Approbation des changements de paramètres sensibles (BE-159).

Un changement de paramètre marqué `sensitive` ne s'applique pas directement : il crée une demande
d'approbation en attente (`approbation_parametre`) et la valeur active ne bouge pas. Un autre
utilisateur, détenant `settings.approve`, tranche la demande.

Cycle de vie de la demande :

    en_attente --approuver--> approuvé   (la valeur devient la version appliquée, EVT-SET-01 + EVT-SET-02)
    en_attente --rejeter----> rejeté     (aucune version écrite, EVT-SET-02)

Fonctions publiques :
- `demander_changement` : crée la demande en attente (CA-1). Le demandeur doit détenir
  `parametres.setting.apply`, la permission d'écriture de BE-157/BE-158.
- `decider_demande` : approuve ou rejette (CA-2, CA-3, CA-4). Toute la décision, applications de
  la valeur comprises, tient dans un seul savepoint avec l'entrée d'audit `EVT-SET-02`.
- `lire_demande` : lit une demande (statut, demandeur, approbateur, dates).

Règles (définition BE-159) :
- CA-1 : seul un paramètre `sensitive` passe par une demande. Un paramètre non sensible ou
  inconnu est refusé en 422 SCHEMA_INVALID, sans rien écrire ;
- CA-2 : une approbation écrit la valeur comme nouvelle version appliquée, et journalise
  `EVT-SET-02` avec la demande, l'approbateur et le motif de la décision ;
- CA-3 : une décision par le demandeur lui-même est refusée (403, auto-approbation interdite,
  règle recommandée en QE-PAR-06) ; une décision sans `settings.approve` est refusée (403) ;
- CA-4 : une décision sur une demande déjà tranchée renvoie 409 VERSION_CONFLICT et n'écrit rien ;
- CA-5 : une demande n'est visible et décidable que dans son tenant. Hors tenant, la réponse
  est 404 (`TENANT_MISMATCH`), identique à une demande inexistante : l'existence n'est pas révélée.

Verrou : la demande est lue avec `FOR UPDATE` avant toute vérification de statut ; deux décisions
concurrentes sont donc sérialisées, et la seconde voit le statut tranché et reçoit 409.

Hypothèses (NON DÉFINI, à confirmer en QE) :
- QE-PAR-02 : les routes et le corps de décision (`decision`, `motif`) ;
- QE-PAR-03 : la permission `settings.approve` ;
- QE-PAR-06 : interdiction de l'auto-approbation ;
- « sensible » lu comme l'attribut `SettingDefinition.sensitive` existant. Ce drapeau sert aussi au
  masquage des valeurs dans l'audit (BE-154) : la confusion entre confidentialité et approbation
  est à trancher ;
- le motif enregistré sur la demande est la raison de la demande (`motif`) ; le motif de la
  décision n'est journalisé que dans `EVT-SET-02`.

Documentation de module : app/parametres/approbation.md.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice, executer_mutation_sensible
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.parametres.application import appliquer_valeur_approuvee
from app.parametres.models import ApprobationParametre, SettingDefinition
from app.parametres.permissions import PARAMETRE_APPLIQUER, PARAMETRE_APPROUVER
from app.rbac.service import user_has_permission

STATUT_EN_ATTENTE = "en_attente"
STATUT_APPROUVE = "approuvé"
STATUT_REJETE = "rejeté"
# Décisions acceptées par l'API, et statut qu'elles produisent.
DECISIONS = {"approuver": STATUT_APPROUVE, "rejeter": STATUT_REJETE}
# Événement de domaine de la décision (catalogue des événements, EVT-SET-02).
EVENEMENT_DECISION = "EVT-SET-02"
ACTION_AUDIT_DECISION = "parametre.approbation.decider"
ENTITE_AUDIT = "approbation_parametre"


async def demander_changement(
    db: AsyncSession,
    identite: IdentiteEmettrice,
    organisation_id: uuid.UUID,
    *,
    definition_key: str,
    scope_kind: str,
    scope_id: uuid.UUID,
    value: object,
    reason: str,
) -> ApprobationParametre:
    """Crée une demande en attente pour un changement de paramètre sensible (CA-1).

    Ordre des contrôles : raison non vide (422), permission d'écriture du demandeur (403),
    paramètre déclaré et sensible (422). Aucune ligne de `setting_value` n'est écrite : la valeur
    active reste celle d'avant. L'appelant fait le `commit()`.
    """
    if not reason or not reason.strip():
        raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="raison de changement vide")
    if not await user_has_permission(db, identite.user_id, organisation_id, PARAMETRE_APPLIQUER):
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED)
    definition = await db.get(SettingDefinition, definition_key)
    if definition is None or not definition.sensitive:
        raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="paramètre non sensible ou non déclaré")

    demande = ApprobationParametre(
        id=uuid.uuid4(),
        settingKey=definition_key,
        scopeKind=scope_kind,
        scopeId=scope_id,
        valeurProposee=value,
        demandeur=identite.user_id,
        statut=STATUT_EN_ATTENTE,
        motif=reason,
    )
    db.add(demande)
    await db.flush()
    return demande


async def _demande_du_tenant(db: AsyncSession, organisation_id: uuid.UUID, demande_id: uuid.UUID, *, verrou: bool) -> ApprobationParametre:
    """Lit une demande filtrée sur le tenant ; absente ou hors tenant : 404 (CA-5).

    `verrou=True` pose un `FOR UPDATE` pour sérialiser les décisions concurrentes.
    """
    requete = select(ApprobationParametre).where(
        ApprobationParametre.id == demande_id,
        ApprobationParametre.scopeId == organisation_id,
    )
    if verrou:
        requete = requete.with_for_update()
    demande = (await db.execute(requete)).scalar_one_or_none()
    if demande is None:
        raise ErreurCatalogue(CodeErreur.TENANT_MISMATCH, detail="demande d'approbation absente du tenant")
    return demande


async def lire_demande(
    db: AsyncSession, identite: IdentiteEmettrice, organisation_id: uuid.UUID, demande_id: uuid.UUID
) -> ApprobationParametre:
    """Lit une demande. Autorisé au demandeur ou à un détenteur de `settings.approve`.

    Erreurs : 404 hors tenant (CA-5), 403 `PERMISSION_DENIED` pour un tiers sans `settings.approve`.
    """
    demande = await _demande_du_tenant(db, organisation_id, demande_id, verrou=False)
    if demande.demandeur != identite.user_id and not await user_has_permission(
        db, identite.user_id, organisation_id, PARAMETRE_APPROUVER
    ):
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED)
    return demande


async def decider_demande(
    db: AsyncSession,
    identite: IdentiteEmettrice,
    organisation_id: uuid.UUID,
    *,
    demande_id: uuid.UUID,
    decision: str,
    motif: str,
) -> ApprobationParametre:
    """Approuve ou rejette une demande en attente (CA-2, CA-3, CA-4, CA-5).

    Ordre des contrôles, avant toute écriture : décision connue et motif non vide (422), demande
    du tenant avec verrou (404), permission `settings.approve` (403), approbateur distinct du
    demandeur (403), statut encore `en_attente` (409 VERSION_CONFLICT).

    Pour `approuver`, la valeur proposée est écrite comme nouvelle version appliquée par
    `appliquer_valeur_approuvee` (EVT-SET-01), dans le même savepoint que l'entrée `EVT-SET-02`.
    Si l'audit échoue, la valeur n'est pas appliquée et la demande reste en attente.
    L'appelant fait le `commit()`.
    """
    if decision not in DECISIONS:
        raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="décision inconnue")
    if not motif or not motif.strip():
        raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="motif de décision vide")

    demande = await _demande_du_tenant(db, organisation_id, demande_id, verrou=True)
    if not await user_has_permission(db, identite.user_id, organisation_id, PARAMETRE_APPROUVER):
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED)
    if demande.demandeur == identite.user_id:
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail="auto-approbation refusée")
    if demande.statut != STATUT_EN_ATTENTE:
        raise ErreurCatalogue(CodeErreur.VERSION_CONFLICT, detail="demande déjà tranchée")

    cle, portee, portee_id, valeur, motif_demande = (
        demande.settingKey, demande.scopeKind, demande.scopeId, demande.valeurProposee, demande.motif
    )

    async def mutation(session: AsyncSession) -> ApprobationParametre:
        if decision == "approuver":
            await appliquer_valeur_approuvee(
                session,
                identite,
                organisation_id,
                definition_key=cle,
                scope_kind=portee,
                scope_id=portee_id,
                value=valeur,
                reason=motif_demande,
            )
        demande.statut = DECISIONS[decision]
        demande.approbateur = identite.user_id
        demande.decidedAt = datetime.now(timezone.utc)
        await session.flush()
        return demande

    def detail(resultat: ApprobationParametre) -> dict:
        # Le détail ne porte ni la valeur proposée ni la valeur appliquée : la cible est identifiée
        # par sa clé et sa portée, le contenu reste dans `approbation_parametre` et `setting_value`.
        return {
            "evenement": EVENEMENT_DECISION,
            "demande": str(resultat.id),
            "approbateur": str(identite.user_id),
            "decision": resultat.statut,
            "cle": cle,
            "portee": portee,
            "scopeId": str(portee_id),
            "motif": motif,
        }

    return await executer_mutation_sensible(
        db,
        identite,
        organisation_id,
        ACTION_AUDIT_DECISION,
        ENTITE_AUDIT,
        demande_id,
        f"décision « {decision} » sur la demande d'approbation du paramètre {cle}",
        mutation,
        changes=detail,
        motif=motif,
    )
