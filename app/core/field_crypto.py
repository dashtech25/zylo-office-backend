"""Chiffrement applicatif des champs sensibles (T-027).

Intention :
- Fernet (AES-128-CBC + HMAC-SHA256, bibliothèque `cryptography`) : chiffrement
  authentifié, une altération de la valeur stockée est détectée au déchiffrement.
- La clé n'est jamais utilisée telle quelle : `APP_FIELD_ENCRYPTION_KEY` (au moins
  32 caractères, exigée hors development/test par core/config.py) est étirée par
  HKDF-SHA256 en une clé Fernet de 32 octets. Ainsi toute chaîne suffisamment
  longue convient, sans contrainte de format base64 pour l'opérateur.
- Préfixe `enc:v1:` : distingue sans ambiguïté une valeur chiffrée d'une valeur
  en clair historique pendant la transition.
- Les messages d'erreur ne contiennent jamais la valeur ni la clé.

Ce module est transverse (core/) : il ne connaît aucun module métier.
Les appelants décident où le déchiffrement a lieu (voir docs/architecture/securite/secrets.md).
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import SECRET_MIN_LENGTH, settings

PREFIXE_CHIFFRE = "enc:v1:"

# Sel et contexte fixes : ils séparent cette dérivation de tout autre usage de la
# même chaîne. Changer ces valeurs rend illisibles toutes les valeurs chiffrées.
_SEL_DERIVATION = b"zylo-office/field-encryption"
_CONTEXTE_DERIVATION = b"fernet-v1"


class ChiffrementError(RuntimeError):
    """Chiffrement ou déchiffrement impossible (clé absente, invalide, valeur altérée).

    Le message ne contient jamais la valeur chiffrée, ni le clair, ni la clé.
    """


def _fernet() -> Fernet:
    cle = settings.APP_FIELD_ENCRYPTION_KEY
    if not cle:
        raise ChiffrementError("APP_FIELD_ENCRYPTION_KEY absente : chiffrement impossible.")
    if len(cle) < SECRET_MIN_LENGTH:
        raise ChiffrementError(
            f"APP_FIELD_ENCRYPTION_KEY invalide : au moins {SECRET_MIN_LENGTH} caractères requis."
        )
    derivee = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=_SEL_DERIVATION, info=_CONTEXTE_DERIVATION
    ).derive(cle.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derivee))


def fernet_maitre() -> Fernet:
    """Fernet dérivé de `APP_FIELD_ENCRYPTION_KEY`, public pour l'enveloppe des clés (BE-231).

    Utilisé par core/crypto.py pour chiffrer les clés de données stockées en base.
    Même contrôle de longueur et même dérivation que `chiffrer` : une seule clé maître."""
    return _fernet()


def est_chiffre(valeur: str) -> bool:
    return valeur.startswith(PREFIXE_CHIFFRE)


def chiffrer(clair: str) -> str:
    """Retourne la valeur à stocker (préfixée). Non déterministe : deux appels diffèrent."""
    return PREFIXE_CHIFFRE + _fernet().encrypt(clair.encode("utf-8")).decode("ascii")


def dechiffrer(stocke: str) -> str:
    """Inverse de `chiffrer`. Refuse une valeur non préfixée, altérée ou chiffrée avec une autre clé."""
    if not est_chiffre(stocke):
        raise ChiffrementError("valeur non chiffrée : déchiffrement refusé.")
    try:
        clair = _fernet().decrypt(stocke[len(PREFIXE_CHIFFRE):].encode("ascii"))
    except (InvalidToken, UnicodeError) as exc:
        raise ChiffrementError("déchiffrement impossible : clé incorrecte ou valeur altérée.") from None
    return clair.decode("utf-8")


def lire_champ(chiffre: str | None, clair_historique: str | None) -> str:
    """Valeur utilisable d'un champ pendant la transition.

    Priorité à la colonne chiffrée. Repli sur la colonne en clair historique
    uniquement si la ligne n'a pas encore été migrée (voir
    scripts/chiffrer_mots_de_passe_holykell.py). Un champ vide lève une erreur.
    """
    if chiffre:
        return dechiffrer(chiffre)
    if clair_historique:
        return clair_historique
    raise ChiffrementError("champ chiffré vide : aucune valeur à lire.")
