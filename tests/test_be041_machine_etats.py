"""BE-041 : machine à états générique et journal de transitions.

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-modules-droits.md,
section BE-041) avant le code. Le journal est la table `module_state_transitions` (nouvelle) ;
la fonction de transition est `app.modules_registry.transitions.transitionner`.
"""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.modules_registry.models import ModuleStateTransition

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REVISION_PRECEDENTE_BE041 = "d4e5f6a7b8c9"
TYPE_SUJET = "tenant_module"


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    from app.core.database import engine

    await engine.dispose()
    yield


def _erreur_code(exc: pytest.ExceptionInfo) -> str:
    assert isinstance(exc.value, AppError)
    return exc.value.code


async def _transition(
    db,
    *,
    sujet: uuid.UUID,
    vers_etat: str,
    version: int,
    cle: str,
    acteur: uuid.UUID | None = None,
    origine: str = "client",
    operation_id: uuid.UUID | None = None,
):
    from app.modules_registry.transitions import transitionner

    return await transitionner(
        db,
        type_sujet=TYPE_SUJET,
        id_sujet=sujet,
        vers_etat=vers_etat,
        version_attendue=version,
        acteur_id=acteur if acteur is not None else uuid.uuid4(),
        origine=origine,
        cle_idempotence=cle,
        operation_id=operation_id,
    )


async def _nombre_de_lignes(db, sujet: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(ModuleStateTransition)
            .where(ModuleStateTransition.subjectId == sujet)
        )
    ).scalar_one()


def test_transitions_autorisees_contiennent_le_chemin_d_installation_et_pas_le_saut_interdit():
    from app.modules_registry.transitions import TRANSITIONS_AUTORISEES, transition_autorisee

    assert transition_autorisee(TYPE_SUJET, "not_installed", "provisioning")
    assert transition_autorisee(TYPE_SUJET, "installed", "active")
    assert transition_autorisee(TYPE_SUJET, "active", "suspended")
    assert transition_autorisee(TYPE_SUJET, "suspended", "active")
    assert not transition_autorisee(TYPE_SUJET, "not_installed", "active")
    assert not transition_autorisee("type_inconnu", "not_installed", "provisioning")
    assert ("not_installed", "active") not in TRANSITIONS_AUTORISEES[TYPE_SUJET]


async def test_ca1_transition_absente_est_refusee_sans_ligne_de_journal():
    async with AsyncSessionLocal() as db:
        sujet = uuid.uuid4()
        with pytest.raises(AppError) as exc:
            await _transition(db, sujet=sujet, vers_etat="active", version=0, cle="ca1-saut")
        nombre = await _nombre_de_lignes(db, sujet)
        await db.rollback()

    assert _erreur_code(exc) == "MODULE_TRANSITION_NOT_ALLOWED"
    assert exc.value.status_code == 409
    assert nombre == 0


async def test_ca1_transition_autorisee_cree_une_ligne_et_avance_la_version():
    async with AsyncSessionLocal() as db:
        sujet = uuid.uuid4()
        ligne = await _transition(db, sujet=sujet, vers_etat="provisioning", version=0, cle="ca1-ok")
        await db.rollback()

    assert ligne.fromState == "not_installed"
    assert ligne.toState == "provisioning"
    assert ligne.stateVersionBefore == 0
    assert ligne.stateVersionAfter == 1


async def test_ca2_rejeu_avec_meme_cle_renvoie_le_resultat_initial_sans_second_effet():
    async with AsyncSessionLocal() as db:
        sujet = uuid.uuid4()
        premiere = await _transition(db, sujet=sujet, vers_etat="provisioning", version=0, cle="ca2-rejeu")
        # Rejeu avec la même clé : la version attendue (0) est périmée, mais le résultat initial
        # doit être renvoyé sans nouvelle ligne ni nouvel effet.
        rejeu = await _transition(db, sujet=sujet, vers_etat="provisioning", version=0, cle="ca2-rejeu")
        nombre = await _nombre_de_lignes(db, sujet)
        await db.rollback()

    assert rejeu.id == premiere.id
    assert rejeu.stateVersionAfter == 1
    assert nombre == 1


async def test_ca3_version_attendue_differente_est_refusee_en_conflit():
    async with AsyncSessionLocal() as db:
        sujet = uuid.uuid4()
        await _transition(db, sujet=sujet, vers_etat="provisioning", version=0, cle="ca3-premiere")
        with pytest.raises(AppError) as exc:
            await _transition(db, sujet=sujet, vers_etat="installed", version=0, cle="ca3-obsolete")
        nombre = await _nombre_de_lignes(db, sujet)
        await db.rollback()

    assert _erreur_code(exc) == "MODULE_STATE_VERSION_CONFLICT"
    assert exc.value.status_code == 409
    assert nombre == 1


async def test_ca4_chaque_transition_reussie_journalise_acteur_origine_et_operation():
    async with AsyncSessionLocal() as db:
        sujet = uuid.uuid4()
        acteur = uuid.uuid4()
        operation = uuid.uuid4()
        ligne = await _transition(
            db,
            sujet=sujet,
            vers_etat="provisioning",
            version=0,
            cle="ca4-journal",
            acteur=acteur,
            origine="support",
            operation_id=operation,
        )
        relue = (
            await db.execute(
                select(ModuleStateTransition).where(ModuleStateTransition.id == ligne.id)
            )
        ).scalar_one()
        await db.rollback()

    assert relue.actorId == acteur
    assert relue.origin == "support"
    assert relue.operationId == operation
    assert relue.idempotencyKey == "ca4-journal"


async def test_ca5_commande_sans_acteur_est_refusee_en_401_sans_ligne():
    async with AsyncSessionLocal() as db:
        from app.modules_registry.transitions import transitionner

        sujet = uuid.uuid4()
        with pytest.raises(AppError) as exc:
            await transitionner(
                db,
                type_sujet=TYPE_SUJET,
                id_sujet=sujet,
                vers_etat="provisioning",
                version_attendue=0,
                acteur_id=None,
                origine="client",
                cle_idempotence="ca5-sans-acteur",
            )
        nombre = await _nombre_de_lignes(db, sujet)
        await db.rollback()

    assert exc.value.status_code == 401
    assert _erreur_code(exc) == "MODULE_ACTOR_REQUIRED"
    assert nombre == 0
