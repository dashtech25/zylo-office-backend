"""Diagnostic paiement guidé (BE-132) : modèle et règles de domaine.

Table `payment_diagnostic` : un diagnostic lancé par un agent support (L1 ou L2) sur
un cas d'intervention (BE-123). Le parcours enregistre la qualification, la preuve
consultée, l'action permise, le résultat, l'état de vérification, l'échec ou la
reprise, l'escalade et la clôture. Le parcours est en lecture seule : il ne produit
aucune action financière (CA-2).

Droits (définition BE-132) :
- lancement et lecture : tout détenteur d'un droit de lecture sur le cas, selon la
  règle de BE-123 (`app.operator.cases.exiger_lecture`). Réutilisée telle quelle,
  sans seconde règle de portée (CA-3) ;
- action financière demandée depuis ce parcours : 403 (CA-2), quel que soit le rôle.

Règles de résultat :
- `conforme` : aucun chemin d'échec. Le diagnostic est clos (`closedAtUtc`) seulement
  si la vérification est `verifiee` ; sinon il reste ouvert en attente de vérification ;
- `echec` : `failurePath` = `escalade` et entrée d'audit `admin.payment_diagnostic.failure` ;
- `non_concluant` : `failurePath` = `reprise` et même entrée d'audit.
Le diagnostic en échec reste ouvert (`closedAtUtc` NULL) jusqu'à la reprise ou l'escalade.

`escalationId` reste NULL : la table d'escalade appartient à BE-142, non livrée.
Le lien est consigné en QE-ADM-BE132 (`app/operator/payment_diagnostic_router.py`) et
n'est pas simulé ici. La trace d'échec tient lieu d'escalade tant que BE-142 n'est pas
livré (CA-4 : « escalade ou reprise tracée »).

Pas de clé de carte, de PAN ni de CVV : la preuve est une référence (`proofConsultedRef`),
jamais le contenu du justificatif.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.errors import AppError
from app.shared.models import UUIDPrimaryKeyMixin

RESULTATS = ("conforme", "echec", "non_concluant")
VERIFICATIONS = ("verifiee", "non_verifiee")
CHEMINS_D_ECHEC = ("reprise", "escalade")

# Seule action permise depuis ce parcours : la consultation. Toute autre valeur est
# refusée avant l'écriture (voir `exiger_pas_d_action_financiere`).
ACTION_PERMISE = "consultation_seule"

# Actions qui déplacent de l'argent ou interrogent le PSP. Le parcours diagnostic ne
# les accepte jamais (BE-132 CA-2) ; elles relèvent de BE-136 et sont bloquées par défaut.
ACTIONS_FINANCIERES = frozenset({"remboursement", "avoir", "encaissement", "appel_psp", "nouvelle_tentative_psp"})

ACTION_ECHEC = "admin.payment_diagnostic.failure"
ACTION_OUVERTURE = "admin.payment_diagnostic.open"
ACTION_CLOTURE = "admin.payment_diagnostic.close"
TYPE_ENTITE_DIAGNOSTIC = "PaymentDiagnostic"


class PaymentDiagnostic(UUIDPrimaryKeyMixin, Base):
    """Un diagnostic paiement rattaché à un cas d'intervention.

    `permittedAction` vaut toujours `consultation_seule` à ce stade. `escalationId`
    reste NULL jusqu'à la livraison de BE-142. Aucune ligne n'est supprimée."""

    __tablename__ = "payment_diagnostic"
    __table_args__ = (
        CheckConstraint("result IN ('conforme', 'echec', 'non_concluant')", name="ck_payment_diagnostic_result"),
        CheckConstraint("\"verificationStatus\" IN ('verifiee', 'non_verifiee')", name="ck_payment_diagnostic_verification"),
        CheckConstraint(
            "\"failurePath\" IS NULL OR \"failurePath\" IN ('reprise', 'escalade')",
            name="ck_payment_diagnostic_failure_path",
        ),
        {"comment": "Diagnostic paiement guidé, lecture seule, rattaché à un cas d'intervention (BE-132)."},
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


def exiger_pas_d_action_financiere(action_demandee: str | None) -> None:
    """403 si l'agent demande une action financière depuis ce parcours (BE-132 CA-2).

    Une action absente ou de consultation est acceptée. Le 403 est celui du refus de
    droit (`admin_scope_denied`), comme pour les autres refus de BE-120 à BE-123."""
    if action_demandee in ACTIONS_FINANCIERES:
        raise AppError(
            code="admin_scope_denied",
            message="Action financière non permise depuis le diagnostic paiement.",
            status_code=403,
        )


def issue_du_diagnostic(result: str, verification_status: str) -> tuple[str | None, datetime | None]:
    """Chemin d'échec et date de clôture déduits du résultat et de la vérification.

    Renvoie `(failurePath, closedAtUtc)`. Un échec ou un résultat non concluant donne un
    chemin (`escalade` ou `reprise`) et laisse le diagnostic ouvert. Un résultat conforme
    ne se clôt que s'il est vérifié ; sinon il reste ouvert en attente de vérification.
    """
    if result == "echec":
        return "escalade", None
    if result == "non_concluant":
        return "reprise", None
    if verification_status == "verifiee":
        return None, datetime.now(timezone.utc)
    return None, None


def erreur_diagnostic_introuvable() -> AppError:
    return AppError(code="diagnostic_not_found", message="Diagnostic introuvable.", status_code=404)

