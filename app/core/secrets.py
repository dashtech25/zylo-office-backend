"""Magasin des valeurs de secrets, en mémoire du processus (BE-230).

Intention :
- Une seule place où les valeurs vivent : le registre (`secret_registry`, voir
  app/operator/secrets_models.py) ne stocke que des métadonnées, jamais une valeur.
  Les valeurs sont injectées depuis l'environnement au démarrage
  (`SecretStore.depuis_environnement`) et ne sont jamais écrites dans un journal,
  une réponse d'API ou un message d'erreur.
- Rotation : `rotate` remplace la valeur courante. L'ancienne valeur n'est plus
  retenue nulle part dans ce magasin : tout credential dérivé de l'ancienne
  (ici une signature HMAC) cesse donc d'être accepté dès la rotation. Pas de liste
  de révocation à maintenir, donc pas de fenêtre de tolérance implicite.
- Les signatures utilisent HMAC-SHA256 et une comparaison à temps constant
  (`hmac.compare_digest`) pour ne pas révéler la valeur par le temps de réponse.

Ce module est transverse (core/) : il ne connaît aucun module métier ni le registre.
"""

import hmac
import hashlib
import os
from collections.abc import Iterable, Mapping


class SecretStore:
    """Valeurs courantes des secrets nommés. Une valeur absente ou vide n'existe pas."""

    def __init__(self, valeurs: Mapping[str, str] | None = None) -> None:
        # Copie défensive : l'appelant ne partage pas le dictionnaire interne.
        self._valeurs: dict[str, str] = dict(valeurs or {})

    @classmethod
    def depuis_environnement(cls, noms: Iterable[str]) -> "SecretStore":
        """Construit le magasin à partir des variables d'environnement `noms`.

        Intention : seules les variables nommées sont lues ; une variable absente
        est simplement absente du magasin (le contrôle de démarrage la refusera
        si elle est obligatoire)."""
        return cls({nom: os.environ[nom] for nom in noms if os.environ.get(nom)})

    def valeur_courante(self, nom: str) -> str | None:
        """Valeur actuelle du secret `nom`, ou None si elle est absente ou vide."""
        valeur = self._valeurs.get(nom)
        return valeur or None

    def rotate(self, nom: str, nouvelle_valeur: str) -> None:
        """Remplace la valeur de `nom`. L'ancienne valeur cesse d'exister dans ce magasin.

        Piège évité : une valeur vide n'est jamais acceptée, sinon une rotation
        mal configurée ouvrirait l'accès avec une clé vide."""
        if not nouvelle_valeur:
            raise ValueError("Une rotation exige une valeur non vide.")
        self._valeurs[nom] = nouvelle_valeur

    def supprimer(self, nom: str) -> None:
        """Retire la valeur de `nom` du magasin : plus aucune résolution ni signature possible.

        Utilisé à la déconnexion d'une intégration (BE-239, CA-2) pour couper l'accès au
        secret. Supprimer une valeur absente ne lève rien : l'opération est idempotente.
        """
        self._valeurs.pop(nom, None)

    def signe(self, nom: str, message: bytes) -> str:
        """Signature HMAC-SHA256 de `message` avec la valeur courante de `nom`.

        Lève KeyError si le secret est absent : signer sans clé ne doit jamais
        produire une signature acceptable."""
        valeur = self.valeur_courante(nom)
        if valeur is None:
            raise KeyError(nom)
        return hmac.new(valeur.encode("utf-8"), message, hashlib.sha256).hexdigest()

    def signature_valide(self, nom: str, message: bytes, signature: str) -> bool:
        """Vrai si `signature` correspond à `message` sous la valeur COURANTE de `nom`.

        Une signature produite avant une rotation est donc refusée après elle."""
        valeur = self.valeur_courante(nom)
        if valeur is None:
            return False
        attendue = hmac.new(valeur.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(attendue, signature)
