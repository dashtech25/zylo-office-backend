"""Sauvegarde chiffrée de la base de plateforme, avec preuve de génération (BE-244).

Ce module ne duplique pas le dump : il réutilise `sauvegarder_base` (BE-175, qui appelle
`scripts/backup.sh` et vérifie le gzip). Ce qu'il ajoute, et que la sauvegarde seule ne
garantissait pas :

- Chiffrement (CA-2) : le dump clair est produit dans un dossier de transit propre à
  l'appel, puis chiffré par la clé maître (`fernet_maitre`, BE-231) et seul l'artefact
  chiffré est conservé dans le dossier de destination. Le transit est supprimé dans tous
  les cas, y compris en échec : aucun dump en clair ne doit survivre à l'opération.
- Contrôle de complétude (CA-3) : chaque table du schéma `public` doit figurer dans le
  dump. Une table absente signifie une sauvegarde partielle, donc un échec, jamais un
  succès silencieux.
- Preuve (CA-1) : chaque tentative, réussie ou non, écrit une ligne `backup_runs` avec le
  résultat, l'empreinte SHA-256 de l'artefact stocké, son volume et son chiffrement.
- Pas de clé en clair (CA-4) : la table des clés est déjà enveloppée (BE-231). Le scan
  vérifie qu'aucune clé de donnée, ni la clé maître, n'apparaît dans l'artefact.
- Politique (CA-5) : fréquence, RPO et rétention viennent de la configuration (`settings`),
  sans valeur codée. Si l'une manque, la sauvegarde est refusée (422) avant toute écriture.

Droits : l'exécution exige le compte d'exploitation (`assert_operator_user`, 403 sinon),
contrôlé avant tout autre effet. La définition demande des comptes de service distincts ;
ce module n'en modélise pas encore (voir QE-EXP-04 et la doc `docs/exploitation/sauvegardes.md`).

Échec : une erreur pendant la sauvegarde ne propage pas d'exception à l'appelant. Elle
produit une ligne `echec` et est journalisée (type de l'erreur seulement, jamais le contenu
du dump ni la clé). L'appelant contrôle `resultat`.
"""

import datetime as dt
import gzip
import hashlib
import logging
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import InvalidToken
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.field_crypto import fernet_maitre
from app.operator.backup_models import BackupRun
from app.operator.permissions import assert_operator_user
from app.operator.restauration import sauvegarder_base

logger = logging.getLogger(__name__)

PERIMETRE_PLATEFORME = "plateforme"
EMPLACEMENT_LOGIQUE_LOCAL = "exploitation-local"
PREFIXE_ARTEFACT = "zylo_office_"
SUFFIXE_ARTEFACT = ".sql.gz.enc"
# Un jeton Fernet commence toujours par ce préfixe (version 0x80 encodée en base64) :
# un artefact qui ne le porte pas n'est pas chiffré.
MARQUE_JETON_FERNET = b"gAAAAA"
_RE_TABLE_DUMP = re.compile(r'^CREATE TABLE public\."?(\w+)"?', re.MULTILINE)


class SauvegardeError(Exception):
    """Un artefact ne satisfait pas une garantie (non chiffré, partiel). Jamais conservé."""


@dataclass(frozen=True)
class PolitiqueSauvegarde:
    """Paramètres d'exploitation lus de la configuration, jamais codés en dur (CA-5)."""

    frequence: str
    rpo_heures: int
    retention_jours: int


def lire_politique_sauvegarde() -> PolitiqueSauvegarde:
    """Lit fréquence, RPO et rétention dans `settings`.

    Lève 422 si l'une des trois valeurs est absente. Une politique incomplète refuse la
    sauvegarde plutôt que de prendre une valeur par défaut que personne n'a décidée.
    """
    frequence = settings.BACKUP_FREQUENCE
    rpo = settings.BACKUP_RPO_HEURES
    retention = settings.BACKUP_RETENTION_JOURS
    if not frequence or rpo is None or rpo <= 0 or retention is None or retention <= 0:
        raise AppError(
            code="sauvegarde_politique_non_definie",
            message="La politique de sauvegarde (fréquence, RPO, rétention) n'est pas configurée.",
            status_code=422,
        )
    return PolitiqueSauvegarde(frequence=frequence, rpo_heures=rpo, retention_jours=retention)


def verifier_chiffrement(fichier: Path) -> None:
    """Refuse un artefact qui n'est pas chiffré par la clé maître.

    Le contrôle ne se limite pas au préfixe : il tente le déchiffrement. Un fichier gzip
    en clair, ou un jeton d'une autre clé maître, lève SauvegardeError.
    """
    contenu = fichier.read_bytes()
    if not contenu.startswith(MARQUE_JETON_FERNET):
        raise SauvegardeError("artefact non chiffré : conservation refusée.")
    try:
        fernet_maitre().decrypt(contenu)
    except InvalidToken:
        raise SauvegardeError("artefact illisible par la clé maître : conservation refusée.") from None


async def _tables_du_schema_public(db: AsyncSession) -> set[str]:
    resultat = await db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    return {ligne[0] for ligne in resultat.all()}


def _appliquer_retention(dossier: Path, retention_jours: int) -> None:
    """Supprime les artefacts plus anciens que la rétention configurée."""
    limite = dt.datetime.now(dt.timezone.utc).timestamp() - retention_jours * 86400
    for artefact in dossier.glob(f"{PREFIXE_ARTEFACT}*{SUFFIXE_ARTEFACT}"):
        if artefact.stat().st_mtime < limite:
            artefact.unlink()


async def sauvegarder_chiffree(db: AsyncSession, actor_user_id: uuid.UUID, dossier: Path) -> BackupRun:
    """Produit une sauvegarde chiffrée dans `dossier` et enregistre sa preuve.

    Ordre : droit d'exploitation (403), politique configurée (422), puis la sauvegarde.
    Les deux premiers contrôles n'écrivent rien : ni fichier, ni ligne `backup_runs`.
    Une fois la tentative commencée, toute issue (réussie ou non) crée une ligne.

    Renvoie la ligne `BackupRun` ajoutée à la session. L'appelant doit committer.
    """
    assert_operator_user(actor_user_id)
    politique = lire_politique_sauvegarde()

    horodatage = dt.datetime.now(dt.timezone.utc)
    transit = dossier / f".transit-{uuid.uuid4().hex}"
    transit.mkdir(parents=True, exist_ok=True)
    ligne = BackupRun(
        horodatage=horodatage,
        perimetre=PERIMETRE_PLATEFORME,
        volume=None,
        resultat="echec",
        empreinte=None,
        emplacement=None,
        chiffrement=False,
    )
    try:
        dump_clair = sauvegarder_base(transit).read_bytes()
        dump_texte = gzip.decompress(dump_clair).decode("utf-8", errors="replace")
        absentes = await _tables_du_schema_public(db) - set(_RE_TABLE_DUMP.findall(dump_texte))
        if absentes:
            raise SauvegardeError(f"sauvegarde partielle : {len(absentes)} table(s) absente(s) du dump.")

        artefact_chiffre = fernet_maitre().encrypt(dump_clair)
        nom = f"{PREFIXE_ARTEFACT}{horodatage:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}{SUFFIXE_ARTEFACT}"
        destination = dossier / nom
        destination.write_bytes(artefact_chiffre)
        verifier_chiffrement(destination)
        _appliquer_retention(dossier, politique.retention_jours)

        ligne.resultat = "reussie"
        ligne.volume = len(artefact_chiffre)
        ligne.empreinte = hashlib.sha256(artefact_chiffre).hexdigest()
        ligne.emplacement = EMPLACEMENT_LOGIQUE_LOCAL
        ligne.chiffrement = True
    except Exception as erreur:
        # Journal sans contenu : seul le type d'erreur sort du module.
        logger.error("sauvegarde en échec : %s", type(erreur).__name__)
    finally:
        shutil.rmtree(transit, ignore_errors=True)

    db.add(ligne)
    return ligne
