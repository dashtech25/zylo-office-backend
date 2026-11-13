"""Résolution d'un paramètre pour un contexte donné (BE-156).

Ordre de priorité, du plus fort au plus faible :

    utilisateur > module > organisation > plateforme > défaut déclaré

- `utilisateur` : valeur écrite pour l'utilisateur courant (`scopeId` = son identifiant) ;
- `module` : valeur écrite pour le module demandé (`scopeId` = identifiant du module) ;
- `organisation` : valeur écrite pour l'organisation courante (`scopeId` = son identifiant) ;
- `plateforme` : valeur globale (`scopeId` = `PLATEFORME_SCOPE_ID`) ;
- `défaut` : `setting_definition.defaultValue`, si la définition en porte un.

Ces niveaux sont ceux recommandés par la définition ; l'ordre exact reste à confirmer
(QE-PAR-06). Le niveau gagnant est la valeur « courante » de chaque niveau, c'est-à-dire
sa dernière version écrite (`lire_valeur_courante`) ; la règle d'application propre à
BE-157 n'est pas encore prise en compte.

Règles qui ne se négocient pas :
- aucune valeur n'est inventée : sans valeur à aucun niveau ni défaut déclaré, le
  résultat est « absent » (`absent=True`, `valeur=None`, `niveau=None`) ;
- un conflit n'est jamais résolu en silence : si deux niveaux renseignés ont des valeurs
  de nature JSON différente (texte, nombre, booléen, liste, objet, nul), la résolution
  lève `AppError` `PARAMETRE_CONFLIT` (409), même si un niveau plus prioritaire
  existe. Le message ne contient jamais les valeurs ;
- isolation tenant : chaque lecture de niveau filtre sur l'identifiant de portée exact.
  La valeur d'une autre organisation n'est jamais lue (voir `lire_valeur_courante`).

Le module ne pose aucune règle d'accès : l'appelant doit avoir déjà vérifié la
permission de lecture du scope (BE-158).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.parametres.models import SettingDefinition
from app.parametres.service import lire_valeur_courante

# Identifiant de `scopeId` utilisé pour la portée plateforme (point ouvert de BE-154) :
# une constante nulle, distincte de tout identifiant d'organisation, d'utilisateur ou de module.
PLATEFORME_SCOPE_ID = uuid.UUID(int=0)

# Niveaux de la priorité, du plus fort au plus faible (hors défaut déclaré).
_NIVEAUX_PAR_PRIORITE = ("utilisateur", "module", "organisation", "plateforme")

# Nom du niveau renvoyé quand la valeur vient du défaut déclaré.
NIVEAU_DEFAUT = "defaut"


@dataclass(frozen=True)
class ResultatParametre:
    """Résultat d'une résolution.

    - `valeur` : valeur retenue, ou None si `absent` ;
    - `niveau` : nom du niveau gagnant (`utilisateur`, `module`, `organisation`,
      `plateforme` ou `defaut`), ou None si `absent` ;
    - `absent` : True quand aucun niveau ni défaut ne fournit de valeur.
    """

    valeur: object
    niveau: str | None
    absent: bool


def _nature(valeur: object) -> str:
    """Nature JSON d'une valeur, pour détecter deux niveaux incompatibles.

    `bool` est testé avant `int` : en Python `True` est un entier, mais une valeur
    booléenne et un nombre sont incompatibles pour un paramètre.
    """
    if valeur is None:
        return "nul"
    if isinstance(valeur, bool):
        return "booleen"
    if isinstance(valeur, (int, float)):
        return "nombre"
    if isinstance(valeur, str):
        return "texte"
    if isinstance(valeur, list):
        return "liste"
    if isinstance(valeur, dict):
        return "objet"
    return "inconnue"


async def resoudre_parametre(
    db: AsyncSession,
    definition_key: str,
    *,
    organisation_id: uuid.UUID,
    utilisateur_id: uuid.UUID,
    module_id: uuid.UUID,
) -> ResultatParametre:
    """Résout la valeur d'un paramètre pour une organisation, un utilisateur et un module.

    Parcourt les niveaux dans l'ordre de priorité, lit la valeur courante de chacun, puis :
    1. si deux niveaux renseignés ont des natures différentes, lève `PARAMETRE_CONFLIT` (409) ;
    2. sinon renvoie le niveau le plus prioritaire renseigné ;
    3. sinon renvoie le défaut déclaré (`niveau='defaut'`), s'il existe ;
    4. sinon renvoie « absent ».

    Lève `SCHEMA_INVALID` (422) si la clé n'est pas déclarée en base : une clé inconnue
    n'a ni défaut ni priorité, et la résolution ne l'invente pas.

    Les identifiants de portée sont ceux du module (voir `_NIVEAUX_PAR_PRIORITE`) : `organisation_id`
    pour l'organisation, `utilisateur_id` pour l'utilisateur, `module_id` pour le module,
    `PLATEFORME_SCOPE_ID` pour la plateforme. Une valeur écrite pour une autre
    organisation ou un autre utilisateur n'est jamais lue.
    """
    definition = await db.get(SettingDefinition, definition_key)
    if definition is None:
        raise AppError(
            "SCHEMA_INVALID",
            "Paramètre non déclaré.",
            status_code=422,
        )

    identifiants = {
        "utilisateur": utilisateur_id,
        "module": module_id,
        "organisation": organisation_id,
        "plateforme": PLATEFORME_SCOPE_ID,
    }
    portees = {
        "utilisateur": "utilisateur",
        "module": "module",
        "organisation": "organisation",
        "plateforme": "plateforme",
    }

    renseignes: list[tuple[str, object]] = []
    for niveau in _NIVEAUX_PAR_PRIORITE:
        ligne = await lire_valeur_courante(db, definition_key, portees[niveau], identifiants[niveau])
        if ligne is not None:
            renseignes.append((niveau, ligne.value))

    natures = {_nature(valeur) for _, valeur in renseignes}
    if len(natures) > 1:
        # Le message ne cite ni les valeurs ni les niveaux : seul le fait du conflit est signalé.
        raise AppError(
            "PARAMETRE_CONFLIT",
            "Des niveaux du paramètre ont des valeurs incompatibles.",
            status_code=409,
        )

    if renseignes:
        niveau, valeur = renseignes[0]
        return ResultatParametre(valeur=valeur, niveau=niveau, absent=False)

    if definition.defaultValue is not None:
        return ResultatParametre(valeur=definition.defaultValue, niveau=NIVEAU_DEFAUT, absent=False)

    return ResultatParametre(valeur=None, niveau=None, absent=True)
