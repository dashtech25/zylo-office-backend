"""Diagnostic abonnement guidé (BE-133) : modèle et règles de domaine.

Table `subscription_diagnostic` : un diagnostic lancé par un agent support (L1 ou L2) sur
un cas d'intervention (BE-123), pour un abonnement du tenant du cas. Le parcours suit les
mêmes huit étapes que le diagnostic paiement (BE-132) : qualification, preuve consultée,
action permise, résultat, vérification, échec ou reprise, escalade et clôture. Le
parcours est en lecture seule : il ne modifie ni les axes d'un abonnement (BE-079), ni
un entitlement dérivé. Toute correction passe par BE-135.

Droits (définition BE-133) :
- lancement et lecture : tout détenteur d'un droit de lecture sur le cas, selon la règle
  de BE-123 (`app.operator.cases.exiger_lecture`), réutilisée telle quelle ;
- modification directe d'un entitlement dérivé, ou toute correction d'abonnement, demandée
  depuis ce parcours : 403 (CA-2). Une écriture directe sur la ressource de diagnostic
  elle-même n'a pas de route : elle renvoie 405.

Règles de résultat : identiques à BE-132 (voir `app.operator.payment_diagnostic.issue_du_diagnostic`).
Un échec ou un résultat non concluant laisse le diagnostic ouvert avec un chemin
(`escalade` ou `reprise`) et une entrée d'audit `admin.subscription_diagnostic.failure`.
Un résultat conforme ne se clôt que si la vérification est faite.

Rétablissement d'abonnement (CA-4) : le parcours ne rétablit jamais un abonnement. La
seule porte d'écriture des axes reste `app.billing.subscriptions.etats.transition_etat`
(BE-079), qui renvoie 409 `INVALID_TRANSITION` quand les préconditions de transition ne
sont pas remplies.

`escalationId` reste NULL : la table d'escalade appartient à BE-142, non livrée (même
choix que BE-132, QE-ADM-BE132). Aucune donnée de carte ni de preuve brute n'est stockée :
`proofConsultedRef` est une référence.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.errors import AppError
from app.operator.payment_diagnostic import ACTIONS_FINANCIERES
from app.shared.models import UUIDPrimaryKeyMixin

# Seule action permise depuis ce parcours : la consultation.
ACTION_PERMISE = "consultation_seule"

# Actions de correction d'abonnement ou de modification d'entitlement. Elles relèvent de
# BE-135 et sont refusées depuis le parcours diagnostic (BE-133 CA-2).
ACTIONS_ABONNEMENT_INTERDITES = frozenset({
    "modification_entitlement",
    "changement_plan",
    "resiliation",
    "retablissement",
})

ACTIONS_REFUSEES = ACTIONS_FINANCIERES | ACTIONS_ABONNEMENT_INTERDITES

ACTION_ECHEC = "admin.subscription_diagnostic.failure"
ACTION_OUVERTURE = "admin.subscription_diagnostic.open"
ACTION_CLOTURE = "admin.subscription_diagnostic.close"
TYPE_ENTITE_DIAGNOSTIC = "SubscriptionDiagnostic"


class SubscriptionDiagnostic(UUIDPrimaryKeyMixin, Base):
    """Un diagnostic abonnement rattaché à un cas d'intervention.

    `permittedAction` vaut toujours `consultation_seule`. `escalationId` reste NULL jusqu'à
    la livraison de BE-142. Aucune ligne n'est supprimée."""

    __tablename__ = "subscription_diagnostic"
    __table_args__ = (
        CheckConstraint("result IN ('conforme', 'echec', 'non_concluant')", name="ck_subscription_diagnostic_result"),
        CheckConstraint(
            "\"verificationStatus\" IN ('verifiee', 'non_verifiee')",
            name="ck_subscription_diagnostic_verification",
        ),
        CheckConstraint(
            "\"failurePath\" IS NULL OR \"failurePath\" IN ('reprise', 'escalade')",
            name="ck_subscription_diagnostic_failure_path",
        ),
        {"comment": "Diagnostic abonnement guidé, lecture seule, rattaché à un cas d'intervention (BE-133)."},
    )

    caseId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intervention_case.id"), nullable=False, index=True,
    )
    qualification: Mapped[str] = mapped_column(String(200), nullable=False)
    proofConsultedRef: Mapped[str] = mapped_column(String(200), nullable=False)
    permittedAction: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    verificationStatus: Mapped[str] = mapped_column(String(16), nullable=False)
    failurePath: Mapped[str | None] = mapped_column(String(16), nullable=True)
    escalationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    closedAtUtc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def exiger_pas_de_correction_d_abonnement(action_demandee: str | None) -> None:
    """403 si l'agent demande depuis ce parcours une action financière ou une correction
    d'abonnement (BE-133 CA-2).

    Une action absente ou de consultation est acceptée. Le 403 est celui du refus de droit
    (`admin_scope_denied`), comme dans BE-132. Aucune écriture n'a lieu avant ce contrôle."""
    if action_demandee in ACTIONS_REFUSEES:
        raise AppError(
            code="admin_scope_denied",
            message="Correction d'abonnement non permise depuis le diagnostic abonnement.",
            status_code=403,
        )
