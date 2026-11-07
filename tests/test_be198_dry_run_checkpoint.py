"""Tests BE-198 : dry-run sans écriture (CA-1) et reprise au dernier checkpoint (CA-2).

Source : implementation-backend/tasks-donnees-api-contrats.md, section BE-198.
Dépendance : BE-196 (non fusionné) ; ces tests échouent tant que le cadre n'existe pas.
"""

from httpx import AsyncClient

from tests.be198_support import (
    CRASH_SIMULE,
    ROUTE_MIGRATIONS,
    compte_lignes_metier,
    entetes,
    enregistre_migration_de_test,
    exploitant_maintenance,  # noqa: F401  (fixture)
    lance_en_simulant_interruption,
    lit_run,
)


async def test_ca1_dry_run_n_ecrit_aucune_donnee_metier(client: AsyncClient, exploitant_maintenance: dict, organization: dict):
    migration = await enregistre_migration_de_test(nombre=5)
    avant = await compte_lignes_metier(migration)

    res = await client.post(
        f"{ROUTE_MIGRATIONS}/{migration.id}/dry-run",
        json={"tenantId": organization["id"]},
        headers=entetes(exploitant_maintenance),
    )

    assert res.status_code == 200, res.text
    assert await compte_lignes_metier(migration) == avant
    assert migration.traites == []


async def test_ca2_interruption_reprend_au_dernier_checkpoint(client: AsyncClient, exploitant_maintenance: dict, organization: dict):
    migration = await enregistre_migration_de_test(nombre=5, crash_avant=3)
    corps = {"tenantId": organization["id"]}

    # Le crash simulé survient avant l'élément 3, après le checkpoint 2.
    await lance_en_simulant_interruption(
        client, f"{ROUTE_MIGRATIONS}/{migration.id}/run", corps, entetes(exploitant_maintenance), CRASH_SIMULE,
    )
    interrompu = await lit_run(migration.id)
    assert interrompu is not None
    assert interrompu["state"] != "completed"
    assert interrompu["checkpoint"] == 2
    assert migration.traites == [1, 2]

    # Reprise : seuls les éléments 3 à 5 sont traités, sans doublon.
    migration.crash_avant = None
    res = await client.post(
        f"{ROUTE_MIGRATIONS}/{migration.id}/resume",
        json=corps,
        headers=entetes(exploitant_maintenance),
    )

    assert res.status_code == 200, res.text
    assert migration.traites == [1, 2, 3, 4, 5]
    assert await compte_lignes_metier(migration) == 5
    assert (await lit_run(migration.id))["state"] == "completed"
