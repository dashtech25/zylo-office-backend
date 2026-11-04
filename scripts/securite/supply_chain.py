#!/usr/bin/env python3
"""Sécurité des dépendances et SBOM (BE-249).

Intention : un seul point d'entrée qui, pour une révision de source donnée, (1) produit un
SBOM CycloneDX lié à l'artefact, puis (2) décide si les dépendances de production passent
l'audit de vulnérabilités. Le pipeline échoue dès qu'une vulnérabilité n'est pas couverte
par une exception datée, ou dès qu'une exception est expirée ou invalide.

Fichiers (dans scripts/securite/) :
  - supply_chain.toml          : configuration. Sources, criticités et délais sont NON DÉFINIS
                                 (QE-EXP-19) : les clés doivent exister, leurs valeurs vides
                                 (ou à 0) signifient « non appliqué », jamais une valeur par défaut
                                 codée ici.
  - exceptions_dependances.toml : exceptions datées ([[exception]]) : id, paquet, version,
                                 motif, responsable, date (ajout), expire (AAAA-MM-JJ).

Règles :
  - Échec fermé : une configuration ou une exception illisible fait échouer le contrôle, sans
    repli silencieux.
  - Une exception couvre une vulnérabilité si l'identifiant, le paquet (nom normalisé) et la
    version exacte correspondent, et si sa date d'expiration n'est pas dépassée (le jour de
    l'expiration inclus).
  - Une exception expirée bloque le pipeline, même s'il n'y a plus de vulnérabilité associée :
    elle doit être retirée ou renouvelée explicitement.
  - Pas de criticité appliquée : tant que la criticité n'est pas définie, toute vulnérabilité
    non couverte bloque.

Usage :
  python3 scripts/securite/supply_chain.py --revision REV --sbom-sortie CHEMIN
      [--artefact NOM] [--requirements requirements.txt] [--audit-json FICHIER]
      [--config FICHIER] [--exceptions FICHIER] [--aujourdhui AAAA-MM-JJ]

Sans --audit-json, l'audit est lancé avec `python -m pip_audit -r <requirements> -f json`
(pip-audit doit être installé, voir requirements-dev.txt). Sa sortie JSON est lue même si
pip-audit signale des vulnérabilités (code de sortie non nul dans ce cas).

Code de sortie : 0 si aucun blocage, 1 sinon. Documentation : docs/securite/supply-chain.md.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

SECURITE_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SECURITE_DIR.parent.parent
CONFIG_PAR_DEFAUT = SECURITE_DIR / "supply_chain.toml"
EXCEPTIONS_PAR_DEFAUT = SECURITE_DIR / "exceptions_dependances.toml"
REQUIREMENTS_PAR_DEFAUT = BACKEND_ROOT / "requirements.txt"

SBOM_FORMAT = "CycloneDX"
SBOM_SPEC_VERSION = "1.5"
CHAMPS_EXCEPTION = ("id", "paquet", "version", "motif", "responsable", "date", "expire")
# Une ligne épinglée : nom, extras optionnels, version exacte (==). Toute autre forme est refusée
# pour que le SBOM ne décrive jamais une dépendance dont la version n'est pas figée.
LIGNE_EPINGLEE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?==([^\s;,]+)$")


class ErreurSupplyChain(Exception):
    """Un contrôle de dépendances ne peut pas être mené : le pipeline échoue."""


class ConfigurationInvalide(ErreurSupplyChain):
    """La configuration est absente, incomplète ou renseigne une valeur non implémentée."""


class ExceptionInvalide(ErreurSupplyChain):
    """Une exception de dépendance est incomplète ou a une date illisible."""


@dataclass(frozen=True)
class ConfigurationSupplyChain:
    """Valeurs lues dans supply_chain.toml. Toutes viennent du fichier.

    sources : bases de vulnérabilités retenues (vide tant que NON DÉFINI). Informatif : le
              contrôle s'appuie sur la sortie d'audit fournie.
    criticite_bloquante : seuil de criticité. Chaîne vide tant que NON DÉFINI ; toute valeur
              non vide est refusée, car pip-audit ne fournit pas la criticité.
    duree_maximale_exception_jours : durée maximale entre l'ajout et l'expiration d'une
              exception. 0 signifie « non borné » tant que NON DÉFINI.
    """

    sources: tuple[str, ...]
    criticite_bloquante: str
    duree_maximale_exception_jours: int


@dataclass(frozen=True)
class ExceptionDependance:
    """Une exception datée, assignée et bornée dans le temps pour une vulnérabilité donnée."""

    id: str
    paquet: str
    version: str
    motif: str
    responsable: str
    date: datetime.date
    expire: datetime.date


def normaliser_nom(nom: str) -> str:
    """Ramène un nom de paquet à la forme PEP 503 (minuscules, séparateurs unifiés)."""
    return re.sub(r"[-_.]+", "-", nom).lower()


def _lit_toml(chemin: Path, erreur) -> dict:
    """Lit un fichier TOML ; une absence ou une erreur de syntaxe lève `erreur`."""
    try:
        return tomllib.loads(Path(chemin).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise erreur(f"fichier absent : {chemin}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise erreur(f"fichier illisible : {chemin} ({exc})") from exc


def charger_configuration(chemin: Path = CONFIG_PAR_DEFAUT) -> ConfigurationSupplyChain:
    """Lit supply_chain.toml et renvoie la configuration validée.

    Lève ConfigurationInvalide si une section ou une clé manque, si le type est incorrect,
    ou si une criticité est renseignée (non implémentée). Aucune valeur par défaut n'est
    appliquée à la place d'une clé absente.
    """
    brut = _lit_toml(chemin, ConfigurationInvalide)

    section = brut.get("sources")
    if not isinstance(section, dict) or not isinstance(section.get("bases"), list):
        raise ConfigurationInvalide("section [sources] ou clé bases absente")

    section = brut.get("criticite")
    if not isinstance(section, dict) or not isinstance(section.get("criticite_bloquante"), str):
        raise ConfigurationInvalide("section [criticite] ou clé criticite_bloquante absente")
    criticite = section["criticite_bloquante"]
    if criticite.strip():
        raise ConfigurationInvalide(
            "criticite_bloquante renseignée alors que pip-audit ne fournit pas la criticité"
        )

    section = brut.get("delais")
    if not isinstance(section, dict) or not isinstance(
        section.get("duree_maximale_exception_jours"), int
    ):
        raise ConfigurationInvalide("section [delais] ou clé duree_maximale_exception_jours absente")
    duree = section["duree_maximale_exception_jours"]
    if duree < 0:
        raise ConfigurationInvalide("duree_maximale_exception_jours ne peut pas être négative")

    return ConfigurationSupplyChain(
        sources=tuple(str(s) for s in brut["sources"]["bases"]),
        criticite_bloquante=criticite,
        duree_maximale_exception_jours=duree,
    )


def charger_exceptions(chemin: Path = EXCEPTIONS_PAR_DEFAUT) -> list[ExceptionDependance]:
    """Lit exceptions_dependances.toml et refuse toute exception incomplète ou mal datée.

    Une exception sans motif, responsable, date d'ajout ou date d'expiration lève
    ExceptionInvalide : elle ne peut pas rester silencieuse dans le dépôt. Une expiration
    antérieure à l'ajout est aussi refusée. L'expiration passée n'est pas traitée ici : elle
    bloque au contrôle (voir evaluer).
    """
    brut = _lit_toml(chemin, ExceptionInvalide)
    exceptions: list[ExceptionDependance] = []
    for index, entree in enumerate(brut.get("exception", [])):
        identifiant = entree.get("id", f"#{index}")
        for champ in CHAMPS_EXCEPTION:
            if not str(entree.get(champ, "")).strip():
                raise ExceptionInvalide(f"exception {identifiant} : champ {champ} absent ou vide")
        try:
            date = datetime.date.fromisoformat(str(entree["date"]))
            expire = datetime.date.fromisoformat(str(entree["expire"]))
        except ValueError as exc:
            raise ExceptionInvalide(f"exception {identifiant} : date invalide ({exc})") from exc
        if expire < date:
            raise ExceptionInvalide(f"exception {identifiant} : expiration antérieure à l'ajout")
        exceptions.append(
            ExceptionDependance(
                id=str(entree["id"]),
                paquet=normaliser_nom(str(entree["paquet"])),
                version=str(entree["version"]),
                motif=str(entree["motif"]),
                responsable=str(entree["responsable"]),
                date=date,
                expire=expire,
            )
        )
    return exceptions


def generer_sbom(requirements: Path, revision: str, artefact: str) -> dict:
    """Produit un SBOM CycloneDX 1.5 pour les dépendances épinglées de requirements.

    Le document porte le nom de l'artefact, la révision de source et l'empreinte SHA-256 du
    fichier requirements, ce qui le lie à l'artefact construit à partir de ce fichier.
    Lève ErreurSupplyChain si une ligne n'est pas épinglée par `==` : un SBOM ne doit pas
    décrire une version qui n'est pas figée.
    """
    contenu = Path(requirements).read_bytes()
    composants = []
    for numero, brute in enumerate(contenu.decode("utf-8").splitlines(), start=1):
        ligne = brute.split(" #")[0].strip()
        if not ligne or ligne.startswith("#"):
            continue
        correspondance = LIGNE_EPINGLEE.match(ligne)
        if not correspondance:
            raise ErreurSupplyChain(f"ligne {numero} non épinglée (==) : {ligne}")
        nom, _extras, version = correspondance.groups()
        nom = normaliser_nom(nom)
        composants.append(
            {
                "type": "library",
                "bom-ref": f"pkg:pypi/{nom}@{version}",
                "name": nom,
                "version": version,
                "purl": f"pkg:pypi/{nom}@{version}",
            }
        )
    return {
        "bomFormat": SBOM_FORMAT,
        "specVersion": SBOM_SPEC_VERSION,
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": artefact,
                "version": revision,
            },
            "properties": [
                {"name": "zylo:revision", "value": revision},
                {
                    "name": "zylo:requirements.sha256",
                    "value": hashlib.sha256(contenu).hexdigest(),
                },
            ],
        },
        "components": composants,
    }


def _charge_audit(payload: str) -> list[tuple[str, str, list[str]]]:
    """Lit la sortie JSON de pip-audit et renvoie (paquet, version, identifiants).

    Lève ErreurSupplyChain si la sortie n'est pas du JSON attendu : un audit illisible
    ne doit jamais passer pour un audit sans vulnérabilité.
    """
    try:
        donnees = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ErreurSupplyChain(f"sortie d'audit illisible : {exc}") from exc
    if not isinstance(donnees, dict) or not isinstance(donnees.get("dependencies"), list):
        raise ErreurSupplyChain("sortie d'audit sans liste 'dependencies'")
    resultats = []
    for dependance in donnees["dependencies"]:
        identifiants = [v.get("id", "") for v in dependance.get("vulns", [])]
        if identifiants:
            resultats.append(
                (dependance.get("name", ""), dependance.get("version", ""), identifiants)
            )
    return resultats


def _exception_valide(exception: ExceptionDependance, config: ConfigurationSupplyChain,
                      aujourdhui: datetime.date) -> bool:
    """Vrai si l'exception n'est ni expirée ni plus longue que la durée maximale configurée."""
    if exception.expire < aujourdhui:
        return False
    duree_maximale = config.duree_maximale_exception_jours
    if duree_maximale and (exception.expire - exception.date).days > duree_maximale:
        return False
    return True


def evaluer(
    vulnerabilites: list[tuple[str, str, list[str]]],
    exceptions: list[ExceptionDependance],
    config: ConfigurationSupplyChain,
    aujourdhui: datetime.date,
) -> list[str]:
    """Renvoie la liste des blocages ; une liste vide signifie que le pipeline passe.

    Bloque : chaque exception expirée, chaque exception dépassant la durée maximale
    configurée, et chaque vulnérabilité qu'aucune exception valide ne couvre.
    """
    blocages: list[str] = []
    for exception in exceptions:
        if exception.expire < aujourdhui:
            blocages.append(
                f"exception expirée : {exception.id} ({exception.paquet} {exception.version}, "
                f"expire le {exception.expire.isoformat()})"
            )
        elif not _exception_valide(exception, config, aujourdhui):
            blocages.append(
                f"exception hors durée maximale : {exception.id} ({exception.paquet} "
                f"{exception.version}, {(exception.expire - exception.date).days} jours)"
            )

    for paquet, version, identifiants in vulnerabilites:
        for identifiant in identifiants:
            couverte = any(
                exception.id == identifiant
                and exception.paquet == normaliser_nom(paquet)
                and exception.version == version
                and _exception_valide(exception, config, aujourdhui)
                for exception in exceptions
            )
            if not couverte:
                blocages.append(f"vulnérabilité non excepte : {identifiant} ({paquet} {version})")
    return blocages


def _lance_pip_audit(requirements: Path) -> str:
    """Lance pip-audit en JSON et renvoie sa sortie standard.

    pip-audit renvoie un code non nul quand il trouve des vulnérabilités : le code de sortie
    n'est donc pas interprété, seule la sortie JSON compte (vérifiée par _charge_audit).
    """
    resultat = subprocess.run(
        [sys.executable, "-m", "pip_audit", "-r", str(requirements), "-f", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if not resultat.stdout.strip():
        raise ErreurSupplyChain(f"pip-audit sans sortie (code {resultat.returncode})")
    return resultat.stdout


def main(argv: list[str] | None = None) -> int:
    """Produit le SBOM, puis contrôle les dépendances. Renvoie 0 si rien ne bloque, 1 sinon.

    Le SBOM est écrit avant le contrôle : il existe même quand l'audit échoue.
    """
    parser = argparse.ArgumentParser(description="Sécurité des dépendances et SBOM (BE-249)")
    parser.add_argument("--revision", required=True, help="identifiant de la révision de source")
    parser.add_argument("--sbom-sortie", required=True, type=Path, help="fichier SBOM à écrire")
    parser.add_argument("--artefact", default="zylo-office-backend", help="nom de l'artefact")
    parser.add_argument("--requirements", type=Path, default=REQUIREMENTS_PAR_DEFAUT)
    parser.add_argument("--audit-json", type=Path, default=None,
                        help="sortie pip-audit -f json déjà produite (sinon pip-audit est lancé)")
    parser.add_argument("--config", type=Path, default=CONFIG_PAR_DEFAUT)
    parser.add_argument("--exceptions", type=Path, default=EXCEPTIONS_PAR_DEFAUT)
    parser.add_argument("--aujourdhui", default=None,
                        help="date de référence AAAA-MM-JJ (par défaut : aujourd'hui)")
    args = parser.parse_args(argv)

    try:
        sbom = generer_sbom(args.requirements, args.revision, args.artefact)
        args.sbom_sortie.parent.mkdir(parents=True, exist_ok=True)
        args.sbom_sortie.write_text(json.dumps(sbom, indent=2, ensure_ascii=False),
                                    encoding="utf-8")

        config = charger_configuration(args.config)
        exceptions = charger_exceptions(args.exceptions)
        if args.audit_json is not None:
            try:
                payload = args.audit_json.read_text(encoding="utf-8")
            except OSError as exc:
                raise ErreurSupplyChain(f"sortie d'audit illisible : {exc}") from exc
        else:
            payload = _lance_pip_audit(args.requirements)
        vulnerabilites = _charge_audit(payload)
        aujourdhui = (datetime.date.fromisoformat(args.aujourdhui)
                      if args.aujourdhui else datetime.date.today())
    except ErreurSupplyChain as erreur:
        print(f"BLOQUANT : {erreur}")
        return 1

    blocages = evaluer(vulnerabilites, exceptions, config, aujourdhui)
    for blocage in blocages:
        print(f"BLOQUANT : {blocage}")
    if blocages:
        return 1
    print(f"supply-chain : aucun blocage (révision {args.revision}, SBOM {args.sbom_sortie})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
