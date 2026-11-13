"""Compatibilité, dépendances et plan de mise à jour d'une version de module (BE-044).

Ce module est purement fonctionnel : il ne touche pas à la base. Le service de persistance et les
routes (`admin_router.py`) lui passent des entrées déjà lues, et enregistrent ses résultats.

Contrat des données (format non défini par la spec, décisions de BE-044) :

- `prerequisites` d'une version : liste de `{"code": str, "version": str | None}`. `code` est la
  clé stable d'un module du catalogue ; `version` absent ou nul signifie « une version publiée
  quelconque de ce module ».
- `compatibility.manifestVersion` (entier) : version du contrat de manifeste visée par la version.
  Elle doit appartenir à `VERSIONS_MANIFESTE_SUPPORTEES` (`manifeste.py`) pour être `compatible`.
- `compatibility.rollbackPossible` (booléen strict) : la version source sait être restaurée. Absent
  ou non booléen = faux.

Règles de résultat (`evaluer_compatibilite`), dans l'ordre :

1. Dépendances : chaque prérequis doit correspondre à au moins une version **publiée** du
   catalogue. Sinon : motif `PREREQUISITE_MISSING`. Un prérequis qui revient dans la chaîne de
   dépendances en cours de parcours : motif `DEPENDENCY_CYCLE`. Un motif de ce type rend le
   résultat `incompatible` (fait établi, donc pas `unknown`).
2. Absence d'information : pas de `compatibility`, ou pas de `manifestVersion`, donne `unknown`
   avec motif `COMPATIBILITY_UNKNOWN`. Une version sans information n'est jamais `compatible` : on
   ne fabrique pas un état positif.
3. `manifestVersion` hors des versions supportées (ou booléen, qui vaut 1 en Python mais n'est pas
   un numéro de version) : `incompatible`, motif `MANIFEST_VERSION_UNSUPPORTED`.
4. Sinon : `compatible`.

Le parcours des dépendances est un parcours en profondeur qui conserve la pile des codes visités :
un code déjà présent dans la pile est un cycle. Un ensemble `visites` évite de réexplorer une
version déjà traitée (le coût reste borné par le nombre de versions du catalogue).

`construire_plan_mise_a_jour` produit le plan sans l'exécuter. Il ne contient jamais d'étape de
retour arrière : `rollbackPossible` est une information, pas une action. Un plan sans retour arrière
possible est `forwardOnly`.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.modules_registry.manifeste import VERSIONS_MANIFESTE_SUPPORTEES

RESULTAT_COMPATIBLE = "compatible"
RESULTAT_INCOMPATIBLE = "incompatible"
RESULTAT_UNKNOWN = "unknown"

MOTIF_DEPENDANCE_CYCLIQUE = "DEPENDENCY_CYCLE"
MOTIF_PREREQUIS_ABSENT = "PREREQUISITE_MISSING"
MOTIF_SANS_INFORMATION = "COMPATIBILITY_UNKNOWN"
MOTIF_MANIFESTE_NON_SUPPORTE = "MANIFEST_VERSION_UNSUPPORTED"


@dataclass(frozen=True)
class EntreeCatalogue:
    """Une version du catalogue, telle que l'évaluation la voit (aucun accès à la base)."""

    code: str
    version: str
    publiee: bool
    compatibility: dict | None
    prerequisites: list | None


@dataclass
class ResultatEvaluation:
    """Résultat d'une évaluation : `result` parmi compatible/incompatible/unknown, et les motifs."""

    result: str
    reasons: list[dict[str, Any]] = field(default_factory=list)


def _motif(motif: str, **detail: Any) -> dict[str, Any]:
    """Construit un motif lisible par l'audit : un code stable et les détails utiles."""
    return {"motif": motif, **detail}


def _manifeste_supporte(valeur: Any) -> bool:
    """Vrai si `valeur` est un entier de version de manifeste supporté (un booléen est refusé)."""
    return isinstance(valeur, int) and not isinstance(valeur, bool) and valeur in VERSIONS_MANIFESTE_SUPPORTEES


def _verifier_dependances(cible: EntreeCatalogue, catalogue: Sequence[EntreeCatalogue]) -> list[dict[str, Any]]:
    """Parcourt les prérequis de `cible` et renvoie les motifs `PREREQUISITE_MISSING` et `DEPENDENCY_CYCLE`.

    La pile `chemin` porte les codes du parcours courant (la cible incluse) ; `visites` évite de
    traiter deux fois la même version publiée."""
    motifs: list[dict[str, Any]] = []
    visites: set[tuple[str, str]] = set()

    def parcourir(entree: EntreeCatalogue, chemin: tuple[str, ...]) -> None:
        for prerequis in entree.prerequisites or []:
            if not isinstance(prerequis, dict) or not isinstance(prerequis.get("code"), str):
                motifs.append(_motif(MOTIF_PREREQUIS_ABSENT, prerequis=prerequis))
                continue
            code = prerequis["code"]
            version = prerequis.get("version")
            candidates = [
                e
                for e in catalogue
                if e.code == code and e.publiee and (version is None or e.version == version)
            ]
            if not candidates:
                motifs.append(_motif(MOTIF_PREREQUIS_ABSENT, module=code, version=version))
                continue
            if code in chemin:
                motifs.append(_motif(MOTIF_DEPENDANCE_CYCLIQUE, chemin=[*chemin, code]))
                continue
            for candidat in candidates:
                if (candidat.code, candidat.version) in visites:
                    continue
                visites.add((candidat.code, candidat.version))
                parcourir(candidat, (*chemin, code))

    parcourir(cible, (cible.code,))
    return motifs


def evaluer_compatibilite(cible: EntreeCatalogue, catalogue: Sequence[EntreeCatalogue]) -> ResultatEvaluation:
    """Évalue la compatibilité de `cible` face au catalogue (règles en tête de module).

    `catalogue` doit contenir `cible` ou ses prérequis ; une version non publiée n'est jamais une
    dépendance disponible. Le résultat ne dépend que des entrées passées."""
    motifs_dependances = _verifier_dependances(cible, catalogue)
    if motifs_dependances:
        return ResultatEvaluation(result=RESULTAT_INCOMPATIBLE, reasons=motifs_dependances)

    compatibilite = cible.compatibility
    if not isinstance(compatibilite, dict) or compatibilite.get("manifestVersion") is None:
        return ResultatEvaluation(result=RESULTAT_UNKNOWN, reasons=[_motif(MOTIF_SANS_INFORMATION)])

    if not _manifeste_supporte(compatibilite["manifestVersion"]):
        return ResultatEvaluation(
            result=RESULTAT_INCOMPATIBLE,
            reasons=[_motif(MOTIF_MANIFESTE_NON_SUPPORTE, manifestVersion=compatibilite["manifestVersion"])],
        )
    return ResultatEvaluation(result=RESULTAT_COMPATIBLE, reasons=[])


def construire_plan_mise_a_jour(
    from_version: str, to_version: str, *, source_compatibility: dict | None
) -> dict[str, Any]:
    """Construit le plan de passage de `from_version` à `to_version`, sans l'exécuter.

    `source_compatibility` est la compatibilité de la version source ; seul son
    `rollbackPossible` booléen strict compte. Le plan ne contient aucune étape de retour arrière,
    même si `rollbackPossible` vaut vrai : `forwardOnly` indique seulement l'absence de retour
    arrière possible."""
    rollback_possible = (
        isinstance(source_compatibility, dict) and source_compatibility.get("rollbackPossible") is True
    )
    steps = [
        {"ordre": 1, "action": "evaluer_compatibilite", "toVersion": to_version},
        {"ordre": 2, "action": "appliquer_version", "fromVersion": from_version, "toVersion": to_version},
        {"ordre": 3, "action": "verifier_migrations", "toVersion": to_version},
    ]
    return {"steps": steps, "rollbackPossible": rollback_possible, "forwardOnly": not rollback_possible}
