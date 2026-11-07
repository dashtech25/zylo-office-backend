"""BE-215 : compatibilité et versionnement des contrats (API et événements).

Tests écrits d'après `### BE-215` de implementation-backend/tasks-donnees-api-contrats.md,
avant le code. Recommandations appliquées pour les points NON DÉFINI : N et N-1 acceptés
jusqu'à décision explicite de retrait (QE-API-23) ; droit de lecture `platform.catalog.manage`
(QE-API-27), 403 sans droit.

Couverture :
- CA-1 : un changement additif (champ optionnel ajouté) passe sans nouveau major ;
- CA-2 : un changement cassant sans nouveau major est refusé, et rien n'est écrit ; un nouveau
  major porteur du même changement est accepté ;
- CA-3 : les versions N et N-1 sont toutes deux acceptées pendant la coexistence ;
- CA-4 : un consommateur N-1 reçoit un champ inconnu sans erreur ;
- CA-5 : une version dépréciée n'est plus sélectionnable pour une nouvelle souscription ;
- route `GET /api/v1/contracts/{contract_name}/versions` : 403 sans droit plateforme, liste avec droit.

Chaque test utilise un nom de contrat unique : le registre persiste dans la base de test.
"""

import uuid

import pytest
from sqlalchemy import select

from app.contrats.compatibilite import changements_cassants, valider_payload
from app.contrats.models import ContractVersion
from app.contrats.service import (
    choisir_version_souscription,
    deprecier_version,
    enregistrer_version,
    modifier_schema_version,
    versions_acceptees,
)
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import User

VARIABLE_DROIT = "PLATFORM_CATALOG_MANAGE_USER_IDS"


def _nom_unique() -> str:
    return f"be215.contrat.{uuid.uuid4().hex[:10]}"


def _schema_v1() -> dict:
    return {
        "type": "object",
        "properties": {"id": {"type": "string"}, "nom": {"type": "string"}},
        "required": ["id"],
    }


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _lire_schema(contrat: str, version: int) -> dict:
    async with AsyncSessionLocal() as db:
        ligne = (
            await db.execute(select(ContractVersion).where(ContractVersion.contractName == contrat, ContractVersion.version == version))
        ).scalar_one()
        return ligne.schemaJson


# ---------------------------------------------------------------------------
# Compatibilité pure (sans base) : règles de changement.
# ---------------------------------------------------------------------------


def test_changement_additif_ne_produit_aucun_changement_cassant():
    nouveau = {**_schema_v1(), "properties": {**_schema_v1()["properties"], "couleur": {"type": "string"}}}

    assert changements_cassants(_schema_v1(), nouveau) == []


@pytest.mark.parametrize(
    "nouveau",
    [
        {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        {"type": "object", "properties": {"id": {"type": "integer"}, "nom": {"type": "string"}}, "required": ["id"]},
        {"type": "object", "properties": {"id": {"type": "string"}, "nom": {"type": "string"}}, "required": ["id", "nom"]},
    ],
    ids=["retrait_de_champ", "changement_de_type", "champ_devenu_requis"],
)
def test_changement_cassant_detecte(nouveau):
    assert changements_cassants(_schema_v1(), nouveau) != []


def test_consommateur_n_moins_1_accepte_un_champ_inconnu():
    """CA-4 : le champ `couleur`, ajouté en N, n'est pas une erreur pour un consommateur N-1."""
    payload_n = {"id": "a1", "nom": "Quai", "couleur": "bleu"}

    assert valider_payload(_schema_v1(), payload_n) == []


def test_consommateur_detecte_un_champ_requis_absent():
    assert valider_payload(_schema_v1(), {"nom": "Quai"}) != []


# ---------------------------------------------------------------------------
# Registre (base de test).
# ---------------------------------------------------------------------------


async def test_ca1_changement_additif_passe_sans_nouveau_major():
    contrat = _nom_unique()
    async with AsyncSessionLocal() as db:
        await enregistrer_version(db, contract_name=contrat, version=1, schema=_schema_v1())
        await db.commit()

    schema_additif = {**_schema_v1(), "properties": {**_schema_v1()["properties"], "couleur": {"type": "string"}}}
    async with AsyncSessionLocal() as db:
        await modifier_schema_version(db, contract_name=contrat, version=1, nouveau_schema=schema_additif)
        await db.commit()

    assert "couleur" in (await _lire_schema(contrat, 1))["properties"]


@pytest.mark.parametrize(
    "nouveau",
    [
        {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        {"type": "object", "properties": {"id": {"type": "integer"}, "nom": {"type": "string"}}, "required": ["id"]},
    ],
    ids=["retrait_de_champ", "changement_de_type"],
)
async def test_ca2_changement_cassant_sans_nouveau_major_refuse(nouveau):
    contrat = _nom_unique()
    async with AsyncSessionLocal() as db:
        await enregistrer_version(db, contract_name=contrat, version=1, schema=_schema_v1())
        await db.commit()

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await modifier_schema_version(db, contract_name=contrat, version=1, nouveau_schema=nouveau)
        assert erreur.value.status_code == 422
        assert erreur.value.code == "CONTRACT_BREAKING_CHANGE"

    assert await _lire_schema(contrat, 1) == _schema_v1()


async def test_ca2_meme_changement_accepte_avec_nouveau_major():
    contrat = _nom_unique()
    nouveau = {"type": "object", "properties": {"id": {"type": "integer"}, "nom": {"type": "string"}}, "required": ["id"]}
    async with AsyncSessionLocal() as db:
        await enregistrer_version(db, contract_name=contrat, version=1, schema=_schema_v1())
        await enregistrer_version(db, contract_name=contrat, version=2, schema=nouveau)
        await db.commit()

    assert await _lire_schema(contrat, 2) == nouveau


async def test_ca3_versions_n_et_n_moins_1_toutes_deux_acceptees():
    contrat = _nom_unique()
    async with AsyncSessionLocal() as db:
        await enregistrer_version(db, contract_name=contrat, version=1, schema=_schema_v1())
        await enregistrer_version(db, contract_name=contrat, version=2, schema=_schema_v1())
        await deprecier_version(db, contract_name=contrat, version=1)
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert await versions_acceptees(db, contract_name=contrat) == [1, 2]


async def test_ca5_version_deprecie_non_selectionnable_pour_souscription():
    contrat = _nom_unique()
    async with AsyncSessionLocal() as db:
        await enregistrer_version(db, contract_name=contrat, version=1, schema=_schema_v1())
        await enregistrer_version(db, contract_name=contrat, version=2, schema=_schema_v1())
        await deprecier_version(db, contract_name=contrat, version=1)
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert await choisir_version_souscription(db, contract_name=contrat) == 2
        with pytest.raises(AppError) as erreur:
            await choisir_version_souscription(db, contract_name=contrat, version=1)
        assert erreur.value.status_code == 422
        assert erreur.value.code == "CONTRACT_VERSION_NOT_SELECTABLE"


# ---------------------------------------------------------------------------
# Route GET /api/v1/contracts/{contract_name}/versions (droit plateforme, 403 sinon).
# ---------------------------------------------------------------------------


def _entetes(registered_user: dict) -> dict:
    return {"Authorization": f"Bearer {registered_user['accessToken']}"}


async def test_route_sans_droit_plateforme_refusee_403(client, registered_user, monkeypatch):
    contrat = _nom_unique()
    async with AsyncSessionLocal() as db:
        await enregistrer_version(db, contract_name=contrat, version=1, schema=_schema_v1())
        await db.commit()
    monkeypatch.setenv(VARIABLE_DROIT, "")

    res = await client.get(f"/api/v1/contracts/{contrat}/versions", headers=_entetes(registered_user))

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_route_avec_droit_plateforme_liste_les_versions(client, registered_user, monkeypatch):
    contrat = _nom_unique()
    async with AsyncSessionLocal() as db:
        await enregistrer_version(db, contract_name=contrat, version=1, schema=_schema_v1())
        await enregistrer_version(db, contract_name=contrat, version=2, schema=_schema_v1())
        await deprecier_version(db, contract_name=contrat, version=1)
        await db.commit()
    user_id = await _id_utilisateur(registered_user["email"])
    monkeypatch.setenv(VARIABLE_DROIT, str(user_id))

    res = await client.get(f"/api/v1/contracts/{contrat}/versions", headers=_entetes(registered_user))

    assert res.status_code == 200, res.text
    statuts = {entree["version"]: entree["status"] for entree in res.json()}
    assert statuts == {1: "deprecated", 2: "current"}


async def test_route_contrat_inconnu_renvoie_404(client, registered_user, monkeypatch):
    user_id = await _id_utilisateur(registered_user["email"])
    monkeypatch.setenv(VARIABLE_DROIT, str(user_id))

    res = await client.get(f"/api/v1/contracts/{_nom_unique()}/versions", headers=_entetes(registered_user))

    assert res.status_code == 404, res.text
