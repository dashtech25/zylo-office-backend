"""Routes API des paramètres (BE-158), sous `/api/v1/parametres`.

Routes :
- `GET /api/v1/parametres/{scope_kind}/{scope_id}` : liste les paramètres résolus du scope.
  Chaque élément porte `cle`, `valeur`, `source` (niveau gagnant) et `version`. Permission
  `settings.read` (PARAMETRE_LIRE). Un paramètre `sensitive` est renvoyé avec `[masqué]`.
- `PUT /api/v1/parametres/{scope_kind}/{scope_id}/{cle}` : écrit une nouvelle valeur appliquée.
  Corps : `value` et `reason` (obligatoire, 422 sinon). En-tête optionnel `X-Expected-Version` :
  si présent et différent de la version appliquée courante, 409 VERSION_CONFLICT sans écriture.
  Permission `parametres.setting.apply` (vérifiée par `appliquer_valeur`, BE-157). 200 avec la
  nouvelle version.
- `POST /api/v1/parametres/{scope_kind}/{scope_id}/{cle}/restaurations` : crée une nouvelle
  version recopiant la valeur d'une version antérieure (`version`, `reason`). Mêmes règles
  d'en-tête de version attendue et de permission que le PUT. 200 avec la nouvelle version.

Contrat de scope :
- seule la portée `organisation` est servie ici ; toute autre portée renvoie 422 SCHEMA_INVALID ;
- le tenant vient de l'en-tête `X-Organization-Id` (contexte serveur, `get_tenant_context`). Un
  `scope_id` différent du tenant courant renvoie 404 `organization_not_found`, réponse identique
  à celle d'un identifiant inexistant : l'existence du scope n'est pas révélée (CA-5).

Ordre des contrôles : tenant et scope (404), puis lecture ou version attendue, puis permission
(403, dans le savepoint de `appliquer_valeur`), puis raison et valeur (422).

Limite connue : la vérification de version attendue précède l'écriture sans verrou propre ; la
concurrence est arbitrée par le verrou de `appliquer_valeur` (`FOR UPDATE` sur la définition), qui
n'évalue pas la version attendue. Une écriture simultanée peut donc passer entre les deux. Point
à trancher en QE-PAR-02.

Documentation de route : app/parametres/routes.md.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice
from app.audit.service import REDACTION
from app.core.database import get_db
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.core.errors import AppError
from app.core.tenant_context import TenantContext, get_tenant_context
from app.parametres.application import appliquer_valeur, restaurer_version
from app.parametres.models import SettingDefinition, SettingValue
from app.parametres.permissions import PARAMETRE_LIRE
from app.parametres.resolution import NIVEAU_DEFAUT, PLATEFORME_SCOPE_ID, resoudre_parametre
from app.parametres.service import lire_valeur_courante
from app.rbac.service import organisation_introuvable, user_has_permission

router = APIRouter()

PORTEE_ORGANISATION = "organisation"
# Identifiant neutre : aucun niveau utilisateur ni module n'est lu pour la liste d'un scope organisation.
IDENTIFIANT_NUL = uuid.UUID(int=0)
EN_TETE_VERSION_ATTENDUE = "X-Expected-Version"


class ModificationParametre(BaseModel):
    """Corps d'une écriture de valeur. `reason` est obligatoire et non vide (CA-2)."""

    value: Any
    reason: str = Field(min_length=1)


class RestaurationParametre(BaseModel):
    """Corps d'une restauration : version source à recopier et raison."""

    version: int
    reason: str = Field(min_length=1)


class ParametreResolu(BaseModel):
    """Paramètre résolu pour un scope : valeur retenue, niveau gagnant et version (CA-1)."""

    cle: str
    valeur: Any
    source: str | None
    version: int | None
    absent: bool


class VersionAppliquee(BaseModel):
    """Réponse d'une écriture : clé et nouvelle version appliquée. La valeur n'est pas renvoyée."""

    cle: str
    version: int


def _verifier_scope(contexte: TenantContext, scope_kind: str, scope_id: uuid.UUID) -> None:
    """Refuse une portée non servie (422) ou un scope hors du tenant courant (404, CA-5)."""
    if scope_kind != PORTEE_ORGANISATION:
        raise AppError("SCHEMA_INVALID", "Portée de paramètre non servie par cette route.", status_code=422)
    if scope_id != contexte.organization_id:
        raise organisation_introuvable()


async def _verifier_permission(db: AsyncSession, contexte: TenantContext, permission: str) -> None:
    """Refuse (403 PERMISSION_DENIED) sans la permission sur l'organisation du tenant."""
    if not await user_has_permission(db, contexte.user_id, contexte.organization_id, permission):
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED)


async def _verifier_version_attendue(db: AsyncSession, cle: str, organisation_id: uuid.UUID, attendue: int | None) -> None:
    """Compare la version attendue à la version appliquée courante (CA-3).

    Sans en-tête, aucune comparaison. Une version appliquée absente vaut 0. Un écart lève 409
    VERSION_CONFLICT avant toute écriture.
    """
    if attendue is None:
        return
    courante = (
        await db.execute(
            select(SettingValue.version).where(
                SettingValue.definitionKey == cle,
                SettingValue.scopeKind == PORTEE_ORGANISATION,
                SettingValue.scopeId == organisation_id,
                SettingValue.applied.is_(True),
            )
        )
    ).scalar_one_or_none()
    if (courante or 0) != attendue:
        raise AppError(
            "VERSION_CONFLICT",
            "La version attendue ne correspond plus à la version appliquée.",
            status_code=409,
        )


async def _version_retenue(db: AsyncSession, cle: str, organisation_id: uuid.UUID, niveau: str | None) -> int | None:
    """Version courante du niveau gagnant ; None pour le défaut déclaré ou une valeur absente."""
    if niveau is None or niveau == NIVEAU_DEFAUT:
        return None
    scope_id = organisation_id if niveau == PORTEE_ORGANISATION else PLATEFORME_SCOPE_ID
    ligne = await lire_valeur_courante(db, cle, niveau, scope_id)
    return ligne.version if ligne is not None else None


@router.get("/{scope_kind}/{scope_id}", response_model=list[ParametreResolu])
async def lister_parametres_resolus(
    scope_kind: str,
    scope_id: uuid.UUID,
    contexte: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[ParametreResolu]:
    """Liste les paramètres résolus d'un scope organisation, triés par clé.

    Résolution au niveau de l'organisation : organisation, puis plateforme, puis défaut déclaré
    (BE-156). Les niveaux utilisateur et module ne sont pas lus ici. Erreurs : 404 hors tenant,
    403 sans `settings.read`, 409 PARAMETRE_CONFLIT si deux niveaux sont de natures différentes.
    Un paramètre `sensitive` est renvoyé avec la valeur `[masqué]`.
    """
    _verifier_scope(contexte, scope_kind, scope_id)
    await _verifier_permission(db, contexte, PARAMETRE_LIRE)

    definitions = (
        await db.execute(
            select(SettingDefinition.key, SettingDefinition.sensitive)
            .where(SettingDefinition.scopeKind == PORTEE_ORGANISATION)
            .order_by(SettingDefinition.key)
        )
    ).all()

    resultats: list[ParametreResolu] = []
    for cle, sensible in definitions:
        resolu = await resoudre_parametre(
            db, cle, organisation_id=contexte.organization_id, utilisateur_id=IDENTIFIANT_NUL, module_id=IDENTIFIANT_NUL
        )
        version = await _version_retenue(db, cle, contexte.organization_id, resolu.niveau)
        valeur = REDACTION if sensible and not resolu.absent else resolu.valeur
        resultats.append(
            ParametreResolu(cle=cle, valeur=valeur, source=resolu.niveau, version=version, absent=resolu.absent)
        )
    return resultats


@router.put("/{scope_kind}/{scope_id}/{cle}", response_model=VersionAppliquee)
async def modifier_parametre(
    scope_kind: str,
    scope_id: uuid.UUID,
    cle: str,
    corps: ModificationParametre,
    contexte: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
    version_attendue: int | None = Header(default=None, alias=EN_TETE_VERSION_ATTENDUE),
) -> VersionAppliquee:
    """Écrit `value` comme nouvelle version appliquée du paramètre `cle` pour le scope.

    Délègue à `appliquer_valeur` (BE-157) : permission `parametres.setting.apply`, audit
    `EVT-SET-01` dans le même savepoint, une seule version appliquée à la fois. Le commit est
    fait ici. Erreurs : 404 hors tenant, 409 VERSION_CONFLICT si `X-Expected-Version` est
    périmé, 403 sans permission, 422 si la clé est inconnue ou si `reason` est vide.
    """
    _verifier_scope(contexte, scope_kind, scope_id)
    await _verifier_version_attendue(db, cle, contexte.organization_id, version_attendue)
    identite = IdentiteEmettrice(user_id=contexte.user_id, organization_id=contexte.organization_id)
    ligne = await appliquer_valeur(
        db,
        identite,
        contexte.organization_id,
        definition_key=cle,
        scope_kind=PORTEE_ORGANISATION,
        scope_id=contexte.organization_id,
        value=corps.value,
        reason=corps.reason,
    )
    await db.commit()
    return VersionAppliquee(cle=cle, version=ligne.version)


@router.post("/{scope_kind}/{scope_id}/{cle}/restaurations", response_model=VersionAppliquee)
async def restaurer_parametre(
    scope_kind: str,
    scope_id: uuid.UUID,
    cle: str,
    corps: RestaurationParametre,
    contexte: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
    version_attendue: int | None = Header(default=None, alias=EN_TETE_VERSION_ATTENDUE),
) -> VersionAppliquee:
    """Crée une nouvelle version appliquée recopiant la valeur de `corps.version` (BE-157, CA-3).

    Mêmes garanties et erreurs que le PUT. 422 si la version source est inconnue pour ce scope.
    La version source n'est jamais modifiée.
    """
    _verifier_scope(contexte, scope_kind, scope_id)
    await _verifier_version_attendue(db, cle, contexte.organization_id, version_attendue)
    identite = IdentiteEmettrice(user_id=contexte.user_id, organization_id=contexte.organization_id)
    ligne = await restaurer_version(
        db,
        identite,
        contexte.organization_id,
        definition_key=cle,
        scope_kind=PORTEE_ORGANISATION,
        scope_id=contexte.organization_id,
        version=corps.version,
        reason=corps.reason,
    )
    await db.commit()
    return VersionAppliquee(cle=cle, version=ligne.version)
