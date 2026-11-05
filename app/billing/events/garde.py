"""Garde anti-donnée de carte pour les événements de facturation (BE-074, CA-4).

Rôle : refuser, avant toute persistance, un payload qui contient un numéro de carte (PAN) ou
un code de sécurité (CVV). Les événements ne transportent ni PAN, ni CVV, ni secret : ils sont
conservés dans l'outbox et l'inbox, lisibles par plusieurs consommateurs.

Deux détections, combinées :
- par nom de clé, après normalisation (casse, `_` et `-` ignorés), sur une liste fermée de
  noms exacts (`pan`, `cvv`, `numeroCarte`, `securityCode`, ...). La comparaison est exacte et
  non par sous-chaîne, pour ne pas refuser `company` ou `panier` ;
- par valeur : toute chaîne ou tout entier composé de 13 à 19 chiffres (séparateurs espace et
  tiret tolérés) et valide selon l'algorithme de Luhn est refusé, quel que soit le nom de clé.
  Une référence de facture de même longueur mais non valide au sens de Luhn n'est pas refusée.

Invariant : le message d'erreur ne recopie jamais la valeur fautive.
"""

from typing import Any, Mapping

from app.core.erreurs.codes import CodeErreur, ErreurCatalogue

# Noms de clés désignant une donnée de carte, comparés après normalisation exacte.
CLES_DONNEE_CARTE = frozenset(
    {"pan", "cvv", "cvv2", "cvc", "cardnumber", "numerocarte", "numerodecarte", "securitycode", "cryptogramme"}
)

_LONGUEUR_MIN_PAN = 13
_LONGUEUR_MAX_PAN = 19


def _cle_est_donnee_carte(cle: str) -> bool:
    """Vrai si le nom de clé, normalisé, désigne une donnée de carte."""
    return cle.lower().replace("_", "").replace("-", "") in CLES_DONNEE_CARTE


def _est_pan_luhn(texte: str) -> bool:
    """Vrai si `texte` ne contient que des chiffres (espaces et tirets tolérés), 13 à 19 au total, et passe Luhn."""
    chiffres = texte.replace(" ", "").replace("-", "")
    if not chiffres.isdigit() or not (_LONGUEUR_MIN_PAN <= len(chiffres) <= _LONGUEUR_MAX_PAN):
        return False
    somme = 0
    for rang, caractere in enumerate(reversed(chiffres)):
        chiffre = int(caractere)
        if rang % 2 == 1:
            chiffre *= 2
            if chiffre > 9:
                chiffre -= 9
        somme += chiffre
    return somme % 10 == 0


def _contient_donnee_carte(valeur: Any) -> bool:
    """Parcourt récursivement dicts et listes ; teste les noms de clés et les valeurs scalaires."""
    if isinstance(valeur, Mapping):
        for cle, sous_valeur in valeur.items():
            if isinstance(cle, str) and _cle_est_donnee_carte(cle):
                return True
            if _contient_donnee_carte(sous_valeur):
                return True
        return False
    if isinstance(valeur, (list, tuple)):
        return any(_contient_donnee_carte(element) for element in valeur)
    if isinstance(valeur, bool):
        return False
    if isinstance(valeur, int):
        return _est_pan_luhn(str(valeur))
    if isinstance(valeur, str):
        return _est_pan_luhn(valeur)
    return False


def valider_sans_donnee_carte(payload: Any) -> None:
    """Lève `SCHEMA_INVALID` si `payload` contient un PAN ou un CVV ; ne renvoie rien sinon.

    Ne persiste rien. L'appelant doit appeler cette garde avant toute écriture d'outbox ou
    d'inbox : une donnée refusée ne doit jamais atteindre la base (CA-4).
    """
    if _contient_donnee_carte(payload):
        raise ErreurCatalogue(
            CodeErreur.SCHEMA_INVALID,
            detail="événement de facturation refusé : donnée de carte détectée dans le payload",
        )
