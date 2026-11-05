"""Catalogue des codes d'erreur des événements, notifications et audit (BE-151).

Rôle : fixer la liste stable des douze codes `SCHEMA_INVALID` ... `AUDIT_WRITE_FAILED`, et pour
chacun une fiche (statut HTTP, classification temporaire ou permanente, action permise,
permission, issue idempotente). Une erreur de ce catalogue se construit par `ErreurCatalogue`,
qui rejette tout code hors liste dès sa construction (CA-4).

Enveloppe : ce module ne redéfinit pas l'enveloppe de réponse. `ErreurCatalogue` est une
sous-classe de `AppError` (app/core/errors.py, propriété de BE-001), donc la réponse reste
`{"error": {code, message, field_errors, details}, request_id}`.

Expurgation (CA-3) : le message exposé est toujours la phrase fixe de la fiche. Le texte détaillé
passé à l'erreur n'entre jamais dans la réponse ; il est seulement expurgé (`expurger`) et gardé
dans `detail_journal` pour le journal. Aucune valeur de secret ne sort donc d'une erreur de ce
catalogue.

Statuts HTTP : les six codes précisés par QE-PAR-01 (PERMISSION_DENIED 403, TENANT_MISMATCH 404,
VERSION_CONFLICT 409, SCHEMA_INVALID 422, RATE_LIMITED 429, CHANNEL_UNAVAILABLE et
REMOTE_UNAVAILABLE 503) suivent la définition. Les autres statuts, la classification, l'action
permise et l'issue idempotente sont NON DÉFINIS dans la source : recommandation appliquée,
à valider (QE-151 dans definition-travail/00-pilotage/POINTS-OUVERTS.md, à ouvrir).

Note : `SCHEMA_INVALID` est encore émis en 400 par app/evenements/enveloppe.py (BE-150), écart
avec la recommandation 422 de cette fiche. Non corrigé ici : hors périmètre de BE-151.
"""

from dataclasses import dataclass
from enum import Enum
import re

from app.core.errors import AppError

# Longueur maximale d'un détail journalisé : au-delà, le texte est tronqué (pas de dump de payload).
LONGUEUR_DETAIL_MAX = 200

# Marqueurs de valeur secrète, comparés sans tenir compte de la casse. Une valeur suivant
# `marqueur=` ou `marqueur:` est remplacée avant toute trace.
_MOTIF_SECRET = re.compile(
    r"(?i)(password|passwd|motdepasse|secret|token|apikey|credential|privatekey|signature)"
    r"(\s*[=:]\s*)\S+"
)


class Classification(str, Enum):
    """Nature d'un échec : `TEMPORAIRE` peut réussir à la reprise, `PERMANENTE` ne réussira pas
    sans action (correction de la requête, renouvellement d'un secret, décision humaine)."""

    TEMPORAIRE = "temporaire"
    PERMANENTE = "permanente"


class CodeErreur(str, Enum):
    """Les douze codes stables du catalogue. La valeur est le code exposé dans l'enveloppe.

    Ajouter ou renommer un code est une décision de contrat : le test de non-régression de BE-151
    (CA-1) doit être mis à jour en même temps, avec la définition.
    """

    SCHEMA_INVALID = "SCHEMA_INVALID"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    REPLAY_DUPLICATE = "REPLAY_DUPLICATE"
    CONSENT_SUPPRESSED = "CONSENT_SUPPRESSED"
    CHANNEL_UNAVAILABLE = "CHANNEL_UNAVAILABLE"
    REMOTE_UNAVAILABLE = "REMOTE_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    SECRET_EXPIRED = "SECRET_EXPIRED"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    AUDIT_WRITE_FAILED = "AUDIT_WRITE_FAILED"


@dataclass(frozen=True)
class FicheErreur:
    """Fiche d'un code d'erreur.

    - `http_status` : statut HTTP de la réponse de l'enveloppe.
    - `classification` : temporaire (reprise possible) ou permanente.
    - `message` : phrase fixe renvoyée au client ; jamais de texte libre.
    - `action_permise` : action que la reprise autorise (étiquette courte, lisible par un outil).
    - `permission` : permission requise pour l'action de reprise, None si aucune.
    - `issue_idempotente` : vrai si rejouer l'opération ne produit pas d'effet en double.
    """

    code: CodeErreur
    http_status: int
    classification: Classification
    message: str
    action_permise: str
    permission: str | None
    issue_idempotente: bool


T = Classification.TEMPORAIRE
P = Classification.PERMANENTE

FICHES: dict[CodeErreur, FicheErreur] = {
    CodeErreur.SCHEMA_INVALID: FicheErreur(
        CodeErreur.SCHEMA_INVALID, 422, P, "Données de l'événement invalides.", "corriger_la_requete", None, True
    ),
    CodeErreur.TENANT_MISMATCH: FicheErreur(
        CodeErreur.TENANT_MISMATCH, 404, P, "Ressource introuvable.", "ne_pas_reessayer", None, True
    ),
    CodeErreur.PERMISSION_DENIED: FicheErreur(
        CodeErreur.PERMISSION_DENIED, 403, P, "Action non autorisée.", "demander_un_droit", None, True
    ),
    CodeErreur.SIGNATURE_INVALID: FicheErreur(
        CodeErreur.SIGNATURE_INVALID, 401, P, "Signature invalide.", "verifier_la_signature", None, True
    ),
    CodeErreur.REPLAY_DUPLICATE: FicheErreur(
        CodeErreur.REPLAY_DUPLICATE, 409, P, "Événement déjà traité.", "aucune_action", None, True
    ),
    CodeErreur.CONSENT_SUPPRESSED: FicheErreur(
        CodeErreur.CONSENT_SUPPRESSED, 403, P, "Envoi supprimé par le consentement.", "ne_pas_envoyer", None, True
    ),
    CodeErreur.CHANNEL_UNAVAILABLE: FicheErreur(
        CodeErreur.CHANNEL_UNAVAILABLE, 503, T, "Canal indisponible.", "reessayer_plus_tard", None, False
    ),
    CodeErreur.REMOTE_UNAVAILABLE: FicheErreur(
        CodeErreur.REMOTE_UNAVAILABLE, 503, T, "Service distant indisponible.", "reessayer_plus_tard", None, False
    ),
    CodeErreur.RATE_LIMITED: FicheErreur(
        CodeErreur.RATE_LIMITED, 429, T, "Trop de requêtes.", "reessayer_apres_delai", None, True
    ),
    CodeErreur.SECRET_EXPIRED: FicheErreur(
        CodeErreur.SECRET_EXPIRED, 401, P, "Secret expiré.", "renouveler_le_secret", None, True
    ),
    CodeErreur.VERSION_CONFLICT: FicheErreur(
        CodeErreur.VERSION_CONFLICT, 409, T, "Conflit de version.", "relire_puis_reessayer", None, True
    ),
    CodeErreur.AUDIT_WRITE_FAILED: FicheErreur(
        CodeErreur.AUDIT_WRITE_FAILED, 500, T, "Écriture d'audit impossible.", "reessayer_la_mutation", None, True
    ),
}


def resoudre_code(code: "CodeErreur | str") -> CodeErreur:
    """Renvoie le `CodeErreur` correspondant, ou lève ValueError si le code est hors catalogue.

    Accepte la valeur exacte du catalogue (texte) ou l'énumération. Un code libre de BE-001
    (`validation_error`, `webhook_eventId_missing`) ou une chaîne vide sont refusés (CA-4)."""
    if isinstance(code, CodeErreur):
        return code
    try:
        return CodeErreur(code)
    except ValueError:
        raise ValueError(f"code d'erreur hors catalogue BE-151 : {code!r}") from None


def expurger(texte: str | None) -> str | None:
    """Masque les valeurs secrètes d'un texte et le tronque à `LONGUEUR_DETAIL_MAX` caractères.

    Un motif `secret=valeur` ou `token: valeur` garde la clé et remplace la valeur par
    `[expurgé]`. Ce filtre protège le journal ; la réponse HTTP ne reprend jamais ce texte."""
    if texte is None:
        return None
    masque = _MOTIF_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[expurgé]", texte)
    return masque[:LONGUEUR_DETAIL_MAX]


class ErreurCatalogue(AppError):
    """Erreur levée avec un code du catalogue BE-151.

    Le code, le statut et le message viennent de la fiche. `detail` est accepté pour le journal
    seulement : il est expurgé et stocké dans `detail_journal`, jamais placé dans le message ni
    dans `details` de la réponse (CA-3). Un code hors catalogue lève ValueError (CA-4).
    """

    def __init__(
        self,
        code: "CodeErreur | str",
        *,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        fiche = FICHES[resoudre_code(code)]
        super().__init__(
            code=fiche.code.value,
            message=fiche.message,
            status_code=fiche.http_status,
            headers=headers,
        )
        self.fiche = fiche
        self.detail_journal = expurger(detail)
