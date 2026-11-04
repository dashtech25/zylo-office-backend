"""Messages d'erreur et textes localisables (BE-256).

Rôle : relier chaque code d'erreur de l'enveloppe (app/core/errors.py) à une
clé de message `erreur.<code>`, et résoudre cette clé dans la locale
configurée. Le module ne contient aucune langue ni aucune locale : les textes
vivent dans des catalogues JSON du dossier `locales/` (un fichier par locale,
ex. `<locale>.json`, clé -> texte), et la locale vient de
`settings.DEFAULT_LOCALE`.

Règles :

- Locale NON DÉFINIE (QE-EXP-23, recommandation appliquée) : `DEFAULT_LOCALE`
  vaut None, `message_pour` renvoie le texte de repli passé par l'appelant.
  Le comportement de BE-001 et BE-220 est donc inchangé tant que la locale
  n'est pas configurée.
- Une locale qui ne respecte pas le format `xx`, `xxx`, `xx-XX` ou `xx_XX`
  est ignorée : elle ne sert jamais de chemin de fichier. C'est la seule
  protection contre une lecture hors du dossier de catalogues.
- Une clé absente du catalogue, ou un catalogue absent, renvoie le texte de
  repli. Un message manquant ne fait jamais planter une réponse d'erreur.
- Les codes métier (`AppError`) gardent leur texte propre tant qu'ils n'ont
  pas de clé dans un catalogue. Seul l'ensemble `CODES_ENVELOPPE` est couvert
  par les catalogues livrés (CA-1).
"""

import json
import re
from pathlib import Path

from app.core.config import settings

# Codes dont le message est résolu par le catalogue : les deux codes que
# l'enveloppe émet elle-même (table BE-220 de errors.py).
CODES_ENVELOPPE: tuple[str, ...] = ("validation_error", "internal_error")

# Dossier des catalogues, lu à chaque appel (pas de constante figée à l'import)
# pour que les tests puissent le substituer.
CATALOGUE_DIR: Path = Path(__file__).resolve().parent / "locales"

# Format accepté pour une locale : deux ou trois lettres, puis un séparateur
# optionnel et deux à huit caractères alphanumériques. Tout autre texte est
# refusé avant d'atteindre le système de fichiers.
_FORMAT_LOCALE = re.compile(r"[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})?")

# Format d'un code d'erreur : minuscules, chiffres et tirets bas (ex.
# `validation_error`, `http_404`). Empêche toute clé libre ou tout chemin.
_FORMAT_CODE = re.compile(r"[a-z][a-z0-9_]*")


def cle_message(code: str) -> str:
    """Renvoie la clé de catalogue `erreur.<code>` d'un code d'erreur.

    Lève ValueError si le code ne respecte pas le format minuscules/chiffres/
    tirets bas : une clé ne se construit jamais à partir d'une saisie libre."""
    if not _FORMAT_CODE.fullmatch(code):
        raise ValueError(f"code d'erreur hors format : {code!r}")
    return f"erreur.{code}"


def locales_disponibles() -> list[str]:
    """Liste triée des locales livrées : un catalogue `<locale>.json` par locale.

    Les noms de fichiers ne sont filtrés que par le format de locale, pour que
    l'ajout d'une locale passe par l'ajout d'un fichier, sans toucher au code."""
    return sorted(
        fichier.stem
        for fichier in CATALOGUE_DIR.glob("*.json")
        if _FORMAT_LOCALE.fullmatch(fichier.stem)
    )


def charger_catalogue(locale: str) -> dict[str, str]:
    """Renvoie le catalogue (clé -> texte) d'une locale, ou {} s'il n'existe pas.

    Une locale hors format ou un fichier absent donnent {} : l'appelant retombe
    alors sur son texte de repli, sans exception."""
    if not _FORMAT_LOCALE.fullmatch(locale):
        return {}
    chemin = CATALOGUE_DIR / f"{locale}.json"
    if not chemin.is_file():
        return {}
    return json.loads(chemin.read_text(encoding="utf-8"))


def locale_par_defaut() -> str | None:
    """Locale configurée (`settings.DEFAULT_LOCALE`), ou None si NON DÉFINIE.

    Une chaîne vide dans la configuration vaut NON DÉFINIE."""
    valeur = (settings.DEFAULT_LOCALE or "").strip()
    return valeur or None


def message_pour(code: str, texte_repli: str, locale: str | None = None) -> str:
    """Renvoie le message du code dans la locale demandée, ou le texte de repli.

    `locale` vaut la locale configurée si l'appelant ne la donne pas. Sans
    locale (NON DÉFINIE), sans catalogue ou sans clé, `texte_repli` est
    renvoyé tel quel : le contrat de réponse ne change jamais de forme."""
    locale_retenue = locale if locale is not None else locale_par_defaut()
    if not locale_retenue:
        return texte_repli
    texte = charger_catalogue(locale_retenue).get(cle_message(code))
    return texte or texte_repli
