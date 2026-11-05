"""Contrôles des runbooks d'exploitation de docs/exploitation/ (BE-257).

Un runbook est un fichier Markdown. Ses champs sont des lignes `Champ : valeur`
en début de ligne, non des phrases dans un paragraphe : c'est ce qui permet de
les vérifier sans interpréter la prose. Un champ vide compte comme absent.

Fonctions publiques :
- `sections_runbook` : découpe un runbook par titres `## ` (texte brut de chaque section).
- `valeur_champ` : valeur d'un champ `Champ : valeur` ; None si absent ou vide.
- `anomalies_section` : champs obligatoires manquants dans une section d'alerte.
- `anomalies_fichier_runbook` : refuse un runbook sans propriétaire (CA-3).
- `date_exercice` / `preuve_exercice` : date et preuve d'un exercice de restauration (CA-2).

Module sans dépendance vers `app.modules` ni vers la base : contrôle de texte pur,
exécuté par les tests de BE-257 et utilisable par le contrôle de livraison.
"""

import re
from datetime import date

CHAMPS_SECTION_ALERTE: tuple[str, ...] = ("Propriétaire", "Sévérité", "Escalade", "Première action")
"""Champs qu'une section de runbook d'alerte doit porter, dans cet ordre de lecture."""

PROPRIETAIRE = "Propriétaire"


def sections_runbook(texte: str) -> dict[str, str]:
    """Retourne {titre: corps} pour chaque section `## titre` du runbook.

    Le corps est le texte brut jusqu'au titre suivant, sans le titre lui-même.
    Le texte avant le premier titre n'est pas une section et est ignoré.
    """
    sections: dict[str, str] = {}
    titre: str | None = None
    lignes: list[str] = []
    for ligne in texte.splitlines():
        if ligne.startswith("## "):
            if titre is not None:
                sections[titre] = "\n".join(lignes)
            titre = ligne[3:].strip()
            lignes = []
        elif titre is not None:
            lignes.append(ligne)
    if titre is not None:
        sections[titre] = "\n".join(lignes)
    return sections


def valeur_champ(corps: str, champ: str) -> str | None:
    """Valeur de la ligne `champ : valeur` du texte, ou None si absente ou vide.

    Seule une ligne qui commence par le nom du champ compte : une mention dans une
    phrase ne vaut pas déclaration.
    """
    motif = re.compile(rf"^{re.escape(champ)}[ \t]*:[ \t]*(.*)$", re.MULTILINE)
    trouve = motif.search(corps)
    if trouve is None:
        return None
    valeur = trouve.group(1).strip()
    return valeur or None


def anomalies_section(corps: str) -> list[str]:
    """Champs obligatoires absents ou vides dans une section d'alerte (CA-1)."""
    return [champ for champ in CHAMPS_SECTION_ALERTE if valeur_champ(corps, champ) is None]


def anomalies_fichier_runbook(texte: str) -> list[str]:
    """Refuse un runbook sans propriétaire non vide (CA-3).

    Retourne ["Propriétaire"] si le champ manque ou est vide, sinon une liste vide.
    Un runbook sans propriétaire n'a personne pour le tenir à jour : il n'est pas accepté.
    """
    return [] if valeur_champ(texte, PROPRIETAIRE) is not None else [PROPRIETAIRE]


def date_exercice(texte: str) -> date | None:
    """Date de la ligne `Exercice : AAAA-MM-JJ`, ou None si absente ou invalide (CA-2)."""
    trouve = re.search(r"^Exercice[ \t]*:[ \t]*(\d{4}-\d{2}-\d{2})", texte, re.MULTILINE)
    if trouve is None:
        return None
    try:
        return date.fromisoformat(trouve.group(1))
    except ValueError:
        return None


def preuve_exercice(texte: str) -> str | None:
    """Chemin relatif du test de preuve, déclaré sur la ligne `Preuve : ...` (CA-2)."""
    trouve = re.search(r"^Preuve[ \t]*:.*?(tests/[\w./-]+\.py)", texte, re.MULTILINE)
    return trouve.group(1) if trouve else None
