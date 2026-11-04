"""Résultat de reprise d'un échec (BE-151, CA-2).

Rôle : décrire ce qu'un consommateur ou un opérateur reçoit après un échec, pour décider de la
suite : code stable, classification, corrélation, horodatage, action permise, permission requise
et issue idempotente. Ce résultat n'est pas une réponse d'erreur HTTP : il est produit côté
traitement (file, webhook, notification) et journalisé.

Chaque champ est obligatoire, sans valeur par défaut. Un champ absent fait échouer la validation,
ce qui protège un consommateur contre un résultat incomplet. `permission` est nullable mais
présent : `None` signifie « aucune permission requise », pas « champ omis ».

Le résultat est construit uniquement à partir de la fiche du code (`resultat_reprise`), jamais
recopié à la main, pour qu'un changement de fiche se propage partout.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from app.core.erreurs.codes import Classification, CodeErreur, FICHES, resoudre_code


class ResultatReprise(BaseModel):
    """Résultat de reprise immuable. Champs dans l'ordre du contrat (CA-2).

    - `code` : code stable du catalogue.
    - `classification` : `temporaire` ou `permanente`.
    - `correlationId` : identifiant de corrélation de la chaîne d'événements, recopié tel quel.
    - `horodatage` : instant de l'échec, toujours aware en UTC.
    - `actionPermise` : action que la reprise autorise.
    - `permission` : permission requise pour cette action, ou None.
    - `issueIdempotente` : vrai si rejouer l'opération ne duplique pas l'effet.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: CodeErreur
    classification: Classification
    correlationId: str = Field(min_length=1)
    horodatage: datetime
    actionPermise: str
    permission: str | None
    issueIdempotente: bool


def resultat_reprise(
    code: "CodeErreur | str",
    correlation_id: str,
    *,
    horodatage: datetime | None = None,
) -> ResultatReprise:
    """Construit le résultat de reprise d'un code du catalogue.

    `horodatage` vaut l'instant courant (UTC) si l'appelant ne le fournit pas. Un code hors
    catalogue lève ValueError, comme `ErreurCatalogue`. Une corrélation vide est refusée par
    la validation du modèle."""
    fiche = FICHES[resoudre_code(code)]
    return ResultatReprise(
        code=fiche.code,
        classification=fiche.classification,
        correlationId=correlation_id,
        horodatage=horodatage if horodatage is not None else datetime.now(timezone.utc),
        actionPermise=fiche.action_permise,
        permission=fiche.permission,
        issueIdempotente=fiche.issue_idempotente,
    )
