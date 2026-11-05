"""Idempotence des mutations et contrôle de version (BE-183).

BE-183 ne crée aucun mécanisme nouveau : il s'appuie sur ceux de BE-232
(`app/core/idempotency.py`, table `idempotencyKeys`) et de BE-233
(`app/core/versioning.py`, colonne `version`). Ce fichier fixe le contrat de
BE-183 au niveau des fonctions, sur la base réelle :

- CA-1 : même clé et même payload rejouent le résultat initial sans second effet ;
- CA-2 : même clé avec un payload différent renvoie 409, sans effet ;
- CA-3 : `expectedVersion` obsolète renvoie 409 et n'écrit rien ;
- CA-4 : une clé du tenant A ne rejoue jamais le résultat du tenant B ;
- CA-5 : après une panne simulée après commit, le rejeu rend le résultat commis,
  sans second effet.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.core.idempotency import run_idempotent
from app.core.versioning import mutation_versionnee
from app.identity.models import Organization

CHEMIN_COMMANDE = "/test-be183/commande"


def _cle() -> str:
    """Clé conforme aux bornes de l'en-tête (16 à 120 caractères)."""
    return f"be183-{uuid.uuid4().hex}"


async def _executer(cle: str, organisation_id: uuid.UUID, acteur_id: uuid.UUID, charge: dict, produire):
    """Exécute la commande dans une session neuve, comme une requête HTTP distincte."""
    async with AsyncSessionLocal() as db:
        return await run_idempotent(
            db,
            cle=cle,
            organisation_id=organisation_id,
            acteur_id=acteur_id,
            methode="POST",
            chemin=CHEMIN_COMMANDE,
            charge=charge,
            produire=produire,
        )


def _producteur(compteur: list[int]):
    """Effet compté : chaque exécution réelle ajoute une entrée dans `compteur`."""

    async def produire() -> tuple[int, dict]:
        compteur.append(1)
        return 201, {"numero": len(compteur)}

    return produire


async def test_ca1_meme_cle_et_meme_payload_rejouent_sans_second_effet(organization):
    """CA-1 : le second envoi rend le résultat initial et n'exécute pas la commande."""
    compteur: list[int] = []
    cle = _cle()
    organisation_id = uuid.UUID(organization["id"])
    acteur_id = uuid.uuid4()

    premiere = await _executer(cle, organisation_id, acteur_id, {"nom": "A"}, _producteur(compteur))
    seconde = await _executer(cle, organisation_id, acteur_id, {"nom": "A"}, _producteur(compteur))

    assert premiere.rejouee is False
    assert seconde.rejouee is True
    assert (seconde.statut, seconde.corps) == (premiere.statut, premiere.corps)
    assert len(compteur) == 1


async def test_ca2_meme_cle_payload_different_renvoie_409_sans_effet(organization):
    """CA-2 : même clé, autre contenu : 409 `idempotency_key_reused`, aucune exécution."""
    compteur: list[int] = []
    cle = _cle()
    organisation_id = uuid.UUID(organization["id"])
    acteur_id = uuid.uuid4()
    await _executer(cle, organisation_id, acteur_id, {"nom": "A"}, _producteur(compteur))

    with pytest.raises(AppError) as erreur:
        await _executer(cle, organisation_id, acteur_id, {"nom": "B"}, _producteur(compteur))

    assert erreur.value.status_code == 409
    assert erreur.value.code == "idempotency_key_reused"
    assert len(compteur) == 1


async def test_ca3_expected_version_obsolete_renvoie_409_et_n_ecrit_rien(organization):
    """CA-3 : une version obsolète ne modifie ni le nom ni la version ; la version
    courante est renvoyée dans `details` pour que le client se recale."""
    organisation_id = uuid.UUID(organization["id"])
    nom_initial = organization["name"]

    async with AsyncSessionLocal() as db:
        await mutation_versionnee(
            db, Organization, organisation_id, 1, {"name": "Nouveau nom"}, code_introuvable="organisation_introuvable"
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await mutation_versionnee(
                db, Organization, organisation_id, 1, {"name": "Écrasement"}, code_introuvable="organisation_introuvable"
            )
        await db.rollback()

    assert erreur.value.status_code == 409
    assert erreur.value.code == "version_conflict"
    assert erreur.value.details[0]["versionCourante"] == 2

    async with AsyncSessionLocal() as db:
        ligne = await db.scalar(select(Organization).where(Organization.id == organisation_id))
    assert ligne.name == "Nouveau nom"
    assert ligne.version == 2
    assert ligne.name != nom_initial


async def test_ca4_cle_d_un_tenant_ne_rejoue_jamais_le_resultat_d_un_autre(organization):
    """CA-4 : la même clé, pour un autre tenant, n'est pas reconnue : nouvelle exécution."""
    compteur: list[int] = []
    cle = _cle()
    acteur_id = uuid.uuid4()
    tenant_a = uuid.UUID(organization["id"])
    tenant_b = uuid.uuid4()

    resultat_a = await _executer(cle, tenant_a, acteur_id, {"nom": "A"}, _producteur(compteur))
    resultat_b = await _executer(cle, tenant_b, acteur_id, {"nom": "A"}, _producteur(compteur))

    assert resultat_a.rejouee is False
    assert resultat_b.rejouee is False
    assert resultat_b.corps != resultat_a.corps
    assert len(compteur) == 2


async def test_ca5_panne_apres_commit_rejeu_sans_second_effet(organization):
    """CA-5 : la commande est commise, puis la réponse est perdue (exception après
    commit). Le rejeu rend le résultat commis et n'exécute pas de nouveau l'effet."""
    compteur: list[int] = []
    cle = _cle()
    organisation_id = uuid.UUID(organization["id"])
    acteur_id = uuid.uuid4()

    with pytest.raises(ConnectionError):
        async with AsyncSessionLocal() as db:
            await run_idempotent(
                db,
                cle=cle,
                organisation_id=organisation_id,
                acteur_id=acteur_id,
                methode="POST",
                chemin=CHEMIN_COMMANDE,
                charge={"nom": "A"},
                produire=_producteur(compteur),
            )
            raise ConnectionError("réponse perdue après commit")

    rejeu = await _executer(cle, organisation_id, acteur_id, {"nom": "A"}, _producteur(compteur))

    assert rejeu.rejouee is True
    assert rejeu.statut == 201
    assert rejeu.corps == {"numero": 1}
    assert len(compteur) == 1
