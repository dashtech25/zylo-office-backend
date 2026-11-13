"""BE-151 : catalogue des codes d'erreur et format de reprise.

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-parametres-notifications-audit.md,
section BE-151) avant le code. Critères couverts :
- CA-1 : les 12 codes existent et sont stables (non-régression sur la liste littérale) ;
- CA-2 : un résultat de reprise contient code, classification, corrélation, horodatage, action
  permise, permission et issue idempotente ; un champ manquant fait échouer la validation ;
- CA-3 (refus) : un texte détaillé ou un secret n'atteint ni le message ni les détails de la réponse ;
- CA-4 : un code hors catalogue est rejeté à la construction de l'erreur ;
- mapping HTTP recommandé (QE-PAR-01) pour les codes que la définition précise.

Ces tests ne lisent pas la base : le conftest applique les migrations de session, mais aucun
test ici n'ouvre de session.
"""

import uuid

import pytest
from pydantic import ValidationError

from app.core.erreurs.codes import FICHES, Classification, CodeErreur, ErreurCatalogue
from app.core.erreurs.reprise import ResultatReprise, resultat_reprise

CODES_ATTENDUS = (
    "SCHEMA_INVALID",
    "TENANT_MISMATCH",
    "PERMISSION_DENIED",
    "SIGNATURE_INVALID",
    "REPLAY_DUPLICATE",
    "CONSENT_SUPPRESSED",
    "CHANNEL_UNAVAILABLE",
    "REMOTE_UNAVAILABLE",
    "RATE_LIMITED",
    "SECRET_EXPIRED",
    "VERSION_CONFLICT",
    "AUDIT_WRITE_FAILED",
)

# QE-PAR-01 : mapping HTTP recommandé, codes précisés par la définition.
STATUTS_DEFINIS = {
    "PERMISSION_DENIED": 403,
    "TENANT_MISMATCH": 404,
    "VERSION_CONFLICT": 409,
    "SCHEMA_INVALID": 422,
    "RATE_LIMITED": 429,
    "CHANNEL_UNAVAILABLE": 503,
    "REMOTE_UNAVAILABLE": 503,
}

CHAMPS_REPRISE = (
    "code",
    "classification",
    "correlationId",
    "horodatage",
    "actionPermise",
    "permission",
    "issueIdempotente",
)

SECRET_FACTICE = "motdepasse-factice-be151-7f3a"


def test_ca1_les_douze_codes_existent_et_sont_stables():
    """CA-1 : la liste des codes correspond exactement à la définition (ni ajout, ni renommage)."""
    assert tuple(code.value for code in CodeErreur) == CODES_ATTENDUS
    assert set(FICHES) == set(CodeErreur)


def test_ca1_chaque_code_a_une_fiche_complete():
    """CA-1 : chaque code porte un statut HTTP entier, une classification et une action permise."""
    for code in CodeErreur:
        fiche = FICHES[code]
        assert isinstance(fiche.http_status, int) and 400 <= fiche.http_status <= 599, code
        assert isinstance(fiche.classification, Classification), code
        assert fiche.action_permise.strip(), code


@pytest.mark.parametrize("code, statut", sorted(STATUTS_DEFINIS.items()))
def test_mapping_http_defini_par_la_definition(code: str, statut: int):
    """Statuts précisés par QE-PAR-01 : une dérive du mapping fait échouer le test."""
    assert FICHES[CodeErreur(code)].http_status == statut


def test_ca2_resultat_de_reprise_contient_les_sept_champs():
    """CA-2 : le résultat de reprise porte exactement les sept champs du contrat."""
    resultat = resultat_reprise(CodeErreur.RATE_LIMITED, correlation_id=str(uuid.uuid4()))
    assert tuple(resultat.model_dump().keys()) == CHAMPS_REPRISE


@pytest.mark.parametrize("champ", CHAMPS_REPRISE)
def test_ca2_un_champ_manquant_fait_echouer_la_validation(champ: str):
    """CA-2 : chaque champ est obligatoire ; son absence fait échouer la validation."""
    donnees = resultat_reprise(CodeErreur.CHANNEL_UNAVAILABLE, correlation_id="corr-151").model_dump()
    del donnees[champ]
    with pytest.raises(ValidationError):
        ResultatReprise.model_validate(donnees)


def test_ca2_classification_et_action_viennent_de_la_fiche():
    """CA-2 : la reprise reprend la classification et l'action de la fiche du code, sans les recopier à la main."""
    for code in CodeErreur:
        resultat = resultat_reprise(code, correlation_id="corr-151")
        fiche = FICHES[code]
        assert resultat.code == code
        assert resultat.classification == fiche.classification
        assert resultat.actionPermise == fiche.action_permise
        assert resultat.permission == fiche.permission
        assert resultat.issueIdempotente == fiche.issue_idempotente


def test_ca2_horodatage_en_utc_et_correlation_conservee():
    """CA-2 : l'horodatage est aware (UTC) et la corrélation est recopiée telle quelle."""
    resultat = resultat_reprise(CodeErreur.REMOTE_UNAVAILABLE, correlation_id="corr-abc")
    assert resultat.correlationId == "corr-abc"
    assert resultat.horodatage.utcoffset() is not None
    assert resultat.horodatage.utcoffset().total_seconds() == 0


def test_ca3_secret_et_detail_absents_de_la_reponse_d_erreur():
    """CA-3 : un détail contenant un secret factice n'apparaît ni dans le message, ni dans les détails."""
    erreur = ErreurCatalogue(
        CodeErreur.SIGNATURE_INVALID,
        detail=f"signature rejetée, jeton={SECRET_FACTICE}",
    )
    assert SECRET_FACTICE not in erreur.message
    assert SECRET_FACTICE not in str(erreur.details)
    assert SECRET_FACTICE not in str(erreur.field_errors)
    assert erreur.message == FICHES[CodeErreur.SIGNATURE_INVALID].message
    assert erreur.details == []
    assert erreur.field_errors == {}


def test_ca3_code_et_statut_repris_de_la_fiche():
    """Une ErreurCatalogue porte le code stable et le statut HTTP de sa fiche (enveloppe BE-001)."""
    erreur = ErreurCatalogue(CodeErreur.VERSION_CONFLICT)
    assert erreur.code == "VERSION_CONFLICT"
    assert erreur.status_code == 409


@pytest.mark.parametrize("code_libre", ["CODE_INCONNU", "validation_error", "webhook_eventId_missing", ""])
def test_ca4_code_hors_catalogue_rejete_a_la_construction(code_libre: str):
    """CA-4 : un code hors liste (y compris un code libre de BE-001) est refusé dès la construction."""
    with pytest.raises(ValueError):
        ErreurCatalogue(code_libre)


def test_ca4_chaque_code_du_catalogue_est_accepte_en_texte():
    """CA-4 : un code écrit en texte exact du catalogue est accepté et résolu vers sa fiche."""
    for code in CodeErreur:
        erreur = ErreurCatalogue(code.value)
        assert erreur.code == code.value


def test_classifications_permanente_et_temporaire_presentes():
    """La classification est binaire : temporaire ou permanente, les deux sont utilisées."""
    valeurs = {fiche.classification for fiche in FICHES.values()}
    assert valeurs == {Classification.TEMPORAIRE, Classification.PERMANENTE}
