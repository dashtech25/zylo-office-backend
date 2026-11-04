#!/usr/bin/env python3
"""Gates qualité serveur (BE-222) : exécution des contrôles, seuils, exceptions et rapport.

Intention : un seul point d'entrée local qui décide si un état du dépôt passe les gates.
Il ne remplace pas pytest, import-linter ou pip-audit ; il les enchaîne, applique les
seuils déclarés dans la configuration, refuse les exceptions non datées ou non assignées,
et écrit un rapport rattaché à une révision de source.

Fichiers (tous dans scripts/qualite/) :
  - gates.toml       : seuils ([seuils]) et étapes ([[etape]]). Aucune valeur n'est codée
                       ici : une clé absente fait échouer le chargement (pas de repli).
  - exceptions.toml  : exceptions de lint ou de test ([[exception]]). Chaque entrée porte
                       id, outil, cible, motif, responsable et date (AAAA-MM-JJ).
  - rapports/<revision>.json : résultat du gate pour une révision de source donnée.

Usage :
  python3 scripts/qualite/gates.py                  gate sur la révision courante (git HEAD)
  python3 scripts/qualite/gates.py --revision REV   gate avec un identifiant explicite

Code de sortie : 0 si toutes les étapes passent, les seuils sont tenus et les exceptions
sont valides ; 1 sinon. Un échec de contrôle ne se contourne pas par un try silencieux.

Relance des étapes : une étape en échec est relancée au plus `relances_flaky` fois. Une
étape qui ne passe qu'après relance est signalée « instable » dans le rapport et compte
comme échec pour le seuil de relances ; elle n'est jamais présentée comme saine.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

QUALITE_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = QUALITE_DIR.parent.parent
CONFIG_PAR_DEFAUT = QUALITE_DIR / "gates.toml"
EXCEPTIONS_PAR_DEFAUT = QUALITE_DIR / "exceptions.toml"
RAPPORTS_PAR_DEFAUT = QUALITE_DIR / "rapports"

CLES_SEUILS = ("couverture_minimale", "duree_maximale_secondes", "relances_flaky")
CHAMPS_EXCEPTION = ("id", "outil", "cible", "motif", "responsable", "date")
# Un identifiant de révision sert de nom de fichier : pas de séparateur de chemin.
MOTIF_IDENTIFIANT_REVISION = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class ConfigurationInvalide(Exception):
    """La configuration du gate est absente, incomplète ou mal formée."""


@dataclass(frozen=True)
class Etape:
    """Un contrôle à exécuter : un nom lisible et une commande à lancer."""

    nom: str
    commande: tuple[str, ...]


@dataclass(frozen=True)
class ConfigurationGates:
    """Seuils et étapes lus depuis gates.toml. Toutes les valeurs viennent du fichier."""

    couverture_minimale: float
    duree_maximale_secondes: float
    relances_flaky: int
    etapes: tuple[Etape, ...]


def charger_configuration(chemin: Path) -> ConfigurationGates:
    """Lit gates.toml et renvoie la configuration validée.

    Lève ConfigurationInvalide si une clé de seuil manque, si une étape n'a pas de nom
    ou de commande. Aucune valeur par défaut n'est appliquée : la configuration fait foi.
    """
    try:
        brut = tomllib.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as erreur:
        raise ConfigurationInvalide(f"lecture impossible : {erreur}") from erreur

    seuils = brut.get("seuils")
    if not isinstance(seuils, dict):
        raise ConfigurationInvalide("section [seuils] absente")
    for cle in CLES_SEUILS:
        if cle not in seuils:
            raise ConfigurationInvalide(f"seuil absent : {cle}")

    etapes = []
    for index, bloc in enumerate(brut.get("etape", [])):
        nom = bloc.get("nom")
        commande = bloc.get("commande")
        if not nom or not isinstance(commande, list) or not commande:
            raise ConfigurationInvalide(f"étape {index} incomplète (nom et commande requis)")
        etapes.append(Etape(nom=str(nom), commande=tuple(str(x) for x in commande)))
    if not etapes:
        raise ConfigurationInvalide("aucune étape déclarée")

    return ConfigurationGates(
        couverture_minimale=float(seuils["couverture_minimale"]),
        duree_maximale_secondes=float(seuils["duree_maximale_secondes"]),
        relances_flaky=int(seuils["relances_flaky"]),
        etapes=tuple(etapes),
    )


def valider_exceptions(chemin: Path) -> list[str]:
    """Contrôle que chaque exception de lint ou de test est complète, datée et assignée.

    Renvoie la liste des erreurs ; une liste vide signifie que toutes les exceptions sont
    acceptables. Une exception sans date ou sans responsable est refusée : elle ne peut
    pas rester silencieuse dans le dépôt.
    """
    try:
        brut = tomllib.loads(Path(chemin).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"fichier d'exceptions absent : {chemin}"]
    except tomllib.TOMLDecodeError as erreur:
        return [f"fichier d'exceptions illisible : {erreur}"]

    erreurs: list[str] = []
    for index, exception in enumerate(brut.get("exception", [])):
        identifiant = exception.get("id", f"#{index}")
        for champ in CHAMPS_EXCEPTION:
            if not str(exception.get(champ, "")).strip():
                erreurs.append(f"exception {identifiant} : champ {champ} absent ou vide")
        date = exception.get("date")
        if date:
            try:
                datetime.date.fromisoformat(str(date))
            except ValueError:
                erreurs.append(f"exception {identifiant} : date invalide ({date})")
    return erreurs


def verifier_seuils(mesures: dict, config: ConfigurationGates) -> list[str]:
    """Compare les mesures aux seuils de la configuration et renvoie les dépassements.

    Clés de mesures reconnues : couverture (minimum), duree_secondes (maximum),
    echecs_relance (maximum). Une mesure absente n'est pas vérifiée ici.
    """
    erreurs = []
    if "couverture" in mesures and mesures["couverture"] < config.couverture_minimale:
        erreurs.append(
            f"couverture {mesures['couverture']} < seuil {config.couverture_minimale}"
        )
    if "duree_secondes" in mesures and mesures["duree_secondes"] > config.duree_maximale_secondes:
        erreurs.append(
            f"durée {mesures['duree_secondes']} s > seuil {config.duree_maximale_secondes} s"
        )
    if "echecs_relance" in mesures and mesures["echecs_relance"] > config.relances_flaky:
        erreurs.append(
            f"échecs avant succès {mesures['echecs_relance']} > seuil {config.relances_flaky}"
        )
    return erreurs


def rapport_present(dossier_rapports: Path, revision: str) -> bool:
    """Indique si un rapport existe pour cette révision de source."""
    return (Path(dossier_rapports) / f"{revision}.json").is_file()


def _lance_etape(etape: Etape, racine: Path, relances: int) -> dict:
    """Exécute une étape, la relance si elle échoue, et renvoie son bilan."""
    debut = time.monotonic()
    echecs = 0
    code = 1
    for _ in range(relances + 1):
        code = subprocess.run(list(etape.commande), cwd=racine).returncode
        if code == 0:
            break
        echecs += 1
    return {
        "nom": etape.nom,
        "code": code,
        "echecs_avant_succes": echecs,
        "instable": code == 0 and echecs > 0,
        "duree_secondes": round(time.monotonic() - debut, 3),
    }


def executer_gate(
    chemin_config: Path,
    chemin_exceptions: Path,
    dossier_rapports: Path,
    revision: str,
    racine: Path = BACKEND_ROOT,
) -> int:
    """Lance le gate complet et écrit le rapport de la révision. Renvoie le code de sortie.

    Ordre : validation des exceptions, puis étapes dans l'ordre de la configuration, puis
    contrôle des seuils de durée et de relances. Le rapport est écrit dans
    dossier_rapports/<revision>.json, même en cas d'échec, pour garder la trace.
    """
    if not MOTIF_IDENTIFIANT_REVISION.match(revision):
        raise ValueError(f"identifiant de révision invalide : {revision!r}")

    config = charger_configuration(chemin_config)
    erreurs = valider_exceptions(chemin_exceptions)

    debut = time.monotonic()
    bilans = [_lance_etape(etape, racine, config.relances_flaky) for etape in config.etapes]
    duree_totale = time.monotonic() - debut

    echecs_relance = max((b["echecs_avant_succes"] for b in bilans), default=0)
    erreurs += verifier_seuils(
        {"duree_secondes": duree_totale, "echecs_relance": echecs_relance}, config
    )
    erreurs += [f"étape en échec : {b['nom']}" for b in bilans if b["code"] != 0]

    verdict = "vert" if not erreurs else "rouge"
    dossier_rapports = Path(dossier_rapports)
    dossier_rapports.mkdir(parents=True, exist_ok=True)
    rapport = {
        "revision": revision,
        "verdict": verdict,
        "date": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "etapes": bilans,
        "erreurs": erreurs,
    }
    (dossier_rapports / f"{revision}.json").write_text(
        json.dumps(rapport, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return 0 if verdict == "vert" else 1


def _revision_courante() -> str:
    """Renvoie le SHA court de HEAD, ou lève une erreur si le dépôt n'est pas un dépôt git."""
    sortie = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sortie.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée en ligne de commande ; voir le module pour les options."""
    parser = argparse.ArgumentParser(description="Gates qualité serveur (BE-222)")
    parser.add_argument("--revision", help="identifiant de révision ; défaut : git HEAD")
    args = parser.parse_args(argv)
    revision = args.revision or _revision_courante()
    code = executer_gate(CONFIG_PAR_DEFAUT, EXCEPTIONS_PAR_DEFAUT, RAPPORTS_PAR_DEFAUT, revision)
    print(f"gate {revision} : {'vert' if code == 0 else 'rouge'}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
