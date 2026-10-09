"""Liste blanche unique des types de fichiers acceptés par le stockage (T-014,
décision `docs/questions/securite/types-fichiers-autorises.md`, option A) :
PDF, PNG, JPEG, WebP. Les formats bureautiques ne sont ajoutés que sur demande
écrite du client.

Intention :
- le type est détecté par les octets (signatures), jamais par le nom ni par le
  Content-Type déclaré par le navigateur ;
- l'extension stockée est celle du type détecté, jamais celle fournie par
  l'utilisateur ;
- seuls les types de cette liste sont affichables en ligne depuis l'API ; tout
  le reste est téléchargé (voir `app/shared/storage_router.py`).

Ce module ne contient aucune logique métier : il est partagé par tous les modules
(règle de `app/shared/`)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TypeFichier:
    extension: str
    mime: str


PDF = TypeFichier(".pdf", "application/pdf")
PNG = TypeFichier(".png", "image/png")
JPEG = TypeFichier(".jpg", "image/jpeg")
WEBP = TypeFichier(".webp", "image/webp")

TYPES_AUTORISES: tuple[TypeFichier, ...] = (PDF, PNG, JPEG, WEBP)

# Extensions et types MIME pouvant être servis en ligne (affichage navigateur).
# Tout autre type est servi en `Content-Disposition: attachment`.
EXTENSIONS_AFFICHABLES: frozenset[str] = frozenset(t.extension for t in TYPES_AUTORISES)
MIME_AFFICHABLES: frozenset[str] = frozenset(t.mime for t in TYPES_AUTORISES)


def detecter_type(contenu: bytes) -> TypeFichier | None:
    """Retourne le type réel du contenu, ou None s'il n'est pas dans la liste blanche.

    Signatures : le PDF peut être précédé de quelques octets (le standard autorise
    un décalage), on cherche donc `%PDF-` dans les premiers 1024 octets. Les autres
    formats ont leur signature en tête de fichier. Une signature seule suffit ici
    car le contenu n'est jamais interprété côté serveur ni servi sans en-têtes de
    protection (nosniff, sandbox, attachment hors affichables)."""
    if b"%PDF-" in contenu[:1024]:
        return PDF
    if contenu.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if contenu.startswith(b"\xff\xd8\xff"):
        return JPEG
    if len(contenu) >= 12 and contenu[:4] == b"RIFF" and contenu[8:12] == b"WEBP":
        return WEBP
    return None


def nom_de_base(nom: str | None) -> str:
    """Réduit un nom fourni par le client à son nom de base (sans chemin, sans `..`).

    Le nom n'est jamais utilisé pour le stockage (la référence est générée par le
    serveur) ; il ne sert qu'à l'affichage. Les séparateurs Windows sont aussi
    retirés, car `basename` POSIX ne les reconnaît pas."""
    base = os.path.basename((nom or "").replace("\\", "/")).strip()
    base = base.replace("..", "_")[:255]
    return base or "fichier"
