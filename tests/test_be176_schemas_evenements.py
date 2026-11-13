"""BE-176 : schémas d'événements versionnés (registre, compatibilité, catalogue admin).

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-parametres-notifications-audit.md,
section BE-176) avant le code. Critères couverts :
- CA-1 : un type d'événement du catalogue sans aucune version de schéma fait échouer la vérification ;
  un catalogue entièrement couvert passe ;
- CA-2 : une version incompatible (champ requis retiré sans rupture déclarée) est refusée à
  l'enregistrement, et rien n'est écrit ;
- CA-3 : `GET /api/v1/admin/evenements/types` sans droit plateforme `evenements.read` renvoie 403
  PERMISSION_DENIED ; avec le droit, il liste les types et leurs versions.

Non couvert ici, à traiter avec l'isolation tenant transverse (CA-4, routes BE-158 à BE-173) : un
seul test rejouant ces routes demande un montage de données multi-tenant qui dépasse ce lot (QE).

Décisions de test :
- le droit plateforme `evenements.read` est accordé par allowlist d'environnement
  (`PLATFORM_EVENEMENTS_READ_USER_IDS`), posée avec `monkeypatch`, sans valeur réelle ;
- chaque test utilise un type d'événement unique : le registre est persistant dans la base de test.
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.evenements.schemas import enregistrer_schema, verifier_couverture
from app.identity.models import User

URL_TYPES = "/api/v1/admin/evenements/types"
VARIABLE_DROIT = "PLATFORM_EVENEMENTS_READ_USER_IDS"


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    from app.core.database import engine

    await engine.dispose()
    yield


def _type_unique() -> str:
    """Type `domaine.action` propre au test (le registre est persistant dans la base de test)."""
    return f"be176.{uuid.uuid4().hex[:10]}.cree"


def _schema(*champs_requis: str) -> dict:
    return {
        "type": "object",
        "required": list(champs_requis),
        "properties": {champ: {"type": "string"} for champ in champs_requis},
    }


def _entetes(registered_user: dict) -> dict:
    return {"Authorization": f"Bearer {registered_user['accessToken']}"}


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _enregistrer(type_evenement: str, version: int, schema: dict, compatible_depuis: int) -> None:
    async with AsyncSessionLocal() as db:
        await enregistrer_schema(
            db,
            eventType=type_evenement,
            schemaVersion=version,
            schemaJson=schema,
            compatibleDepuis=compatible_depuis,
            actif=True,
        )
        await db.commit()


async def test_ca1_type_sans_schema_fait_echouer_la_couverture():
    type_couvert = _type_unique()
    type_sans_schema = _type_unique()
    await _enregistrer(type_couvert, 1, _schema("id"), compatible_depuis=1)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await verifier_couverture(db, [type_couvert, type_sans_schema])
    assert erreur.value.code == "SCHEMA_INVALID"
    assert type_sans_schema in str(erreur.value.message)


async def test_ca1_catalogue_entierement_couvert_passe():
    type_couvert = _type_unique()
    await _enregistrer(type_couvert, 1, _schema("id"), compatible_depuis=1)

    async with AsyncSessionLocal() as db:
        await verifier_couverture(db, [type_couvert])


async def test_ca2_champ_requis_retire_sans_rupture_declaree_est_refuse():
    type_evenement = _type_unique()
    await _enregistrer(type_evenement, 1, _schema("id", "nom"), compatible_depuis=1)

    # Retirer `nom` des champs requis sans déclarer de rupture (compatibleDepuis reste à 1) : refus.
    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_schema(
                db,
                eventType=type_evenement,
                schemaVersion=2,
                schemaJson=_schema("id"),
                compatibleDepuis=1,
                actif=True,
            )
        await db.rollback()
    assert erreur.value.code == "SCHEMA_INVALID"

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError):
            await verifier_couverture(db, [type_evenement], versions_attendues={type_evenement: 2})


async def test_ca2_retrait_de_champ_requis_accepte_avec_rupture_declaree():
    type_evenement = _type_unique()
    await _enregistrer(type_evenement, 1, _schema("id", "nom"), compatible_depuis=1)

    # Même retrait, mais la version 2 déclare une rupture (compatibleDepuis = 2) : accepté.
    await _enregistrer(type_evenement, 2, _schema("id"), compatible_depuis=2)

    async with AsyncSessionLocal() as db:
        await verifier_couverture(db, [type_evenement])


async def test_ca3_sans_droit_plateforme_liste_refusee_403(client, registered_user, monkeypatch):
    monkeypatch.setenv(VARIABLE_DROIT, "")

    res = await client.get(URL_TYPES, headers=_entetes(registered_user))

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_ca3_avec_droit_plateforme_liste_types_et_versions(client, registered_user, monkeypatch):
    type_evenement = _type_unique()
    await _enregistrer(type_evenement, 1, _schema("id"), compatible_depuis=1)
    user_id = await _id_utilisateur(registered_user["email"])
    monkeypatch.setenv(VARIABLE_DROIT, str(user_id))

    res = await client.get(URL_TYPES, headers=_entetes(registered_user))

    assert res.status_code == 200, res.text
    types = {entree["eventType"]: entree for entree in res.json()}
    assert type_evenement in types
    versions = types[type_evenement]["versions"]
    assert [v["schemaVersion"] for v in versions] == [1]
    assert versions[0]["compatibleDepuis"] == 1
