"""Accessibilité effective d'un module pour un utilisateur (BE-053).

Intention : répondre, à chaque demande, à la question « cet utilisateur peut-il
exercer cette action sur ce module maintenant ? » par `allow` ou `deny` et un
motif stable. Le résultat est un diagnostic : il est calculé à la volée et n'est
jamais persisté (matrice-etats-modules-et-droits.md, section 1). Aucune ligne
n'est écrite par ce module.

Deux couches séparées :

- `evaluer_acces` est PURE : elle ne lit rien, elle applique l'ordre des portes
  à des faits déjà collectés (`FaitsAcces`). C'est elle que testent les critères
  unitaires.
- `evaluer_acces_effectif` collecte les faits depuis la base, en lecture seule,
  en réutilisant les briques existantes : appartenance (core/authz), permission
  (rbac/service), état du module et entitlement (modules_registry/service),
  réconciliation ouverte (modules_registry/reconciliation). Elle ne recalcule
  aucune règle de droit déjà portée ailleurs.

Ordre des portes, la première qui échoue donne le motif :

    NOT_MEMBER -> PERMISSION_MISSING -> MODULE_NOT_ACTIVE
      -> RECONCILIATION_PENDING -> ENTITLEMENT_REQUIRED
      -> QUOTA_EXCEEDED -> POLICY_MISSING

Décisions de cadrage (points ouverts, voir POINTS-OUVERTS.md) :
- QE-MOD-14 : une capacité sans déclaration `requiresEntitlement` est traitée
  comme exigeant un entitlement (fail closed). Un `None` ne vaut jamais « pas
  d'exigence ».
- QE-MOD-06 : une action mutante sans politique déclarée est refusée par défaut.
  Une action de lecture n'est pas concernée par cette porte.
- Quota : le comptage réel des usages n'existe pas encore ; la porte n'est
  évaluée que si l'appelant fournit un résultat (`quota`).

Ce module ne remplace pas `core/authz.decide` (moteur d'enforcement de BE-226)
qui protège les routes ; il en fournit la version diagnostic, avec les motifs de
BE-053 et les portes propres à l'accessibilité (réconciliation, fail closed).
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import _membre_actif
from app.modules_registry.models import OrganizationModule
from app.modules_registry.reconciliation import reconciliation_ouverte_pour
from app.modules_registry.service import get_module_entitlement_access, is_module_active
from app.rbac.module_policy import permission_belongs_to_module
from app.rbac.models import Permission
from app.rbac.service import user_has_permission

# Motifs stables : utilisés par l'API de diagnostic et les tests.
MOTIF_NON_MEMBRE = "NOT_MEMBER"
PERMISSION_MANQUANTE = "PERMISSION_MISSING"
MODULE_NON_ACTIF = "MODULE_NOT_ACTIVE"
RECONCILIATION_EN_ATTENTE = "RECONCILIATION_PENDING"
ENTITLEMENT_REQUIS = "ENTITLEMENT_REQUIRED"
QUOTA_DEPASSE = "QUOTA_EXCEEDED"
POLITIQUE_ABSENTE = "POLICY_MISSING"

# Type de sujet utilisé par la réconciliation pour une activation de module.
TYPE_SUJET_ACTIVATION = "tenant_module"

# Dernier segment d'un code `domaine.entite.action` qui désigne une lecture seule.
# Toute autre action est considérée comme mutante (fail closed).
SEGMENTS_LECTURE = frozenset({"read", "lire", "list", "view", "consulter"})


@dataclass(frozen=True)
class FaitsAcces:
    """Faits déjà collectés, passés à la fonction pure `evaluer_acces`.

    - `capacite_exige_entitlement` : True / False issu de la déclaration de la
      capacité ; None si la capacité n'est pas déclarée (traitée comme True).
    - `quota_conforme` : None si la porte n'est pas évaluée.
    """

    membre_actif: bool
    permission_accordee: bool
    module_actif: bool
    reconciliation_pendante: bool
    capacite_exige_entitlement: bool | None
    entitlement_valide: bool
    quota_conforme: bool | None
    action_mutante: bool
    politique_declaree: bool


@dataclass(frozen=True)
class Evaluation:
    """Résultat : `motif` est None quand l'accès est accordé."""

    autorise: bool
    motif: str | None

    @property
    def decision(self) -> str:
        """Forme attendue par l'API : `allow` ou `deny`."""
        return "allow" if self.autorise else "deny"


_ACCORDEE = Evaluation(autorise=True, motif=None)


def _refus(motif: str) -> Evaluation:
    return Evaluation(autorise=False, motif=motif)


def evaluer_acces(faits: FaitsAcces) -> Evaluation:
    """Applique l'ordre des portes à des faits donnés. Fonction pure, sans effet.

    Une capacité non déclarée (None) exige un entitlement : l'absence de
    déclaration ne doit jamais ouvrir l'accès (QE-MOD-14).
    """
    if not faits.membre_actif:
        return _refus(MOTIF_NON_MEMBRE)
    if not faits.permission_accordee:
        return _refus(PERMISSION_MANQUANTE)
    if not faits.module_actif:
        return _refus(MODULE_NON_ACTIF)
    if faits.reconciliation_pendante:
        return _refus(RECONCILIATION_EN_ATTENTE)
    exige_entitlement = faits.capacite_exige_entitlement is not False
    if exige_entitlement and not faits.entitlement_valide:
        return _refus(ENTITLEMENT_REQUIS)
    if faits.quota_conforme is False:
        return _refus(QUOTA_DEPASSE)
    if faits.action_mutante and not faits.politique_declaree:
        return _refus(POLITIQUE_ABSENTE)
    return _ACCORDEE


def est_action_mutante(action: str) -> bool:
    """Vrai sauf si le dernier segment de `action` désigne une lecture."""
    return action.rsplit(".", 1)[-1] not in SEGMENTS_LECTURE


async def evaluer_acces_effectif(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    module_code: str,
    action: str,
    capacites: Mapping[str, bool] | None = None,
    quota: Callable[[], Awaitable[bool]] | None = None,
) -> Evaluation:
    """Collecte les faits en lecture seule puis applique `evaluer_acces`.

    - `action` : code de permission `domaine.entite.action` visé.
    - `capacites` : déclarations `requiresEntitlement` par action. Absente de
      la table = non déclarée = fail closed.
    - `quota` : awaitable optionnel ; non évalué si absent.

    N'écrit jamais en base (CA-4). Le tenant doit avoir été vérifié par l'appelant
    (la route utilise la garde d'organisation courante).
    """
    membre = await _membre_actif(db, user_id, organization_id)
    permission = await user_has_permission(db, user_id, organization_id, action)

    module_actif = await is_module_active(db, organization_id, module_code)

    activation_id = (
        await db.execute(
            select(OrganizationModule.id).where(
                OrganizationModule.organizationId == organization_id,
                OrganizationModule.moduleCode == module_code,
            )
        )
    ).scalar_one_or_none()
    reconciliation = (
        activation_id is not None
        and await reconciliation_ouverte_pour(db, organization_id, TYPE_SUJET_ACTIVATION, activation_id)
    )

    # Une ligne d'entitlement absente vaut « non configuré » : l'accès legacy reste ouvert pour
    # les autres parcours, mais CA-3 exige un refus quand la capacité exige un entitlement.
    etat_entitlement, entitlement_ok = await get_module_entitlement_access(db, organization_id, module_code)
    entitlement_valide = entitlement_ok and etat_entitlement != "not_configured"

    permission_module = (
        await db.execute(select(Permission.moduleCode).where(Permission.code == action))
    ).scalar_one_or_none()
    politique = permission_module is not None and permission_belongs_to_module(action, permission_module, module_code)

    quota_conforme = await quota() if quota is not None else None

    faits = FaitsAcces(
        membre_actif=membre,
        permission_accordee=permission,
        module_actif=module_actif,
        reconciliation_pendante=bool(reconciliation),
        capacite_exige_entitlement=(capacites or {}).get(action),
        entitlement_valide=entitlement_valide,
        quota_conforme=quota_conforme,
        action_mutante=est_action_mutante(action),
        politique_declaree=politique,
    )
    return evaluer_acces(faits)
