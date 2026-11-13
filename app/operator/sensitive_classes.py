"""Registre des classes d'action sensible (BE-127), en lecture seule.

Une classe d'action sensible est une famille de commandes d'exploitation qui
modifient un tenant, un abonnement, une facture, un droit ou une configuration.
Chaque classe porte une fiche standard (onze champs, voir
`definition-travail/03-plateforme/administration-plateforme/02-autorites-actions-et-controles.md`
section 4) ; les commandes futures devront s'y référer.

Pourquoi un registre en code et non en table : la liste est candidate et ne
donne aucun droit. Son changement passe par une migration de code relue, pas
par une API (CA-4 : aucune route d'écriture). Il n'existe donc aucune table
`sensitive_action_class` et aucune migration pour BE-127.

Valeurs non arbitrées : `approvalWindow`, les champs de fiche et les motifs de
réversibilité dépendent des propriétaires PH-07 à PH-16 et des questions Q-04 à
Q-07. Ils restent à `None` ou « NON DÉFINI ». Aucun seuil, aucune durée, aucun
approbateur n'est inventé ici.

Choix provisoire, fermé par défaut : `requiresDoubleValidation` et
`requiresReauth` valent `True` pour toutes les classes tant que les
propriétaires ne tranchent pas. Un défaut ouvert accorderait une commande sans
contrôle.

Garde : `exiger_approbation` est le point de contrôle que les futures commandes
appelleront avant d'exécuter une classe à double validation.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.core.errors import AppError

# Les onze champs de la fiche standard, dans l'ordre de la source.
CHAMPS_FICHE: tuple[str, ...] = (
    "autorite", "cible", "motif", "previsualisation", "limite", "confirmation",
    "execution", "echec_reprise", "notification", "audit", "revue",
)

_A_ARBITRER = "NON DÉFINI : à arbitrer (PH-07 à PH-16, Q-04 à Q-07)"


@dataclass(frozen=True)
class SensitiveActionClass:
    """Une classe d'action sensible et sa fiche standard.

    `approvalWindow` : durée d'approbation, `None` tant que non définie.
    `reversible` : `True` ou `False` si la source le dit, `None` sinon.
    `fiche` : valeur de chacun des champs de `CHAMPS_FICHE`.
    """

    code: str
    libelle: str
    requiresDoubleValidation: bool
    requiresReauth: bool
    approvalWindow: str | None
    reversible: bool | None
    risk_note: str
    fiche: Mapping[str, str] = field(default_factory=lambda: {c: _A_ARBITRER for c in CHAMPS_FICHE})


CLASSES: tuple[SensitiveActionClass, ...] = (
    SensitiveActionClass(
        code="tenant.suspension", libelle="Suspension ou rétablissement d'un tenant",
        requiresDoubleValidation=True, requiresReauth=True, approvalWindow=None, reversible=True,
        risk_note="Coupe l'accès des utilisateurs du tenant. Rétablissement par transition inverse.",
    ),
    SensitiveActionClass(
        code="entitlement.module", libelle="Activation ou changement d'entitlement ou de module",
        requiresDoubleValidation=True, requiresReauth=True, approvalWindow=None, reversible=None,
        risk_note="Modifie les droits dérivés. Ne jamais éditer directement un entitlement dérivé.",
    ),
    SensitiveActionClass(
        code="facturation.operation", libelle="Opération de facture, paiement ou remboursement",
        requiresDoubleValidation=True, requiresReauth=True, approvalWindow=None, reversible=None,
        risk_note="Engage de l'argent. Gouvernée par la politique financière et le PSP, à décider.",
    ),
    SensitiveActionClass(
        code="role.adhesion", libelle="Changement de rôle ou d'adhésion",
        requiresDoubleValidation=True, requiresReauth=True, approvalWindow=None, reversible=None,
        risk_note="Élargit ou restreint les accès d'une personne. Risque d'élévation.",
    ),
    SensitiveActionClass(
        code="donnees.export_suppression_restauration", libelle="Export, suppression ou restauration de données",
        requiresDoubleValidation=True, requiresReauth=True, approvalWindow=None, reversible=False,
        risk_note="Un export déjà remis ne se reprend pas. La suppression touche rétention et sauvegardes.",
    ),
    SensitiveActionClass(
        code="acces.contenu_exceptionnel", libelle="Accès exceptionnel au contenu d'un tenant",
        requiresDoubleValidation=True, requiresReauth=True, approvalWindow=None, reversible=None,
        risk_note="Ouvre une lecture de contenu tenant. Exige une demande légale ou client identifiée.",
    ),
    SensitiveActionClass(
        code="evenement.replay", libelle="Rejeu d'un événement à effet métier",
        requiresDoubleValidation=True, requiresReauth=True, approvalWindow=None, reversible=None,
        risk_note="Un rejeu peut dupliquer un effet métier. Vérifier l'idempotence avant exécution.",
    ),
    SensitiveActionClass(
        code="configuration.modification", libelle="Modification de configuration ou de credential",
        requiresDoubleValidation=True, requiresReauth=True, approvalWindow=None, reversible=None,
        risk_note="Peut couper une intégration ou exposer un secret. Jamais de valeur de secret dans la réponse.",
    ),
)

_PAR_CODE: dict[str, SensitiveActionClass] = {c.code: c for c in CLASSES}


def classe_par_code(code: str) -> SensitiveActionClass | None:
    """Renvoie la classe de ce code, ou `None` si elle n'existe pas dans le registre."""
    return _PAR_CODE.get(code)


def exiger_approbation(classe: SensitiveActionClass, approbateur_id: uuid.UUID | None) -> None:
    """Lève 409 `approval_required` si la classe exige une double validation sans approbateur.

    Ne contrôle pas encore que l'approbateur diffère de l'initiateur : la commande
    qui appelle cette garde connaîtra les deux identités, pas le registre.
    """
    if classe.requiresDoubleValidation and approbateur_id is None:
        raise AppError(
            code="approval_required",
            message="Cette action exige une approbation par un second opérateur.",
            status_code=409,
        )
