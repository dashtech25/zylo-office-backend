"""Quotas et limites techniques de l'API (BE-191).

Deux familles, configurées séparément dans `Settings` :

- quota produit (`QUOTA_PRODUIT_*`) : nombre de requêtes autorisées par fenêtre,
  décidé par le produit (QE-API-17). Clé de comptage attendue : le tenant ;
- limite technique (`LIMITE_TECHNIQUE_*`) : protection de l'infrastructure,
  indépendante du produit. Clé attendue : l'adresse client.

Algorithme : fenêtre fixe. La fenêtre démarre à la première requête de la clé ;
à son échéance le compteur repart à zéro. Un dépassement lève `AppError` 429
(code `quota_depasse`) avec :

- l'en-tête HTTP `Retry-After` (secondes restant avant la fin de la fenêtre) ;
- `details = [{"retryAfter": s, "retryable": true}]`, exception au principe
  « details vide hors validation » de app/core/errors.py, choisie pour que le
  client lise le délai dans le corps comme dans l'en-tête.

Limite connue : les compteurs vivent dans la mémoire du processus. Avec plusieurs
workers, chacun compte pour lui ; un stockage partagé (PostgreSQL ou Redis) sera
nécessaire avant de dire qu'un quota est exact en production. BE-191 ne crée
aucune table ni migration. Les compteurs expirés sont purgés quand leur nombre
dépasse `_SEUIL_PURGE`, pour borner la mémoire.

Ce module n'est branché sur aucune route dans BE-191 : il fournit le contrôle,
que les routes de liste ou les modules activent via `exiger_quota`.

Documentation de module : chemin NON DÉFINI (QE-API-02), docstrings seules.
"""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

from app.core.config import settings
from app.core.errors import AppError

CATEGORIE_PRODUIT = "produit"
CATEGORIE_TECHNIQUE = "technique"

_SEUIL_PURGE = 10_000


@dataclass(frozen=True)
class PolitiqueQuota:
    """Règle de comptage : `max_requetes` par `fenetre_secondes`, pour une `categorie`
    (produit ou technique). `nom` sert au journal et aux messages, pas au calcul."""

    nom: str
    categorie: str
    max_requetes: int
    fenetre_secondes: int


def politique_produit() -> PolitiqueQuota:
    """Quota produit, lu dans `Settings` à chaque appel (les tests le remplacent)."""
    return PolitiqueQuota(
        nom=CATEGORIE_PRODUIT,
        categorie=CATEGORIE_PRODUIT,
        max_requetes=settings.QUOTA_PRODUIT_MAX_REQUETES,
        fenetre_secondes=settings.QUOTA_PRODUIT_FENETRE_SECONDES,
    )


def politique_technique() -> PolitiqueQuota:
    """Limite technique, lue dans `Settings` ; indépendante du quota produit."""
    return PolitiqueQuota(
        nom=CATEGORIE_TECHNIQUE,
        categorie=CATEGORIE_TECHNIQUE,
        max_requetes=settings.LIMITE_TECHNIQUE_MAX_REQUETES,
        fenetre_secondes=settings.LIMITE_TECHNIQUE_FENETRE_SECONDES,
    )


class ControleQuota:
    """Compteur à fenêtre fixe par clé. Une instance par politique : un quota produit
    et une limite technique ne partagent jamais leurs compteurs.

    `horloge` est injectable (par défaut `time.monotonic`) pour tester les fenêtres
    sans attendre."""

    def __init__(self, politique: PolitiqueQuota, horloge: Callable[[], float] = time.monotonic):
        self.politique = politique
        self._horloge = horloge
        self._compteurs: dict[str, tuple[float, int]] = {}

    def verifier(self, cle: str) -> None:
        """Compte une requête pour `cle`, ou lève `AppError` 429 si la fenêtre est pleine.

        La requête refusée n'est pas comptée : un client bloqué ne prolonge pas
        son blocage.
        """
        maintenant = self._horloge()
        debut, compte = self._compteurs.get(cle, (maintenant, 0))
        if maintenant - debut >= self.politique.fenetre_secondes:
            debut, compte = maintenant, 0
        if compte >= self.politique.max_requetes:
            restant = max(1, math.ceil(self.politique.fenetre_secondes - (maintenant - debut)))
            raise AppError(
                "quota_depasse",
                "Quota dépassé. Réessayez plus tard.",
                status_code=429,
                details=[{"retryAfter": restant, "retryable": True}],
                headers={"Retry-After": str(restant)},
            )
        self._compteurs[cle] = (debut, compte + 1)
        if len(self._compteurs) > _SEUIL_PURGE:
            self._purger(maintenant)

    def _purger(self, maintenant: float) -> None:
        """Retire les compteurs dont la fenêtre est échue."""
        fenetre = self.politique.fenetre_secondes
        self._compteurs = {c: (d, n) for c, (d, n) in self._compteurs.items() if maintenant - d < fenetre}


def exiger_quota(controle: ControleQuota, cle: Callable[[Request], str]) -> Callable[[Request], None]:
    """Fabrique une dépendance FastAPI qui compte la requête sous la clé `cle(request)`.

    Usage : `Depends(exiger_quota(controle, lambda r: r.state.tenant_id))`. La clé
    doit être lisible sur la requête entrante (en-tête, état posé par un middleware).
    """

    async def dependance(requete: Request) -> None:
        controle.verifier(cle(requete))

    return dependance
