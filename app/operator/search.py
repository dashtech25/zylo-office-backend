"""Recherche d'organisation pour la console de support (BE-129, lecture seule).

Intention : un agent de support retrouve une organisation cliente par son nom,
son identifiant de tenant (slug) ou son identifiant. Aucune table propre : la
lecture porte sur `organization` (BE-100).

Règles (définition BE-129) :
- CA-1 : chaque recherche est écrite dans `audit_event` (action
  `admin.search.query`) avec une empreinte SHA-256 du terme normalisé
  (`changes.termeEmpreinte`). Le terme n'est jamais écrit en clair, ni dans le
  résumé, ni dans les changements, ni dans l'action.
- CA-2 : la route est gardée par `require_admin_scope` (BE-120). Un sujet sans
  autorité plateforme reçoit 403, avant toute lecture.
- CA-3 : la portée est un sélecteur. En portée `platform`, la recherche porte sur
  toutes les organisations (autorité plateforme). En portée `tenant:<uuid>`, elle
  ne porte que sur ce tenant ; une portée sur un tenant sans affectation est
  refusée en 403 par `require_admin_scope` avant la recherche.
- CA-4 : en portée tenant, la réponse ne contient que les champs normalisés
  (`CHAMPS_NORMALISES`). La portée plateforme reçoit aussi les dates de création
  et de mise à jour (`CHAMPS_COMPLETS`).

Écarts consignés (recommandation appliquée, pas de QE tranchée) :
- Type : seul `organization` est accepté (`type` absent : `organization`). Un
  autre type est refusé en 422 par la route. « client » et « organisation »
  désignent la même entité (organisation cliente = tenant racine).
- Projection : la spécification prévoit une « vue limitée » pour l'agent L1. La
  garde BE-120 n'accorde l'accès qu'à l'autorité plateforme (rôle
  `operateur_plateforme`), donc aucun agent L1 ne peut passer la garde seul. La
  projection suit la portée à la place : tenant = normalisée, plateforme =
  complète. À reprendre si un rôle L1 reçoit un jour l'autorité plateforme.
- Permission `admin.search.read` : non déclarée. Le contrôle est la garde de
  portée de BE-120, comme sur les autres routes `/api/v1/admin`.
- Empreinte : SHA-256 nu, sans clé. Un terme très court ou très courant reste
  retrouvable par essais ; le terme minimal de 2 caractères limite le risque.
- Résultats : au plus `LIMITE_RESULTATS` (50), tri par nom. Pas de pagination
  (taille de page NON DÉFINIE dans la spécification).

Route : `GET /api/v1/admin/search`, dans `app/operator/search_router.py`.
"""

import hashlib
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.identity.models import Organization
from app.operator.scope import AdminScope

TYPE_RECHERCHE = "organization"
ACTION_RECHERCHE = "admin.search.query"
LIMITE_RESULTATS = 50
TERME_MIN = 2
TERME_MAX = 100
CHAMPS_NORMALISES = ("id", "name", "slug", "status")
CHAMPS_COMPLETS = CHAMPS_NORMALISES + ("createdAt", "updatedAt")


def normaliser_terme(terme: str) -> str:
    """Forme comparée et empreintée du terme : sans espaces de bord, sans casse."""
    return terme.strip().casefold()


def empreinte_terme(terme: str) -> str:
    """Empreinte SHA-256 (hexadécimal) du terme normalisé, celle qui est journalisée.

    Le condensat remplace le terme dans l'audit (BE-129 CA-1) : il permet de
    retrouver les recherches identiques sans conserver ce qui a été cherché."""
    return hashlib.sha256(normaliser_terme(terme).encode("utf-8")).hexdigest()


def valider_terme(terme: str) -> str:
    """Renvoie le terme normalisé, ou lève 422 s'il est trop court ou trop long."""
    normalise = normaliser_terme(terme)
    if not TERME_MIN <= len(normalise) <= TERME_MAX:
        raise AppError(
            code="recherche_terme_invalide",
            message="Le terme de recherche doit compter entre 2 et 100 caractères.",
            status_code=422,
            field_errors={"q": [f"longueur attendue : entre {TERME_MIN} et {TERME_MAX} caractères"]},
        )
    return normalise


def _echapper_like(valeur: str) -> str:
    """Échappe les jokers SQL LIKE pour qu'un terme soit toujours une recherche littérale."""
    return valeur.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def projeter(organisation: Organization, complete: bool) -> dict:
    """Ligne de réponse : champs normalisés, ou champs complets si `complete` est vrai.

    Le contrat est la liste de champs ci-dessus, pas le modèle : aucun autre
    champ d'`organization` ne doit sortir par cette route (BE-129 CA-4)."""
    ligne = {
        "id": str(organisation.id),
        "name": organisation.name,
        "slug": organisation.slug,
        "status": organisation.status,
    }
    if complete:
        ligne["createdAt"] = organisation.createdAt.isoformat()
        ligne["updatedAt"] = organisation.updatedAt.isoformat()
    return ligne


async def rechercher_organisations(db: AsyncSession, scope: AdminScope, terme: str) -> list[Organization]:
    """Organisations dont le nom ou le slug contient `terme`, ou dont l'identifiant l'égale.

    `terme` est déjà normalisé (`valider_terme`). En portée tenant, seule
    l'organisation de la portée est lue. Les organisations supprimées logiquement
    (`deletedAt`) sont exclues."""
    stmt = select(Organization).where(Organization.deletedAt.is_(None))
    if not scope.is_platform:
        stmt = stmt.where(Organization.id == scope.organization_id)
    motif = f"%{_echapper_like(terme)}%"
    conditions = [
        Organization.name.ilike(motif, escape="\\"),
        Organization.slug.ilike(motif, escape="\\"),
    ]
    try:
        conditions.append(Organization.id == uuid.UUID(terme))
    except ValueError:
        # Le terme n'est pas un identifiant : seule la recherche textuelle s'applique.
        pass
    stmt = stmt.where(or_(*conditions)).order_by(Organization.name, Organization.id).limit(LIMITE_RESULTATS)
    return list((await db.execute(stmt)).scalars().all())
