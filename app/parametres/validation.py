"""Déclaration et validation des paramètres (BE-155).

Ce module tient le registre des paramètres connus du système. Un paramètre n'existe
pour l'application que s'il est déclaré ici avec :
- une règle de validation (`RegleValeur`) : type, bornes ou énumération ;
- un effet (`EFFETS_PARAMETRE`) : ce qui se passe quand la valeur change.

Trois garanties, toutes vérifiées en code et non seulement par convention :
- CA-1 : un paramètre sans règle n'entre pas dans le registre (`declarer` lève
  `ValueError`) ; `anomalies` détecte les entrées incohérentes pour le test de
  cohérence ;
- CA-3 : aucun effet n'est supposé par défaut. Sans effet déclaré, ou avec un effet
  hors liste, la déclaration est refusée ;
- CA-2 et CA-4 : `valider` rejette toute valeur hors règle, et tout paramètre absent
  du registre, en `AppError` code `SCHEMA_INVALID` (422). La validation ne crée
  jamais de ligne : l'écriture (BE-157) n'a lieu qu'après `valider` réussi.

Points NON DÉFINIS encore ouverts :
- le code HTTP de SCHEMA_INVALID est repris du catalogue (422, QE-PAR-01) ;
- les valeurs de `EFFETS_PARAMETRE` sont provisoires (QE-PAR-04).

Le registre réel `REGISTRE` est vide à ce stade : aucun paramètre métier n'est encore
déclaré. Les modules qui en ont besoin déclarent leurs paramètres à l'import, via
`REGISTRE.declarer`, en fournissant la règle et l'effet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.errors import AppError

# Effets possibles d'un paramètre. Valeurs provisoires : la définition ne les fixe pas
# encore (QE-PAR-04). Aucune n'est appliquée par défaut.
EFFETS_PARAMETRE: tuple[str, ...] = ("immediat", "prochain_cycle", "redemarrage")

# Types de valeur reconnus par une règle.
TYPES_VALEUR: tuple[str, ...] = ("booleen", "entier", "decimal", "texte", "enumeration")


@dataclass(frozen=True)
class RegleValeur:
    """Règle de validation d'un paramètre.

    - `valueType` : l'un de `TYPES_VALEUR`. `booleen` n'accepte que `bool` ; `entier`
      refuse aussi `bool` (qui est un sous-type de `int` en Python) ;
    - `minimum` / `maximum` : bornes incluses, pour `entier` et `decimal` ;
    - `longueurMaximum` : nombre maximal de caractères, pour `texte` ;
    - `valeursAdmises` : énumération de chaînes, obligatoire pour `enumeration`.

    Les bornes incohérentes (minimum > maximum, énumération vide) lèvent `ValueError`
    à la construction : une règle impossible à satisfaire ne doit jamais entrer dans
    le registre.
    """

    valueType: str
    minimum: float | int | None = None
    maximum: float | int | None = None
    longueurMaximum: int | None = None
    valeursAdmises: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.valueType not in TYPES_VALEUR:
            raise ValueError(f"type de valeur inconnu : {self.valueType!r}")
        if self.valueType == "enumeration" and not self.valeursAdmises:
            raise ValueError("une énumération exige au moins une valeur admise")
        if self.valueType != "enumeration" and self.valeursAdmises is not None:
            raise ValueError("valeursAdmises n'est admis que pour une énumération")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum supérieur au maximum")
        if self.valueType not in ("entier", "decimal") and (self.minimum is not None or self.maximum is not None):
            raise ValueError("bornes admises seulement pour entier et decimal")
        if self.longueurMaximum is not None and self.valueType != "texte":
            raise ValueError("longueurMaximum n'est admis que pour texte")

    def verifier(self, valeur: Any) -> bool:
        """Renvoie True si la valeur respecte la règle, False sinon.

        Ne lève jamais : le service décide quoi faire d'un refus (`RegistreParametres.valider`).
        """
        if self.valueType == "booleen":
            return isinstance(valeur, bool)
        if self.valueType == "entier":
            if isinstance(valeur, bool) or not isinstance(valeur, int):
                return False
            return self._dans_bornes(valeur)
        if self.valueType == "decimal":
            if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
                return False
            return self._dans_bornes(valeur)
        if self.valueType == "texte":
            if not isinstance(valeur, str):
                return False
            return self.longueurMaximum is None or len(valeur) <= self.longueurMaximum
        # enumeration
        return isinstance(valeur, str) and valeur in (self.valeursAdmises or ())

    def _dans_bornes(self, valeur: float | int) -> bool:
        if self.minimum is not None and valeur < self.minimum:
            return False
        if self.maximum is not None and valeur > self.maximum:
            return False
        return True


class RegistreParametres:
    """Ensemble des paramètres déclarés : clé -> (règle, effet).

    Une instance isolée sert aux tests ; l'application utilise `REGISTRE`.
    """

    def __init__(self) -> None:
        self._entrees: dict[str, tuple[RegleValeur, str]] = {}

    def declarer(self, cle: str, regle: RegleValeur | None, effet: str | None) -> None:
        """Déclare un paramètre. Refuse sans règle (CA-1) ou sans effet valide (CA-3).

        Une clé déjà déclarée est refusée : deux déclarations divergentes du même
        paramètre ne doivent pas coexister.
        """
        if not isinstance(regle, RegleValeur):
            raise ValueError(f"paramètre {cle!r} sans règle de validation")
        if effet not in EFFETS_PARAMETRE:
            raise ValueError(f"paramètre {cle!r} sans effet valide : {effet!r}")
        if cle in self._entrees:
            raise ValueError(f"paramètre {cle!r} déjà déclaré")
        self._entrees[cle] = (regle, effet)

    def cles(self) -> list[str]:
        """Clés déclarées, dans l'ordre de déclaration."""
        return list(self._entrees)

    def regle(self, cle: str) -> RegleValeur:
        """Règle d'un paramètre déclaré. Lève `KeyError` si la clé est absente."""
        return self._entrees[cle][0]

    def effet(self, cle: str) -> str:
        """Effet d'un paramètre déclaré. Lève `KeyError` si la clé est absente."""
        return self._entrees[cle][1]

    def anomalies(self) -> list[str]:
        """Liste les défauts de cohérence du registre ; vide si tout est conforme.

        Sert au test de cohérence : une entrée sans règle ou sans effet valide doit
        faire échouer le test. Avec `declarer` qui refuse ces cas, la liste ne peut
        être non vide qu'après une modification directe du registre.
        """
        defauts: list[str] = []
        for cle, (regle, effet) in self._entrees.items():
            if not isinstance(regle, RegleValeur):
                defauts.append(f"{cle} : règle absente")
            if effet not in EFFETS_PARAMETRE:
                defauts.append(f"{cle} : effet non déclaré")
        return defauts

    def valider(self, cle: str, valeur: Any) -> Any:
        """Valide une valeur pour un paramètre déclaré et la renvoie telle quelle.

        - clé absente du registre : `AppError` SCHEMA_INVALID 422 (CA-4) ;
        - valeur hors règle : `AppError` SCHEMA_INVALID 422 (CA-2).

        Le message ne reprend pas la valeur refusée : une valeur de paramètre peut être
        sensible (QE-PAR-12) et ne doit pas se retrouver dans une réponse d'erreur.
        """
        if cle not in self._entrees:
            raise AppError(
                "SCHEMA_INVALID",
                "Paramètre inconnu : il n'est pas déclaré dans le registre.",
                status_code=422,
            )
        if not self.regle(cle).verifier(valeur):
            raise AppError(
                "SCHEMA_INVALID",
                "Valeur de paramètre hors de la règle de validation.",
                status_code=422,
            )
        return valeur


# Registre de l'application. Vide tant qu'aucun module n'a déclaré de paramètre.
REGISTRE = RegistreParametres()
