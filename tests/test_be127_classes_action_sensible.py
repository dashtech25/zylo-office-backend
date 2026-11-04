"""BE-127 : registre des classes d'action sensible (fiche standard, lecture seule).

Tests écrits d'après la définition `### BE-127` de
implementation-backend/tasks-administration-interventions.md, avant le code.

Route visée (décision : préfixe `/api/v1/admin`) :
- `GET /api/v1/admin/sensitive-action-classes` (liste des huit classes).

Couverture :
- CA-1 (schéma) : chaque classe expose les huit classes de la définition et,
  pour chacune, les onze champs de la fiche standard
  (02-autorites-actions-et-controles.md#4) ;
- CA-2 (refus de droit) : un compte hors allowlist d'exploitation (agent L1)
  reçoit 403 ;
- CA-3 : une classe à double validation, commandée sans approbateur, renvoie
  409 `approval_required` (règle testée sur la fonction de garde, car BE-127
  ne crée aucune commande) ;
- CA-4 : aucune route d'écriture sur le registre : POST, PUT, PATCH, DELETE
  renvoient 405.

Hypothèse de lecture : la définition prévoit « auditeur et administrateur
global ». Aucun rôle auditeur plateforme n'existe encore (BE-121) : la lecture
est donc réservée à l'autorité plateforme actuelle (`require_operator`).
"""

import uuid

import pytest
from httpx import AsyncClient

from app.core.errors import AppError
from app.operator.sensitive_classes import CLASSES, exiger_approbation

CHEMIN = "/api/v1/admin/sensitive-action-classes"

# Les huit classes de la définition (liste candidate, sans droit accordé).
CODES_ATTENDUS = {
    "tenant.suspension",
    "entitlement.module",
    "facturation.operation",
    "role.adhesion",
    "donnees.export_suppression_restauration",
    "acces.contenu_exceptionnel",
    "evenement.replay",
    "configuration.modification",
}

# Les onze champs de la fiche standard, écrits à partir de la définition.
CHAMPS_FICHE_ATTENDUS = {
    "autorite", "cible", "motif", "previsualisation", "limite", "confirmation",
    "execution", "echec_reprise", "notification", "audit", "revue",
}


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


async def _autoriser(client: AsyncClient, utilisateur: dict, monkeypatch, autorise: bool = True) -> None:
    """Place l'utilisateur dans l'allowlist d'exploitation (`autorise`) ou un autre identifiant seulement."""
    me = await client.get("/api/v1/auth/me", headers=_entetes(utilisateur))
    user_id = me.json()["id"]
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", user_id if autorise else str(uuid.uuid4()))


async def test_be127_ca1_registre_expose_huit_classes_avec_fiche_standard(
    client: AsyncClient, registered_user: dict, monkeypatch,
):
    await _autoriser(client, registered_user, monkeypatch, autorise=True)

    reponse = await client.get(CHEMIN, headers=_entetes(registered_user))

    assert reponse.status_code == 200
    classes = reponse.json()
    assert {c["code"] for c in classes} == CODES_ATTENDUS
    for classe in classes:
        assert isinstance(classe["requiresDoubleValidation"], bool), classe["code"]
        assert isinstance(classe["requiresReauth"], bool), classe["code"]
        assert "approvalWindow" in classe, classe["code"]
        assert "reversible" in classe, classe["code"]
        assert isinstance(classe["risk_note"], str) and classe["risk_note"], classe["code"]
        assert set(classe["fiche"]) == CHAMPS_FICHE_ATTENDUS, classe["code"]
        for champ, valeur in classe["fiche"].items():
            assert isinstance(valeur, str) and valeur, (classe["code"], champ)


async def test_be127_ca2_agent_l1_hors_allowlist_recoit_403(
    client: AsyncClient, registered_user: dict, monkeypatch,
):
    await _autoriser(client, registered_user, monkeypatch, autorise=False)

    reponse = await client.get(CHEMIN, headers=_entetes(registered_user))

    assert reponse.status_code == 403
    assert reponse.json()["error"]["code"] == "operator_access_denied"


@pytest.mark.parametrize(
    "classe",
    [c for c in CLASSES if c.requiresDoubleValidation],
    ids=lambda c: c.code,
)
def test_be127_ca3_double_validation_sans_approbateur_renvoie_409(classe):
    with pytest.raises(AppError) as erreur:
        exiger_approbation(classe, approbateur_id=None)

    assert erreur.value.status_code == 409
    assert erreur.value.code == "approval_required"


def test_be127_ca3_double_validation_avec_approbateur_passe():
    classe = next(c for c in CLASSES if c.requiresDoubleValidation)

    exiger_approbation(classe, approbateur_id=uuid.uuid4())


@pytest.mark.parametrize("methode", ["post", "put", "patch", "delete"])
async def test_be127_ca4_aucune_ecriture_sur_le_registre(
    client: AsyncClient, registered_user: dict, monkeypatch, methode: str,
):
    await _autoriser(client, registered_user, monkeypatch, autorise=True)

    reponse = await client.request(methode.upper(), CHEMIN, headers=_entetes(registered_user), json={})

    assert reponse.status_code == 405
