"""BE-021 : registre des modules et états de module (absent, inconnu, incompatible).

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-socle-tenant-identite.md,
section BE-021). Chaque modification de la base est annulée (rollback) pour ne jamais laisser
d'état entre tests.
"""

import uuid

from sqlalchemy import delete, update

from app.core.database import AsyncSessionLocal
from app.modules_registry.models import Module, OrganizationModule
from app.modules_registry.seed import seed_known_modules


async def test_ca1_module_connu_absent_du_registre_renvoie_absent(client):
    from app.modules_registry.etats import ETAT_ABSENT, etat_module

    await seed_known_modules()
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Module).where(Module.code == "zylo_tanker"))
        etat = await etat_module(db, "zylo_tanker")
        await db.rollback()
    assert etat == ETAT_ABSENT


async def test_ca2_module_non_reconnu_renvoie_inconnu(client):
    from app.modules_registry.etats import ETAT_INCONNU, etat_module

    async with AsyncSessionLocal() as db:
        etat = await etat_module(db, "module_fantome_be021")
    assert etat == ETAT_INCONNU


async def test_ca3_manifeste_de_version_incompatible_renvoie_incompatible(client):
    from app.modules_registry.etats import ETAT_INCOMPATIBLE, etat_module

    await seed_known_modules()
    async with AsyncSessionLocal() as db:
        await db.execute(update(Module).where(Module.code == "zylo_liquid").values(manifestVersion=99))
        etat = await etat_module(db, "zylo_liquid")
        await db.rollback()
    assert etat == ETAT_INCOMPATIBLE


async def test_module_connu_et_compatible_renvoie_disponible(client):
    from app.modules_registry.etats import ETAT_DISPONIBLE, etat_module

    await seed_known_modules()
    async with AsyncSessionLocal() as db:
        etat = await etat_module(db, "zylo_liquid")
    assert etat == ETAT_DISPONIBLE


def test_ca4_aucun_des_trois_etats_n_ouvre_l_acces():
    from app.modules_registry.etats import (
        ETAT_ABSENT,
        ETAT_DISPONIBLE,
        ETAT_INCOMPATIBLE,
        ETAT_INCONNU,
        etat_ouvre_acces,
    )

    assert etat_ouvre_acces(ETAT_ABSENT) is False
    assert etat_ouvre_acces(ETAT_INCONNU) is False
    assert etat_ouvre_acces(ETAT_INCOMPATIBLE) is False
    assert etat_ouvre_acces(ETAT_DISPONIBLE) is True


async def test_ca4_module_incompatible_ne_donne_pas_acces_meme_active_pour_l_organisation(
    client, registered_user: dict, organization: dict
):
    from app.modules_registry.service import is_module_active, require_module_active  # noqa: F401

    await seed_known_modules()
    org_id = uuid.UUID(organization["id"])
    async with AsyncSessionLocal() as db:
        db.add(OrganizationModule(organizationId=org_id, moduleCode="zylo_liquid", status="active"))
        await db.flush()
        acces_compatible = await is_module_active(db, org_id, "zylo_liquid")
        await db.execute(update(Module).where(Module.code == "zylo_liquid").values(manifestVersion=99))
        acces_incompatible = await is_module_active(db, org_id, "zylo_liquid")
        await db.rollback()
    assert acces_compatible is True
    assert acces_incompatible is False


async def test_ca4_module_absent_ne_donne_pas_acces_dans_les_droits_effectifs(
    client, registered_user: dict, organization: dict
):
    from app.rbac.module_rights import effective_rights_by_module

    await seed_known_modules()
    org_id = uuid.UUID(organization["id"])
    async with AsyncSessionLocal() as db:
        await db.execute(update(Module).where(Module.code == "zylo_liquid").values(manifestVersion=99))
        blocs = await effective_rights_by_module(db, org_id, uuid.uuid4())
        await db.rollback()
    bloc = next(b for b in blocs if b["moduleCode"] == "zylo_liquid")
    assert bloc["active"] is False
    assert bloc["permissionCodes"] == []
