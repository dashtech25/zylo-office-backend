"""BE-250 : artefact versionné, provenance et promotion.

Périmètre fixé par implementation-backend/tasks-exploitation-architecture.md (section BE-250) :
  - CA-1 : le même hash d'artefact est promu entre environnements ;
  - CA-2 : une promotion sans gate réussi est refusée ;
  - CA-3 : le rollback identifie la release antérieure et la configuration compatible ;
  - CA-4 : une promotion sans droit donne 403 (test de refus).

Aucune route HTTP n'est livrée par BE-250 : les tests appellent le service directement,
avec une base de test réelle (table `release_records`, migrée par la session de test).
Chaque test utilise des versions et des environnements uniques (uuid), donc aucun test
ne dépend de l'ordre d'exécution ni des lignes laissées par un autre.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.release import service
from app.release.models import ReleaseRecord
from app.release.permissions import PERMISSION_PROMOTION

GATES_REQUIS = ("G1", "G2")
GATES_REUSSIS = {"G1": "reussi", "G2": "reussi"}
HASH_ARTEFACT = "a" * 64


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    await engine.dispose()
    yield
    await engine.dispose()


def _nom(prefixe: str) -> str:
    return f"{prefixe}-{uuid.uuid4().hex[:12]}"


async def _enregistrer_validation(version: str, gates: dict, config_version: int = 1, hash_artefact: str = HASH_ARTEFACT) -> uuid.UUID:
    """Crée la release de validation (source de la promotion) et renvoie son identifiant."""
    async with AsyncSessionLocal() as db:
        release = await service.enregistrer_release(
            db,
            version=version,
            hash_artefact=hash_artefact,
            reference_source="git:be-250-lot",
            sbom_reference="sbom/cyclonedx-test.json",
            config_version=config_version,
            resultats_gates=gates,
            demandeur_id=uuid.uuid4(),
            environnement=_nom("validation"),
        )
        await db.commit()
        return release.id


async def _promouvoir(source_id, environnement, *, gates=GATES_REUSSIS, demandeur=None, approbateur=None, permissions=None):
    """Promeut une release vers un environnement avec un droit explicite par défaut."""
    demandeur = demandeur or uuid.uuid4()
    approbateur = approbateur or uuid.uuid4()
    permissions = frozenset({PERMISSION_PROMOTION}) if permissions is None else permissions
    async with AsyncSessionLocal() as db:
        release = await service.promouvoir_release(
            db,
            source_id=source_id,
            environnement_cible=environnement,
            demandeur_id=demandeur,
            approbateur_id=approbateur,
            permissions_approbateur=permissions,
            gates_requis=GATES_REQUIS,
            resultats_gates_courants=gates,
        )
        await db.commit()
        return release


async def _compter_releases(environnement: str) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(func.count()).select_from(ReleaseRecord).where(ReleaseRecord.environnement == environnement)
        )).scalar_one()


# CA-1 : même hash d'artefact entre environnements.
async def test_ca1_meme_hash_promu_entre_environnements():
    version = _nom("v")
    source_id = await _enregistrer_validation(version, GATES_REUSSIS)
    recette = _nom("recette")
    production = _nom("production")

    promue_recette = await _promouvoir(source_id, recette)
    promue_production = await _promouvoir(promue_recette.id, production)

    async with AsyncSessionLocal() as db:
        source = await db.get(ReleaseRecord, source_id)
    assert promue_recette.hash_artefact == source.hash_artefact == HASH_ARTEFACT
    assert promue_production.hash_artefact == HASH_ARTEFACT
    assert promue_production.version == version
    assert promue_production.environnement == production
    assert promue_production.reference_source == source.reference_source


# CA-2 : promotion sans gate réussi refusée.
@pytest.mark.parametrize(
    "gates",
    [
        {},
        {"G1": "reussi"},
        {"G1": "reussi", "G2": "echoue"},
        {"G1": "reussi", "G2": "en_cours"},
    ],
    ids=["aucun_gate", "gate_manquant", "gate_echoue", "gate_en_cours"],
)
async def test_ca2_promotion_sans_gate_reussi_refusee(gates):
    source_id = await _enregistrer_validation(_nom("v"), gates)
    environnement = _nom("production")

    with pytest.raises(AppError) as erreur:
        await _promouvoir(source_id, environnement, gates=gates)

    assert erreur.value.status_code == 409
    assert await _compter_releases(environnement) == 0


# CA-3 : le rollback identifie la release antérieure et la configuration compatible.
async def test_ca3_rollback_identifie_release_anterieure_compatible():
    environnement = _nom("production")
    v_ancienne = _nom("v")
    v_courante = _nom("v")
    source_ancienne = await _enregistrer_validation(v_ancienne, GATES_REUSSIS, config_version=1)
    source_courante = await _enregistrer_validation(v_courante, GATES_REUSSIS, config_version=2)
    await _promouvoir(source_ancienne, environnement)
    await _promouvoir(source_courante, environnement)

    async with AsyncSessionLocal() as db:
        cible = await service.identifier_rollback(
            db,
            environnement=environnement,
            version_courante=v_courante,
            config_version_supportee=2,
        )

    assert cible is not None
    assert cible.version == v_ancienne
    assert cible.config_version == 1


async def test_ca3_rollback_ecarte_release_dont_la_configuration_est_incompatible():
    environnement = _nom("production")
    v_ancienne = _nom("v")
    v_courante = _nom("v")
    source_ancienne = await _enregistrer_validation(v_ancienne, GATES_REUSSIS, config_version=3)
    source_courante = await _enregistrer_validation(v_courante, GATES_REUSSIS, config_version=2)
    await _promouvoir(source_ancienne, environnement)
    await _promouvoir(source_courante, environnement)

    async with AsyncSessionLocal() as db:
        cible = await service.identifier_rollback(
            db,
            environnement=environnement,
            version_courante=v_courante,
            config_version_supportee=2,
        )

    assert cible is None


# CA-4 : promotion sans droit donne 403, et n'écrit rien.
async def test_ca4_promotion_sans_droit_donne_403():
    source_id = await _enregistrer_validation(_nom("v"), GATES_REUSSIS)
    environnement = _nom("production")

    with pytest.raises(AppError) as erreur:
        await _promouvoir(source_id, environnement, permissions=frozenset({"zylo.autre.permission"}))

    assert erreur.value.status_code == 403
    assert await _compter_releases(environnement) == 0


async def test_ca4_approbation_par_le_demandeur_donne_403():
    """Approbation distincte : celui qui demande la promotion ne peut pas l'approuver."""
    source_id = await _enregistrer_validation(_nom("v"), GATES_REUSSIS)
    environnement = _nom("production")
    meme_personne = uuid.uuid4()

    with pytest.raises(AppError) as erreur:
        await _promouvoir(source_id, environnement, demandeur=meme_personne, approbateur=meme_personne)

    assert erreur.value.status_code == 403
    assert await _compter_releases(environnement) == 0
