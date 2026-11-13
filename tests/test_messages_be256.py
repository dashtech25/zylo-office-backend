"""Messages d'erreur et textes localisables (BE-256).

BE-256 ne redéfinit pas l'enveloppe d'erreur (BE-001, BE-220) : elle ajoute une
clé de message par code (`app/core/messages.py`) et une lecture de la locale
depuis la configuration. Ces tests vérifient :

- CA-1 : chaque code de l'enveloppe possède une clé de message dans chaque
  catalogue ; le gestionnaire 422 passe par cette clé ;
- CA-2 : des libellés longs, FR comme EN, ne cassent pas le contrat d'enveloppe ;
- CA-3 : aucune locale n'est codée en dur dans le code ; sans locale configurée
  (NON DÉFINI, QE-EXP-23), le texte de repli est utilisé ; la locale vient de
  la configuration ; une locale invalide ne sort jamais du dossier de catalogues.

Les tests ne touchent pas la base : ils montent une application FastAPI
minimale avec les gestionnaires réels de `app.core.errors`.
"""

import ast
import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import messages
from app.core.config import settings
from app.core.errors import AppError, register_exception_handlers
from pydantic import BaseModel

_CODE_ERREUR_VALIDATION = "validation_error"
_CODE_ERREUR_INTERNE = "internal_error"
_TEXTE_REPLI_VALIDATION = "Les données envoyées sont invalides."
_FICHIERS_CODE = (
    Path(messages.__file__),
    Path(messages.__file__).with_name("errors.py"),
)


class _Formulaire(BaseModel):
    """Formulaire témoin : le champ `age` déclenche une erreur de validation."""

    age: int


def _application_temoin() -> FastAPI:
    """Application minimale avec les gestionnaires réels et trois routes témoins."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/formulaire")
    def _formulaire(formulaire: _Formulaire) -> dict:
        return {"ok": True}

    @app.get("/metier")
    def _metier() -> None:
        raise AppError(code="user_not_found", message="Utilisateur introuvable.", status_code=404)

    @app.get("/interne")
    def _interne() -> None:
        raise RuntimeError("secret-interne-be256")

    return app


def _catalogues_temporaires(tmp_path: Path, monkeypatch, textes: dict[str, dict[str, str]]) -> None:
    """Écrit un catalogue par locale dans `tmp_path` et le substitue au dossier réel."""
    for locale, entrees in textes.items():
        (tmp_path / f"{locale}.json").write_text(json.dumps(entrees, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(messages, "CATALOGUE_DIR", tmp_path)


def _contrat_enveloppe_ok(corps: dict) -> None:
    """Vérifie la forme exacte de l'enveloppe BE-001, sans l'évaluer sur le texte."""
    assert set(corps.keys()) == {"error", "request_id"}
    assert set(corps["error"].keys()) == {"code", "message", "field_errors", "details"}
    assert isinstance(corps["error"]["message"], str)


# --- CA-1 : clé de message par code, et usage par les gestionnaires ----------


def test_cle_message_suit_la_forme_erreur_code():
    """La clé est `erreur.<code>` ; un code hors format est refusé (pas de clé libre)."""
    assert messages.cle_message(_CODE_ERREUR_VALIDATION) == "erreur.validation_error"
    with pytest.raises(ValueError):
        messages.cle_message("Code Invalide")
    with pytest.raises(ValueError):
        messages.cle_message("../etc")


def test_chaque_code_de_l_enveloppe_a_une_cle_dans_chaque_catalogue():
    """CA-1 : tout code de `CODES_ENVELOPPE` a sa clé dans chaque catalogue livré."""
    locales = messages.locales_disponibles()
    assert locales, "aucun catalogue de messages livré"
    for locale in locales:
        catalogue = messages.charger_catalogue(locale)
        for code in messages.CODES_ENVELOPPE:
            assert messages.cle_message(code) in catalogue, f"{code} sans clé dans {locale}"


def test_gestionnaire_422_utilise_la_cle_de_message(tmp_path, monkeypatch):
    """CA-1 : le message 422 vient du catalogue de la locale configurée, pas d'un texte en dur."""
    _catalogues_temporaires(
        tmp_path,
        monkeypatch,
        {"xx": {"erreur.validation_error": "LIBELLE-CATALOGUE-422"}},
    )
    monkeypatch.setattr(settings, "DEFAULT_LOCALE", "xx")
    client = TestClient(_application_temoin(), raise_server_exceptions=False)

    reponse = client.post("/formulaire", json={"age": "pas un nombre"})

    assert reponse.status_code == 422
    assert reponse.json()["error"]["code"] == _CODE_ERREUR_VALIDATION
    assert reponse.json()["error"]["message"] == "LIBELLE-CATALOGUE-422"


# --- CA-2 : libellés longs FR et EN ----------------------------------------


@pytest.mark.parametrize("locale", ["fr", "en"])
def test_libelle_long_ne_casse_pas_le_contrat_d_enveloppe(tmp_path, monkeypatch, locale):
    """CA-2 : un libellé de 900 caractères, accents compris, garde la forme de l'enveloppe."""
    long_libelle = ("Très long libellé d'erreur, réel ou traduit. " * 20)[:900]
    _catalogues_temporaires(
        tmp_path,
        monkeypatch,
        {locale: {"erreur.validation_error": long_libelle, "erreur.internal_error": long_libelle}},
    )
    monkeypatch.setattr(settings, "DEFAULT_LOCALE", locale)
    client = TestClient(_application_temoin(), raise_server_exceptions=False)

    reponse = client.post("/formulaire", json={"age": "x"})

    corps = reponse.json()
    _contrat_enveloppe_ok(corps)
    assert corps["error"]["message"] == long_libelle
    assert corps["error"]["code"] == _CODE_ERREUR_VALIDATION
    assert "age" in corps["error"]["field_errors"]


def test_libelle_long_sur_erreur_metier_garde_le_contrat(tmp_path, monkeypatch):
    """CA-2 : une AppError sans clé dans le catalogue garde son texte ; une clé longue le remplace sans casser la forme."""
    long_libelle = "Libellé métier très long, avec des accents é è à ç. " * 15
    _catalogues_temporaires(
        tmp_path,
        monkeypatch,
        {"en": {"erreur.user_not_found": long_libelle}},
    )
    monkeypatch.setattr(settings, "DEFAULT_LOCALE", "en")
    client = TestClient(_application_temoin(), raise_server_exceptions=False)

    reponse = client.get("/metier")

    assert reponse.status_code == 404
    corps = reponse.json()
    _contrat_enveloppe_ok(corps)
    assert corps["error"]["code"] == "user_not_found"
    assert corps["error"]["message"] == long_libelle


# --- CA-3 : aucune locale codée en dur, locale lue de la configuration -----


def test_aucune_locale_codee_en_dur_dans_le_code():
    """CA-3 : aucune constante de chaîne de `messages.py` ou `errors.py` n'est un code de locale nu.

    Les docstrings sont exclues. Un code de locale nu est une chaîne qui ressemble
    à `fr`, `en` ou `fr-FR` (deux lettres minuscules, région optionnelle en majuscules)."""
    motif = re.compile(r"[a-z]{2}([-_][A-Z]{2})?")
    for fichier in _FICHIERS_CODE:
        arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        docstrings = {
            id(noeud.body[0].value)
            for noeud in ast.walk(arbre)
            if isinstance(noeud, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
            and noeud.body
            and isinstance(noeud.body[0], ast.Expr)
            and isinstance(noeud.body[0].value, ast.Constant)
        }
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str) and id(noeud) not in docstrings:
                assert not motif.fullmatch(noeud.value), f"locale en dur dans {fichier.name} : {noeud.value!r}"


def test_sans_locale_configuree_le_texte_de_repli_est_utilise(monkeypatch):
    """CA-3 : locale NON DÉFINIE (QE-EXP-23) : pas de locale par défaut, le texte de repli reste la réponse."""
    monkeypatch.setattr(settings, "DEFAULT_LOCALE", None)
    assert messages.locale_par_defaut() is None
    assert messages.message_pour(_CODE_ERREUR_VALIDATION, _TEXTE_REPLI_VALIDATION) == _TEXTE_REPLI_VALIDATION

    client = TestClient(_application_temoin(), raise_server_exceptions=False)
    reponse = client.post("/formulaire", json={"age": "x"})
    assert reponse.json()["error"]["message"] == _TEXTE_REPLI_VALIDATION


def test_locale_lue_de_la_configuration(tmp_path, monkeypatch):
    """CA-3 : la locale vient de `settings.DEFAULT_LOCALE`, et seul le catalogue correspondant sert."""
    _catalogues_temporaires(
        tmp_path,
        monkeypatch,
        {
            "fr": {"erreur.validation_error": "Libellé FR"},
            "en": {"erreur.validation_error": "EN label"},
        },
    )
    monkeypatch.setattr(settings, "DEFAULT_LOCALE", "en")
    assert messages.locale_par_defaut() == "en"
    assert messages.message_pour(_CODE_ERREUR_VALIDATION, _TEXTE_REPLI_VALIDATION) == "EN label"


def test_locale_absente_du_catalogue_garde_le_texte_de_repli(tmp_path, monkeypatch):
    """CA-3 : locale configurée sans catalogue, ou clé absente : repli, jamais d'erreur 500."""
    _catalogues_temporaires(tmp_path, monkeypatch, {"fr": {}})
    assert messages.message_pour(_CODE_ERREUR_VALIDATION, _TEXTE_REPLI_VALIDATION, "de") == _TEXTE_REPLI_VALIDATION
    assert messages.message_pour(_CODE_ERREUR_VALIDATION, _TEXTE_REPLI_VALIDATION, "fr") == _TEXTE_REPLI_VALIDATION


@pytest.mark.parametrize("locale_hostile", ["../secret", "fr/../../etc", "fr.json", "", "x" * 40])
def test_locale_invalide_ne_sort_jamais_du_dossier_de_catalogues(tmp_path, monkeypatch, locale_hostile):
    """CA-3 : une locale qui ne respecte pas le format est ignorée : pas de lecture hors dossier."""
    _catalogues_temporaires(tmp_path, monkeypatch, {"fr": {"erreur.validation_error": "Libellé FR"}})
    assert messages.message_pour(_CODE_ERREUR_VALIDATION, _TEXTE_REPLI_VALIDATION, locale_hostile) == _TEXTE_REPLI_VALIDATION
