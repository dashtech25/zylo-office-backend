"""Politique de mot de passe : UNE seule règle pour tout le backend (T-013).

Intention : inscription, activation de compte (T-021/T-049), changement de mot de
passe et mot de passe temporaire du personnel passent tous par ce module. Aucun
autre endroit ne doit recopier une de ces règles.

Décision (docs/questions/securite/politique-mot-de-passe.md, option B,
recommandation NIST SP 800-63B) :
- 12 caractères minimum, comptés en caractères Unicode (pas en octets) ;
- 72 octets UTF-8 maximum : c'est la limite de bcrypt. Au-delà, le hachage
  ignore la fin du mot de passe en silence ; on refuse donc explicitement ;
- liste locale de mots de passe courants, comparée sans tenir compte de la casse
  et des accents. La liste ne contient que des entrées de 12 caractères ou plus :
  les plus courtes sont déjà refusées par la longueur minimale ;
- ni adresse e-mail ni nom : seuls les fragments d'au moins 5 caractères sont
  comparés (un prénom court comme « Jo » bloquerait trop de mots de passe) ;
- aucune règle de composition (majuscule, chiffre, symbole non exigés) ;
- un mot de passe fait d'un seul caractère répété est refusé.

Le frontend (src/shared/lib/validation.ts) reprend les mêmes règles de longueur,
d'octets, de répétition et de fragments. La liste de mots courants n'existe que
ici : le backend fait autorité, et ses messages s'affichent tels quels.
"""

import re
import unicodedata

from app.core.errors import AppError

LONGUEUR_MINIMALE = 12
LONGUEUR_MAXIMALE_OCTETS = 72
# Fragments trop courts pour être significatifs (prénom « Jo », domaine « ex »).
LONGUEUR_MINIMALE_FRAGMENT = 5

# Entrées sans accent, en minuscules, de 12 caractères ou plus. Source : listes
# publiques de mots de passe fréquents, réduites aux formes longues (les formes
# courtes sont déjà refusées par la longueur). À enrichir : limite connue (T-013).
MOTS_DE_PASSE_COURANTS: frozenset[str] = frozenset(
    {
        "motdepasse1234",
        "motdepasse12345",
        "motdepasse2026",
        "motdepasse2025",
        "bienvenue1234",
        "bienvenue2026",
        "bienvenue12345",
        "password1234",
        "password12345",
        "password123456",
        "password2026",
        "azerty123456",
        "azertyuiop123",
        "azertyuiopqsd",
        "qwerty123456",
        "qwertyuiop1234",
        "qwertyuiop123",
        "123456789012",
        "1234567890123",
        "1234567890abc",
        "abcdefghijkl",
        "abcdefghijklm",
        "abcdefghijklmn",
        "abcdefghijklmnopqrstuvwxyz",
        "letmein123456",
        "welcome123456",
        "changeme1234",
        "iloveyou12345",
        "monmotdepasse",
        "monmotdepasse1",
        "mot2passe1234",
        "soleil2026123",
        "zylooffice2026",
        "zylo-office123",
        "zylooffice1234",
        "administrateur",
        "administrateur1",
        "gestionnaire123",
        "stationservice1",
        "stationessence1",
    }
)

MESSAGE_LONGUEUR = f"Le mot de passe doit contenir au moins {LONGUEUR_MINIMALE} caractères."
MESSAGE_OCTETS = f"Le mot de passe ne doit pas dépasser {LONGUEUR_MAXIMALE_OCTETS} octets (UTF-8)."
MESSAGE_COURANT = "Ce mot de passe figure parmi les mots de passe les plus courants. Choisissez-en un autre."
MESSAGE_EMAIL = "Le mot de passe ne doit pas contenir votre adresse e-mail."
MESSAGE_NOM = "Le mot de passe ne doit pas contenir votre nom ni votre prénom."
MESSAGE_REPETITION = "Le mot de passe ne doit pas être constitué d'un seul caractère répété."
MESSAGE_IDENTIQUE = "Le nouveau mot de passe doit être différent de l'ancien."

_SEPARATEURS_NOM = re.compile(r"[\s\-'’.]+")


class PolitiqueMotDePasseErreur(ValueError):
    """Mot de passe refusé. `raisons` liste chaque règle violée, en français.

    Sous-classe de ValueError : Pydantic la convertit en erreur de validation
    (422) sans traitement particulier."""

    def __init__(self, raisons: list[str]):
        self.raisons = list(raisons)
        super().__init__(" ".join(self.raisons))


def _normalise(texte: str) -> str:
    """Minuscules et sans accents : « Véronique » et « veronique » se comparent."""
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c)).casefold()


def _fragments(email: str | None, nom_complet: str | None) -> tuple[list[str], list[str]]:
    fragments_email: list[str] = []
    if email:
        partie_locale = _normalise(email.strip()).split("@", 1)[0]
        if len(partie_locale) >= LONGUEUR_MINIMALE_FRAGMENT:
            fragments_email.append(partie_locale)
    fragments_nom: list[str] = []
    if nom_complet:
        for mot in _SEPARATEURS_NOM.split(_normalise(nom_complet.strip())):
            if len(mot) >= LONGUEUR_MINIMALE_FRAGMENT:
                fragments_nom.append(mot)
    return fragments_email, fragments_nom


def raisons_mot_de_passe(
    mot_de_passe: str,
    *,
    email: str | None = None,
    nom_complet: str | None = None,
) -> list[str]:
    """Liste des règles violées (vide si le mot de passe est accepté)."""
    raisons: list[str] = []
    if len(mot_de_passe) < LONGUEUR_MINIMALE:
        raisons.append(MESSAGE_LONGUEUR)
    if len(mot_de_passe.encode("utf-8")) > LONGUEUR_MAXIMALE_OCTETS:
        raisons.append(MESSAGE_OCTETS)

    normalise = _normalise(mot_de_passe)
    if normalise in MOTS_DE_PASSE_COURANTS:
        raisons.append(MESSAGE_COURANT)

    fragments_email, fragments_nom = _fragments(email, nom_complet)
    if any(fragment in normalise for fragment in fragments_email):
        raisons.append(MESSAGE_EMAIL)
    if any(fragment in normalise for fragment in fragments_nom):
        raisons.append(MESSAGE_NOM)

    if len(mot_de_passe) > 1 and len(set(mot_de_passe)) == 1:
        raisons.append(MESSAGE_REPETITION)
    return raisons


def verifie_mot_de_passe(
    mot_de_passe: str,
    *,
    email: str | None = None,
    nom_complet: str | None = None,
) -> None:
    """Lève PolitiqueMotDePasseErreur si une règle est violée."""
    raisons = raisons_mot_de_passe(mot_de_passe, email=email, nom_complet=nom_complet)
    if raisons:
        raise PolitiqueMotDePasseErreur(raisons)


def erreur_api(exc: PolitiqueMotDePasseErreur) -> AppError:
    """Réponse 422 `password_policy_violation` : une entrée `details` par règle violée."""
    return AppError(
        code="password_policy_violation",
        message=" ".join(exc.raisons),
        status_code=422,
        details=[{"message": raison} for raison in exc.raisons],
    )
