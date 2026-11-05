"""BE-155 : déclaration et validation des paramètres.

Tests écrits d'après la définition `### BE-155` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : chaque paramètre déclaré a une règle de validation ; un paramètre sans
  règle ne peut pas entrer dans le registre et fait échouer la cohérence ;
- CA-2 : une valeur hors règle est rejetée `422` SCHEMA_INVALID ;
- CA-3 : chaque paramètre déclare son effet ; un paramètre sans effet (ou avec un
  effet hors liste) est refusé ;
- CA-4 (refus) : un paramètre absent du registre est rejeté `422` SCHEMA_INVALID et
  rien n'est créé en base.

Hypothèses de test (points NON DÉFINI de la définition, à confirmer en QE) :
- le code HTTP de SCHEMA_INVALID est pris dans `app/core/erreurs/codes.py` (422),
  conformément à CA-2 de la définition (QE-PAR-01) ;
- les trois valeurs d'effet (`immediat`, `prochain_cycle`, `redemarrage`) sont
  provisoires ; la définition ne les fixe pas (QE-PAR-04).
"""

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.parametres.models import SettingDefinition
from app.parametres.validation import EFFETS_PARAMETRE, REGISTRE, RegistreParametres, RegleValeur


def _registre_avec_exemples() -> RegistreParametres:
    """Registre isolé, rempli avec un paramètre de chaque forme de règle."""
    registre = RegistreParametres()
    registre.declarer("be155.entier_borne", RegleValeur(valueType="entier", minimum=1, maximum=10), "immediat")
    registre.declarer("be155.decimal", RegleValeur(valueType="decimal", minimum=0.0, maximum=1.0), "prochain_cycle")
    registre.declarer("be155.booleen", RegleValeur(valueType="booleen"), "redemarrage")
    registre.declarer("be155.texte", RegleValeur(valueType="texte", longueurMaximum=5), "immediat")
    registre.declarer(
        "be155.enumeration",
        RegleValeur(valueType="enumeration", valeursAdmises=("mensuel", "annuel")),
        "immediat",
    )
    return registre


# CA-1 : une règle est obligatoire à la déclaration, et le registre est cohérent.

def test_be155_ca1_declaration_sans_regle_refusee():
    registre = RegistreParametres()
    with pytest.raises(ValueError):
        registre.declarer("be155.sans_regle", None, "immediat")
    assert "be155.sans_regle" not in registre.cles()


def test_be155_ca1_registre_avec_regles_est_coherent():
    registre = _registre_avec_exemples()
    assert registre.anomalies() == []


def test_be155_ca1_registre_de_production_est_coherent():
    # Le registre réel peut être vide à ce stade ; la cohérence doit tenir quand il l'est.
    for cle in REGISTRE.cles():
        assert isinstance(REGISTRE.regle(cle), RegleValeur), f"règle absente pour {cle}"
    assert REGISTRE.anomalies() == []


# CA-2 : une valeur hors règle est rejetée en SCHEMA_INVALID (422).

@pytest.mark.parametrize(
    ("cle", "valeur_valide", "valeur_invalide"),
    [
        ("be155.entier_borne", 10, 11),
        ("be155.entier_borne", 1, 0),
        ("be155.entier_borne", 5, "5"),
        ("be155.entier_borne", 5, True),
        ("be155.decimal", 0.5, 1.5),
        ("be155.decimal", 0.0, "0.0"),
        ("be155.booleen", True, 1),
        ("be155.texte", "abcde", "abcdef"),
        ("be155.texte", "ab", 12),
        ("be155.enumeration", "mensuel", "hebdo"),
        ("be155.enumeration", "annuel", None),
    ],
)
def test_be155_ca2_valeur_hors_regle_rejetee_en_schema_invalid(cle, valeur_valide, valeur_invalide):
    registre = _registre_avec_exemples()

    assert registre.valider(cle, valeur_valide) == valeur_valide

    with pytest.raises(AppError) as erreur:
        registre.valider(cle, valeur_invalide)
    assert erreur.value.code == "SCHEMA_INVALID"
    assert erreur.value.status_code == 422


# CA-3 : chaque paramètre déclare son effet.

def test_be155_ca3_declaration_sans_effet_refusee():
    registre = RegistreParametres()
    with pytest.raises(ValueError):
        registre.declarer("be155.sans_effet", RegleValeur(valueType="booleen"), None)
    assert "be155.sans_effet" not in registre.cles()


def test_be155_ca3_effet_hors_liste_refuse():
    registre = RegistreParametres()
    with pytest.raises(ValueError):
        registre.declarer("be155.effet_inconnu", RegleValeur(valueType="booleen"), "bientot")
    assert "be155.effet_inconnu" not in registre.cles()


def test_be155_ca3_chaque_parametre_declare_un_effet_connu():
    registre = _registre_avec_exemples()
    for cle in registre.cles():
        assert registre.effet(cle) in EFFETS_PARAMETRE, f"effet non déclaré pour {cle}"


# CA-4 (refus) : un paramètre absent du registre est rejeté et n'est pas créé.

async def test_be155_ca4_parametre_absent_du_registre_rejete_sans_creation():
    registre = _registre_avec_exemples()
    cle_inconnue = "be155.absent_du_registre"

    with pytest.raises(AppError) as erreur:
        registre.valider(cle_inconnue, 3)
    assert erreur.value.code == "SCHEMA_INVALID"
    assert erreur.value.status_code == 422

    async with AsyncSessionLocal() as db:
        nombre = (await db.execute(
            select(func.count()).select_from(SettingDefinition).where(SettingDefinition.key == cle_inconnue)
        )).scalar_one()
    assert nombre == 0, "un paramètre refusé ne doit pas être créé en base"
