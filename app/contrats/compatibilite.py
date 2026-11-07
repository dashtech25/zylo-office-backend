"""Règles de compatibilité d'un contrat, sans accès à la base (BE-215).

Un changement est **additif** (compatible, sans nouveau major) quand il n'ajoute que des
propriétés optionnelles. Il est **cassant** quand il retire une propriété, change le type
d'une propriété, ou rend requise une propriété qui ne l'était pas. Un changement cassant
exige une nouvelle version majeure ; le service de registre le refuse sinon.

`valider_payload` applique le lecteur tolérant : une propriété absente du schéma du
consommateur est ignorée sans erreur (coexistence N/N-1, CA-4).
"""

_TYPES_JSON: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def _proprietes(schema: dict) -> dict:
    return schema.get("properties", {}) or {}


def _requises(schema: dict) -> set[str]:
    return set(schema.get("required", []) or [])


def changements_cassants(ancien: dict, nouveau: dict) -> list[str]:
    """Liste lisible des changements cassants entre deux schémas ; vide si le changement est additif.

    Les messages nomment les propriétés concernées et ne recopient aucune valeur.
    """
    anciennes = _proprietes(ancien)
    nouvelles = _proprietes(nouveau)
    cassants: list[str] = []

    for nom, definition in anciennes.items():
        if nom not in nouvelles:
            cassants.append(f"propriété retirée : {nom}")
            continue
        type_ancien = definition.get("type")
        type_nouveau = nouvelles[nom].get("type")
        if type_ancien is not None and type_nouveau is not None and type_ancien != type_nouveau:
            cassants.append(f"type modifié : {nom}")

    for nom in sorted(_requises(nouveau) - _requises(ancien)):
        cassants.append(f"propriété devenue requise : {nom}")

    return cassants


def valider_payload(schema: dict, payload: dict) -> list[str]:
    """Erreurs de validation d'un payload contre un schéma de consommateur ; vide si valide.

    Contrôle la présence des propriétés requises et le type des propriétés connues. Les
    propriétés inconnues du schéma sont ignorées : un consommateur plus ancien ne rejette pas
    un champ ajouté par une version plus récente.
    """
    erreurs: list[str] = []
    for nom in sorted(_requises(schema)):
        if nom not in payload:
            erreurs.append(f"propriété requise absente : {nom}")

    for nom, definition in _proprietes(schema).items():
        if nom not in payload:
            continue
        type_attendu = definition.get("type")
        valeur = payload[nom]
        if type_attendu is None or valeur is None:
            continue
        types = _TYPES_JSON.get(type_attendu)
        est_booleen = isinstance(valeur, bool)
        if types is None or not isinstance(valeur, types) or (est_booleen and type_attendu != "boolean"):
            erreurs.append(f"type invalide : {nom}")

    return erreurs
