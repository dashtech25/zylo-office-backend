"""Migration des données existantes : chiffrement des mots de passe Holykell (T-027).

Usage (depuis la racine du dépôt backend, venv activé ou .venv/bin/python) :

    python scripts/chiffrer_mots_de_passe_holykell.py --dry-run
    python scripts/chiffrer_mots_de_passe_holykell.py
    python scripts/chiffrer_mots_de_passe_holykell.py --effacer-clair

Intention :
- Idempotent : une ligne déjà chiffrée n'est jamais réécrite ; relancer le script
  ne produit aucune modification supplémentaire.
- --dry-run : compte ce qui serait fait, n'écrit rien (aucune transaction de
  modification n'est validée).
- Vérification avant écriture : chaque valeur chiffrée est déchiffrée et comparée
  au clair ; un écart arrête le script sans écraser la ligne.
- Par défaut, la colonne en clair `holykellPassword` est conservée (retour arrière
  possible). `--effacer-clair` ne la vide qu'après vérification, et seulement pour
  les lignes déjà chiffrées : à lancer après une sauvegarde vérifiée.
- Ne jamais afficher de valeur : seuls des compteurs et des identifiants de ligne
  sortent sur la sortie standard.
- Exige APP_FIELD_ENCRYPTION_KEY valide : sans clé, rien n'est modifié.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from sqlalchemy import select  # noqa: E402

from app.core import field_crypto  # noqa: E402
from app.core.database import AsyncSessionLocal, engine  # noqa: E402

# Mêmes modules importés que alembic/env.py : la configuration des relations doit
# être complète avant la première requête.
from app.alerts import models as _alerts_models  # noqa: F401,E402
from app.auth import models as _auth_models  # noqa: F401,E402
from app.billing import models as _billing_models  # noqa: F401,E402
from app.files import models as _files_models  # noqa: F401,E402
from app.identity import models as _identity_models  # noqa: F401,E402
from app.location import models as _location_models  # noqa: F401,E402
from app.modules.zylo_liquid.models import HolykellAccount  # noqa: E402
from app.modules.zylo_tanker import models as _zylo_tanker_models  # noqa: F401,E402
from app.modules_registry import models as _modules_registry_models  # noqa: F401,E402
from app.rbac import models as _rbac_models  # noqa: F401,E402
from app.shared import geo as _shared_geo_models  # noqa: F401,E402
from app.shared import currency as _shared_currency_models  # noqa: F401,E402


@dataclass
class Rapport:
    examinees: int = 0
    chiffres: int = 0          # valeurs chiffrées (ou qui le seraient en --dry-run)
    deja_chiffres: int = 0     # lignes déjà migrées, laissées telles quelles
    clairs_effaces: int = 0    # colonnes en clair vidées (ou qui le seraient)


async def migrer(session_factory, *, dry_run: bool, effacer_clair: bool, lot: int) -> Rapport:
    """Migre les comptes Holykell par lots de `lot` lignes. Retourne des compteurs uniquement."""
    if lot < 1:
        raise ValueError("la taille de lot doit être au moins 1")
    # Contrôle de la clé avant toute lecture écrite : sans clé utilisable, rien ne change.
    verification = "controle-de-cle"
    if field_crypto.dechiffrer(field_crypto.chiffrer(verification)) != verification:
        raise field_crypto.ChiffrementError("contrôle de la clé de chiffrement échoué.")

    rapport = Rapport()
    dernier_id = None
    while True:
        async with session_factory() as db:
            requete = select(HolykellAccount).order_by(HolykellAccount.id).limit(lot)
            if dernier_id is not None:
                requete = requete.where(HolykellAccount.id > dernier_id)
            lignes = (await db.execute(requete)).scalars().all()
            if not lignes:
                break

            for ligne in lignes:
                rapport.examinees += 1
                dernier_id = ligne.id
                clair = ligne.holykellPassword
                chiffre = ligne.holykellPasswordChiffre

                if chiffre is None:
                    if clair is None:
                        raise field_crypto.ChiffrementError(
                            f"compte {ligne.id} : ni valeur en clair ni valeur chiffrée, migration arrêtée."
                        )
                    nouveau = field_crypto.chiffrer(clair)
                    if field_crypto.dechiffrer(nouveau) != clair:
                        raise field_crypto.ChiffrementError(f"compte {ligne.id} : vérification du chiffrement échouée.")
                    rapport.chiffres += 1
                    if not dry_run:
                        ligne.holykellPasswordChiffre = nouveau
                else:
                    rapport.deja_chiffres += 1
                    if clair is not None and field_crypto.dechiffrer(chiffre) != clair:
                        raise field_crypto.ChiffrementError(
                            f"compte {ligne.id} : la valeur chiffrée ne correspond pas au clair, migration arrêtée."
                        )

                if effacer_clair and clair is not None:
                    rapport.clairs_effaces += 1
                    if not dry_run:
                        ligne.holykellPassword = None

            if not dry_run:
                await db.commit()
    return rapport


def _afficher(rapport: Rapport, dry_run: bool) -> None:
    entete = "Simulation (aucune écriture)" if dry_run else "Migration appliquée"
    print(entete)
    print(f"  comptes examinés      : {rapport.examinees}")
    print(f"  valeurs à chiffrer    : {rapport.chiffres}")
    print(f"  déjà chiffrés         : {rapport.deja_chiffres}")
    print(f"  colonnes en clair vidées : {rapport.clairs_effaces}")


async def _principal(args: argparse.Namespace) -> int:
    try:
        rapport = await migrer(
            AsyncSessionLocal, dry_run=args.dry_run, effacer_clair=args.effacer_clair, lot=args.lot
        )
    except field_crypto.ChiffrementError as exc:
        # Le message ne contient jamais de valeur (voir app/core/field_crypto.py).
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    _afficher(rapport, args.dry_run)
    return 0


def main() -> int:
    parseur = argparse.ArgumentParser(description="Chiffre les mots de passe Holykell existants (T-027).")
    parseur.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    parseur.add_argument("--effacer-clair", action="store_true", help="vide la colonne en clair après vérification")
    parseur.add_argument("--lot", type=int, default=100, help="taille des lots (défaut : 100)")
    return asyncio.run(_principal(parseur.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
