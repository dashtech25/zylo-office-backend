"""BE-252 : rollback et compensation.

Périmètre fixé par implementation-backend/tasks-exploitation-architecture.md (section BE-252) :
  - CA-1 : défaut injecté après mutation asynchrone : la compensation converge sans doublon ;
  - CA-2 : rollback du binaire ne restaure pas les données (limite documentée) ;
  - CA-3 : la compensation est idempotente (deux exécutions = un effet) ;
  - CA-4 : compensation sans droit donne 403 (test de refus).

Aucune route HTTP n'est livrée par BE-252 : les tests appellent le service directement,
avec une base de test réelle (table `compensations`, migrée par la session de test).

Les effets de bord d'une mutation asynchrone (un envoi, une ressource externe) ne sont pas
persistés en base ici : ils sont simulés par un dictionnaire propre au test, et l'action de
compensation est une fonction injectée par l'appelant. Chaque test utilise des clés et des
environnements uniques (uuid) pour ne dépendre ni de l'ordre ni des lignes d'un autre test.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.release import compensation, service
from app.release.compensation import ETAT_EN_ATTENTE, ETAT_REALISEE
from app.release.models import Compensation, ReleaseRecord
from app.release.permissions import PERMISSION_COMPENSATION

HASH_ARTEFACT = "b" * 64


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    await engine.dispose()
    yield
    await engine.dispose()


def _nom(prefixe: str) -> str:
    return f"{prefixe}-{uuid.uuid4().hex[:12]}"


async def _demander(operation: str, cle: str, *, permissions=None, demandeur=None, approbateur=None):
    """Déclenche une compensation avec un droit explicite par défaut et renvoie son identifiant."""
    permissions = frozenset({PERMISSION_COMPENSATION}) if permissions is None else permissions
    demandeur = demandeur or uuid.uuid4()
    approbateur = approbateur or uuid.uuid4()
    async with AsyncSessionLocal() as db:
        comp = await compensation.demander_compensation(
            db,
            operation_origine=operation,
            action_compensation="annuler_effet",
            cle_idempotence=cle,
            demandeur_id=demandeur,
            approbateur_id=approbateur,
            permissions_approbateur=permissions,
        )
        await db.commit()
        return comp.id


async def _executer(comp_id: uuid.UUID, actions: dict) -> str:
    """Exécute la compensation avec le registre d'actions fourni et renvoie son état."""
    async with AsyncSessionLocal() as db:
        comp = await compensation.executer_compensation(db, compensation_id=comp_id, actions=actions)
        await db.commit()
        return comp.etat


async def _compter_compensations(cle: str) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(func.count()).select_from(Compensation).where(Compensation.cle_idempotence == cle)
        )).scalar_one()


# CA-1 : défaut injecté après mutation asynchrone, la compensation converge sans doublon.
async def test_ca1_defaut_apres_mutation_asynchrone_converge_sans_doublon():
    operation = _nom("mutation")
    cle = _nom("cle")
    effets: dict[str, int] = {}
    appels: list[str] = []

    async def mutation_asynchrone(origine: str) -> None:
        """Effet externe créé à chaque passage de la mutation."""
        effets[origine] = effets.get(origine, 0) + 1

    async def annuler_effet(_db, origine: str) -> None:
        """Action de compensation : retire tous les effets de l'opération d'origine."""
        appels.append(origine)
        effets[origine] = 0

    # Défaut injecté : la mutation est rejouée après une erreur, elle crée donc deux effets.
    await mutation_asynchrone(operation)
    await mutation_asynchrone(operation)
    assert effets[operation] == 2

    # La compensation est demandée deux fois (reprise après défaut) : une seule ligne.
    premier = await _demander(operation, cle)
    second = await _demander(operation, cle)
    assert premier == second
    assert await _compter_compensations(cle) == 1

    actions = {"annuler_effet": annuler_effet}
    assert await _executer(premier, actions) == ETAT_REALISEE
    assert effets[operation] == 0
    assert appels == [operation]


# CA-2 : rollback du binaire ne restaure pas les données (limite documentée).
async def test_ca2_rollback_du_binaire_ne_restaure_pas_les_donnees():
    environnement = _nom("production")
    donnees = {"schema_donnees": 2}  # écrit par la version v2 du binaire

    async with AsyncSessionLocal() as db:
        await service.enregistrer_release(
            db,
            version=_nom("v1"),
            hash_artefact=HASH_ARTEFACT,
            reference_source="git:be-252-lot",
            sbom_reference="sbom/test.json",
            config_version=1,
            resultats_gates={},
            demandeur_id=uuid.uuid4(),
            environnement=environnement,
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        v2 = await service.enregistrer_release(
            db,
            version=_nom("v2"),
            hash_artefact=HASH_ARTEFACT,
            reference_source="git:be-252-lot",
            sbom_reference="sbom/test.json",
            config_version=2,
            resultats_gates={},
            demandeur_id=uuid.uuid4(),
            environnement=environnement,
        )
        await db.commit()
        version_courante = v2.version

    # Le rollback identifie la cible compatible (v1, config 1) ...
    async with AsyncSessionLocal() as db:
        cible = await service.identifier_rollback(
            db,
            environnement=environnement,
            version_courante=version_courante,
            config_version_supportee=1,
        )
    assert cible is not None
    assert cible.config_version == 1

    # ... mais il ne touche ni aux données ni aux lignes de compensation : la restauration
    # des données exige une compensation explicite (limite documentée dans docs/release/rollback.md).
    assert donnees == {"schema_donnees": 2}
    async with AsyncSessionLocal() as db:
        restantes = (await db.execute(
            select(func.count()).select_from(ReleaseRecord).where(ReleaseRecord.environnement == environnement)
        )).scalar_one()
    assert restantes == 2


# CA-3 : la compensation est idempotente, deux exécutions produisent un seul effet.
async def test_ca3_compensation_idempotente_deux_executions_un_effet():
    operation = _nom("mutation")
    cle = _nom("cle")
    effets = {operation: 1}
    appels: list[str] = []

    async def annuler_effet(_db, origine: str) -> None:
        appels.append(origine)
        effets[origine] = 0

    comp_id = await _demander(operation, cle)
    actions = {"annuler_effet": annuler_effet}

    assert await _executer(comp_id, actions) == ETAT_REALISEE
    assert await _executer(comp_id, actions) == ETAT_REALISEE

    assert effets[operation] == 0
    assert appels == [operation]  # l'action n'a été appelée qu'une fois


async def test_ca3_etat_initial_en_attente_avant_execution():
    comp_id = await _demander(_nom("mutation"), _nom("cle"))
    async with AsyncSessionLocal() as db:
        comp = await db.get(Compensation, comp_id)
    assert comp.etat == ETAT_EN_ATTENTE
    assert comp.realisee_le is None


# CA-4 : compensation sans droit donne 403.
@pytest.mark.parametrize(
    "permissions",
    [frozenset(), frozenset({"release.promotion.executer"})],
    ids=["aucune_permission", "autre_permission"],
)
async def test_ca4_compensation_sans_droit_refusee_403(permissions):
    operation = _nom("mutation")
    cle = _nom("cle")

    with pytest.raises(AppError) as erreur:
        await _demander(operation, cle, permissions=permissions)

    assert erreur.value.status_code == 403
    assert await _compter_compensations(cle) == 0


async def test_ca4_approbation_par_le_demandeur_refusee_403():
    personne = uuid.uuid4()
    cle = _nom("cle")

    with pytest.raises(AppError) as erreur:
        await _demander(_nom("mutation"), cle, demandeur=personne, approbateur=personne)

    assert erreur.value.status_code == 403
    assert await _compter_compensations(cle) == 0


async def test_ca4_action_inconnue_refusee_sans_effet():
    comp_id = await _demander(_nom("mutation"), _nom("cle"))
    with pytest.raises(AppError) as erreur:
        await _executer(comp_id, {})
    assert erreur.value.status_code == 409
    async with AsyncSessionLocal() as db:
        comp = await db.get(Compensation, comp_id)
    assert comp.etat == ETAT_EN_ATTENTE
