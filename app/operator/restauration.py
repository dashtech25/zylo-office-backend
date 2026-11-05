"""Sauvegarde et restauration de la base (preuve BE-175).

Ce module ne fait que relier les scripts existants `scripts/backup.sh` et
`scripts/restore.sh` aux règles de l'application :

- la sauvegarde ne demande aucun droit particulier : elle produit un dump gzip
  complet, dans un dossier donné, en réutilisant la configuration de connexion
  de `DATABASE_URL` ;
- la restauration est une opération d'exploitation. Elle n'est accessible qu'au
  compte présent dans l'allowlist opérateur (`assert_operator_user`, 403 sinon),
  et elle refuse de cibler la base source : un dump restauré sur la base en
  service écraserait les paramètres et le journal d'audit en place.

Aucune route HTTP n'expose ces fonctions (BE-175 : « Routes : aucune »). Les
scripts restent l'outil réel ; ce module n'en duplique pas la logique.

Limite connue : `restore.sh` n'arrête pas `psql` à la première erreur. Une
restauration partielle n'est donc détectée que par la comparaison des données
(tests BE-175). Restaurer un seul tenant n'est pas implémenté (voir la doc du module).
"""

import os
import subprocess
import uuid
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.errors import AppError
from app.operator.permissions import assert_operator_user

RACINE_BACKEND = Path(__file__).resolve().parents[2]
SCRIPT_SAUVEGARDE = RACINE_BACKEND / "scripts" / "backup.sh"
SCRIPT_RESTAURATION = RACINE_BACKEND / "scripts" / "restore.sh"


def _environnement_connexion() -> dict[str, str]:
    """Variables que lisent les scripts (POSTGRES_USER, POSTGRES_HOST, POSTGRES_DB),
    dérivées de `DATABASE_URL` pour que les scripts visent la même base que l'application.

    Un hôte en socket (`?host=/var/run/postgresql`) est lu dans la requête de l'URL,
    car `make_url` le place là et non dans `host`."""
    url = make_url(os.environ["DATABASE_URL"])
    hote = url.query.get("host")
    if isinstance(hote, tuple):
        hote = hote[0]
    env = dict(os.environ)
    env["POSTGRES_USER"] = url.username or ""
    env["POSTGRES_HOST"] = hote or url.host or "localhost"
    env["POSTGRES_DB"] = url.database or ""
    return env


def sauvegarder_base(dossier: Path) -> Path:
    """Lance `scripts/backup.sh` vers `dossier` et renvoie le fichier produit.

    Le script vérifie lui-même l'intégrité gzip du dump. Le dossier est passé par
    `ZYLO_BACKUP_DIR` pour ne jamais écrire dans `backups/` du dépôt pendant un test.
    """
    env = _environnement_connexion()
    env["ZYLO_BACKUP_DIR"] = str(dossier)
    subprocess.run(["bash", str(SCRIPT_SAUVEGARDE)], env=env, check=True, capture_output=True, text=True)
    fichiers = sorted(dossier.glob("zylo_office_*.sql.gz"))
    if len(fichiers) != 1:
        raise RuntimeError(f"sauvegarde attendue : un seul fichier dans {dossier}, trouvé {len(fichiers)}")
    return fichiers[0]


def restaurer_sauvegarde(actor_user_id: uuid.UUID, fichier: Path, base_cible: str) -> None:
    """Restaure un dump de `sauvegarder_base` sur `base_cible`, base jetable.

    Ordre des contrôles : le droit opérateur d'abord (403 sans rien toucher), puis le
    refus de la base source (422). Seulement ensuite le script est lancé. Le script
    écrase le contenu de la base cible : elle doit être vide ou jetable.
    """
    assert_operator_user(actor_user_id)
    nom_source = make_url(os.environ["DATABASE_URL"]).database
    if base_cible == nom_source:
        raise AppError(
            code="RESTAURATION_BASE_SOURCE",
            message="La restauration ne peut pas viser la base en service.",
            status_code=422,
        )
    subprocess.run(
        ["bash", str(SCRIPT_RESTAURATION), str(fichier), base_cible],
        env=_environnement_connexion(),
        check=True,
        capture_output=True,
        text=True,
    )
