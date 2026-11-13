"""Chiffrement versionné des données et gestion des clés (BE-231).

Modèle d'enveloppe à deux niveaux :
- la clé maître `APP_FIELD_ENCRYPTION_KEY` (env, jamais en base) dérive, via
  core/field_crypto.py, un Fernet qui sert uniquement à ENVELOPPER les clés de
  données ; elle ne chiffre aucune donnée métier ;
- chaque version N possède une clé de données aléatoire, stockée en base
  (table `encryption_keys`) sous forme ENVELOPPÉE (`wrappedKey`). Une sauvegarde
  de la table ne contient donc jamais une clé de données en clair (CA-3).

Format d'une valeur chiffrée versionnée : `enc:v2:<version>:<jeton Fernet>`.
Les valeurs `enc:v1:` produites par field_crypto restent lisibles à l'identique
(clé maître directe) : ce module ne les remplace pas.

Cycle de vie d'une version (portée par app/operator/encryption_service.py) :
- `active` : chiffre les nouvelles écritures et déchiffre ;
- `retiree` : ne chiffre plus, déchiffre encore (lecture sans perte après rotation, CA-1) ;
- `revoquee` : matériel supprimé de la base (`wrappedKey` mis à NULL). Une
  valeur chiffrée avec elle ne se déchiffre plus, ni en mémoire ni après
  rechargement (CA-2). Révoquer une valeur encore chiffrée sous cette version
  rend donc ces valeurs illisibles : il faut ré-chiffrer avant révocation.

`AnneauDeCles` est l'état en mémoire d'un processus : il ne connaît ni la base
ni les rôles. Les décisions (qui peut tourner ou révoquer) restent dans le
service opérateur, qui appelle `assert_operator_user` avant toute mutation.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.field_crypto import ChiffrementError, fernet_maitre

PREFIXE_VERSIONNE = "enc:v2:"


def generer_cle_donnee() -> bytes:
    """Clé de données aléatoire d'une version, au format Fernet (base64 urlsafe, 32 octets).

    Retourne les octets base64 attendus par `Fernet(...)`. Ne jamais journaliser."""
    return Fernet.generate_key()


def envelopper_cle(cle_donnee: bytes) -> str:
    """Chiffre une clé de données par la clé maître : seule forme admise en base."""
    return fernet_maitre().encrypt(cle_donnee).decode("ascii")


def desenvelopper_cle(enveloppe: str) -> bytes:
    """Inverse de `envelopper_cle`. Une enveloppe altérée ou d'une autre clé maître lève ChiffrementError.

    Le message ne contient ni l'enveloppe ni la clé."""
    try:
        return fernet_maitre().decrypt(enveloppe.encode("ascii"))
    except (InvalidToken, UnicodeError):
        raise ChiffrementError("clé de données illisible : clé maître incorrecte ou enveloppe altérée.") from None


class AnneauDeCles:
    """Ensemble des versions de clés de données utilisables par le processus.

    Invariants :
    - au plus une version courante (celle qui chiffre) ;
    - une version révoquée est retirée de l'anneau : elle ne déchiffre plus.

    La règle « la version courante ne se révoque pas » est appliquée par le
    service, sur l'état de la BASE (seule source de vérité) : l'anneau est un
    instantané qui peut être en retard après une rotation. Si la version
    révoquée était encore courante ici, l'anneau n'écrit plus rien (fail closed)."""

    def __init__(self) -> None:
        self._fernets: dict[int, Fernet] = {}
        self._courante: int | None = None

    @property
    def version_courante(self) -> int | None:
        return self._courante

    def ajouter(self, version: int, cle_donnee: bytes, *, courante: bool = False) -> None:
        """Charge la clé de données de `version`. `courante=True` la désigne pour chiffrer."""
        self._fernets[version] = Fernet(cle_donnee)
        if courante:
            self._courante = version

    def revoquer(self, version: int) -> None:
        """Retire `version` de l'anneau, sans contrôle de rôle ni de statut (fait par le service)."""
        self._fernets.pop(version, None)
        if version == self._courante:
            self._courante = None

    def chiffrer(self, clair: str) -> str:
        """Valeur à stocker, sous la version courante. Lève ChiffrementError sans version courante."""
        if self._courante is None:
            raise ChiffrementError("aucune version de clé courante : chiffrement impossible.")
        jeton = self._fernets[self._courante].encrypt(clair.encode("utf-8")).decode("ascii")
        return f"{PREFIXE_VERSIONNE}{self._courante}:{jeton}"

    def dechiffrer(self, stocke: str) -> str:
        """Déchiffre une valeur `enc:v2:` dont la version est présente dans l'anneau.

        Une version absente (révoquée ou jamais chargée) lève ChiffrementError sans
        jamais laisser entrevoir la valeur ni la clé."""
        if not stocke.startswith(PREFIXE_VERSIONNE):
            raise ChiffrementError("valeur non versionnée : déchiffrement refusé.")
        version_texte, _, jeton = stocke[len(PREFIXE_VERSIONNE):].partition(":")
        try:
            version = int(version_texte)
        except ValueError:
            raise ChiffrementError("version de clé illisible dans la valeur chiffrée.") from None
        fernet = self._fernets.get(version)
        if fernet is None:
            raise ChiffrementError("version de clé absente ou révoquée : déchiffrement impossible.")
        try:
            return fernet.decrypt(jeton.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError):
            raise ChiffrementError("déchiffrement impossible : valeur altérée.") from None


__all__ = [
    "AnneauDeCles",
    "ChiffrementError",
    "PREFIXE_VERSIONNE",
    "desenvelopper_cle",
    "envelopper_cle",
    "generer_cle_donnee",
]
