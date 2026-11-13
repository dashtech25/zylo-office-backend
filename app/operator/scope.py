"""Portée d'administration : plateforme ou tenant explicite (BE-120).

Intention : toute route d'administration dit explicitement sur quoi elle agit.
Deux portées seulement :

- `platform` : administration de la plateforme (liste des organisations, console
  opérateur). Elle ne donne jamais accès au contenu d'un tenant (CA-2).
- `tenant:<uuid>` : action sur un tenant précis. L'accès exige, en plus de
  l'autorité plateforme, une adhésion active au tenant désigné (CA-3). Un
  administrateur global sans affectation au tenant A ne voit rien du tenant A.

Format de l'en-tête `X-Admin-Scope` (absent : `platform`) :

- `platform` ;
- `tenant:<uuid>` où `<uuid>` est sous sa forme canonique (minuscules, tirets).
  Toute autre valeur (casse, préfixe inconnu, suffixe, espace) est rejetée en
  422 `admin_scope_invalid`. Le client ne choisit jamais le tenant au-delà de
  ce qu'il a le droit de voir : la portée n'est qu'un sélecteur.

Refus (réponses) :

- portée mal formée : 422 `admin_scope_invalid` ;
- sujet sans autorité plateforme, ou sans affectation au tenant demandé, ou
  portée plateforme sur contenu tenant : 403 `admin_scope_denied`. Le 403 est
  délibéré : à la différence du contrôle d'organisation (BE-009, 404 uniforme),
  un administrateur sait qu'il lui manque un droit, il ne doit pas croire que
  le tenant n'existe pas.

Source de l'autorité plateforme : une affectation active de rôle d'opérateur
plateforme en portée `platform` (BE-121, `app/rbac/role_assignments.py`). Elle
remplace la liste d'exploitation `OPERATOR_READ_USER_IDS`, qui ne sert plus à
la portée d'administration (elle reste celle de la console opérateur BE-030).

Aucune table : BE-120 ne crée ni colonne ni migration. Aucune route n'est
ajoutée ici ; les routes d'administration (BE-121 et suivants) dépendent de
`require_admin_scope`.
"""

import uuid
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.operator.tenant_guard import journaliser_refus_cross_tenant
from app.rbac.guards import assert_active_membership
from app.rbac.role_assignments import has_platform_authority

EN_TETE_PORTEE = "X-Admin-Scope"
PORTEE_PLATEFORME = "platform"
PREFIXE_TENANT = "tenant:"


@dataclass(frozen=True)
class AdminScope:
    """Portée d'une requête d'administration.

    `organization_id` vaut `None` pour la portée plateforme, et l'identifiant du
    tenant pour la portée tenant. Deux portées sont égales si elles désignent la
    même cible : la plateforme n'est égale qu'à elle-même.
    """

    organization_id: uuid.UUID | None

    @property
    def is_platform(self) -> bool:
        """Vrai pour la portée plateforme, faux pour un tenant explicite."""
        return self.organization_id is None


PLATEFORME = AdminScope(organization_id=None)


def _portee_invalide() -> AppError:
    return AppError(
        code="admin_scope_invalid",
        message="Portée d'administration invalide.",
        status_code=422,
        field_errors={"X-Admin-Scope": ["valeur attendue : platform ou tenant:<uuid canonique>"]},
    )


def parse_admin_scope(brut: str) -> AdminScope:
    """Lit une valeur d'en-tête et renvoie la portée correspondante.

    Refuse en 422 tout ce qui n'est pas exactement `platform` ou
    `tenant:<uuid canonique>`. La comparaison à la forme canonique est
    volontaire : deux écritures du même UUID (casse, accolades) ne doivent pas
    produire deux portées distinctes dans les journaux.
    """
    if brut == PORTEE_PLATEFORME:
        return PLATEFORME
    if not brut.startswith(PREFIXE_TENANT):
        raise _portee_invalide()
    valeur = brut[len(PREFIXE_TENANT):]
    try:
        organisation = uuid.UUID(valeur)
    except ValueError:
        raise _portee_invalide() from None
    if str(organisation) != valeur:
        raise _portee_invalide()
    return AdminScope(organization_id=organisation)


def admin_scope_from_request(request: Request) -> AdminScope:
    """Portée demandée par la requête. En-tête absent : plateforme.

    Un en-tête présent mais vide est une valeur mal formée (422), pas une absence.
    """
    brut = request.headers.get(EN_TETE_PORTEE)
    if brut is None:
        return PLATEFORME
    return parse_admin_scope(brut)


def _refus() -> AppError:
    return AppError(
        code="admin_scope_denied",
        message="Accès d'administration refusé pour cette portée.",
        status_code=403,
    )


def assert_tenant_content_scope(scope: AdminScope, organization_id: uuid.UUID) -> None:
    """Lève 403 si la portée ne couvre pas le contenu de `organization_id`.

    La portée plateforme ne couvre jamais un contenu tenant (CA-2), même si
    l'utilisateur est autorisé au niveau plateforme. Une portée tenant ne couvre
    que son propre tenant.
    """
    if scope.is_platform or scope.organization_id != organization_id:
        raise _refus()


async def require_admin_scope(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminScope:
    """Dépendance FastAPI : valide la portée et l'autorité de l'appelant.

    Ordre de décision (deny-by-default) :
    1. portée mal formée : 422 ;
    2. sans autorité plateforme : 403 (CA-4), quelle que soit la portée ;
    3. portée tenant sans adhésion active à ce tenant : 403 (CA-3).

    Renvoie la portée validée ; la route vérifie ensuite la cible avec
    `assert_tenant_content_scope` pour chaque ressource tenant lue ou écrite.
    """
    scope = admin_scope_from_request(request)
    if not await has_platform_authority(db, current_user.id):
        raise _refus()
    if not scope.is_platform:
        try:
            await assert_active_membership(db, current_user.id, scope.organization_id)
        except AppError:
            # Le 404 uniforme de BE-009 est remplacé par un 403 : le refus est un
            # défaut de droit d'administration, pas une organisation inexistante.
            # BE-147 CA-4 : ce refus est un refus cross-tenant, il est journalisé.
            await journaliser_refus_cross_tenant(
                db,
                acteur_id=current_user.id,
                organization_id=scope.organization_id,
                portee=f"tenant:{scope.organization_id}",
            )
            raise _refus() from None
    return scope
