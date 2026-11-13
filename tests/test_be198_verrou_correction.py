"""Tests BE-198 : verrou perdu (CA-3) et correction en avant sans rollback destructif (CA-4).

Source : implementation-backend/tasks-donnees-api-contrats.md, section BE-198.
Dépendance : BE-196 (non fusionné) ; ces tests échouent tant que le cadre n'existe pas.
"""

from httpx import AsyncClient

from tests.be198_support import (
    ECHEC_APRES_EFFET_EXTERNE,
    ROUTE_MIGRATIONS,
    compte_lignes_metier,
    entetes,
    enregistre_migration_de_test,
    exploitant_maintenance,  # noqa: F401  (fixture)
    lance_en_simulant_interruption,
    lit_run,
)


async def test_ca3_verrou_perdu_arrete_les_ecritures_du_run(client: AsyncClient, exploitant_maintenance: dict, organization: dict):
    # Après l'élément 2, un autre processus prend le verrou : le run doit cesser d'écrire.
    migration = await enregistre_migration_de_test(nombre=5, vole_verrou_apres=2)

    await client.post(
        f"{ROUTE_MIGRATIONS}/{migration.id}/run",
        json={"tenantId": organization["id"]},
        headers=entetes(exploitant_maintenance),
    )

    assert migration.traites == [1, 2]
    assert await compte_lignes_metier(migration) == 2
    run = await lit_run(migration.id)
    assert run is not None
    assert run["state"] != "completed"
    assert run["lockOwner"] == "autre-processus-be198"


async def test_ca4_echec_apres_effet_externe_pas_de_rollback_destructif(client: AsyncClient, exploitant_maintenance: dict, organization: dict):
    migration = await enregistre_migration_de_test(nombre=3, echec_apres_effet_externe=2)
    corps = {"tenantId": organization["id"]}

    # L'élément 2 produit un effet externe puis échoue : le run n'est pas terminé.
    await lance_en_simulant_interruption(
        client, f"{ROUTE_MIGRATIONS}/{migration.id}/run", corps, entetes(exploitant_maintenance), ECHEC_APRES_EFFET_EXTERNE,
    )
    assert migration.effets_externes == [2]
    assert (await lit_run(migration.id))["state"] != "completed"
    avant_rollback = await compte_lignes_metier(migration)
    assert avant_rollback == 1  # seul l'élément 1 est committé au checkpoint

    # Un rollback destructif est refusé après effet externe : aucune ligne n'est supprimée.
    refus = await client.post(
        f"{ROUTE_MIGRATIONS}/{migration.id}/rollback",
        json=corps,
        headers=entetes(exploitant_maintenance),
    )
    assert refus.status_code == 409, refus.text
    assert await compte_lignes_metier(migration) == avant_rollback

    # Correction en avant : la panne est levée, la reprise mène le run à son terme.
    migration.echec_apres_effet_externe = None
    res = await client.post(
        f"{ROUTE_MIGRATIONS}/{migration.id}/resume",
        json=corps,
        headers=entetes(exploitant_maintenance),
    )
    assert res.status_code == 200, res.text
    assert (await lit_run(migration.id))["state"] == "completed"
    assert await compte_lignes_metier(migration) == 3
