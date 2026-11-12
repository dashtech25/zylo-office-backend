"""Tests BE-198 : droit `platform.maintenance.run` (CA-5) et tenant inactif (CA-6).

Source : implementation-backend/tasks-donnees-api-contrats.md, section BE-198.
Dépendance : BE-196 (non fusionné) ; ces tests échouent tant que le cadre n'existe pas.
"""

import pytest
from httpx import AsyncClient

from tests.be198_support import (
    ROUTE_MIGRATIONS,
    compte_lignes_metier,
    entetes,
    enregistre_migration_de_test,
    exploitant_maintenance,  # noqa: F401  (fixture)
    exploitant_sans_droit,  # noqa: F401  (fixture)
    fixe_statut_tenant,
    lit_run,
)


async def test_ca5_acces_de_maintenance_sans_droit_renvoie_403(client: AsyncClient, exploitant_sans_droit: dict, exploitant_maintenance: dict, organization: dict):
    migration = await enregistre_migration_de_test(nombre=2)
    corps = {"tenantId": organization["id"]}

    refus = await client.post(
        f"{ROUTE_MIGRATIONS}/{migration.id}/run",
        json=corps,
        headers=entetes(exploitant_sans_droit),
    )

    assert refus.status_code == 403, refus.text
    assert migration.traites == []
    assert await lit_run(migration.id) is None

    # Témoin : le même appel réussit avec le droit, donc le 403 vient bien du contrôle de droit.
    accepte = await client.post(
        f"{ROUTE_MIGRATIONS}/{migration.id}/dry-run",
        json=corps,
        headers=entetes(exploitant_maintenance),
    )
    assert accepte.status_code == 200, accepte.text


@pytest.mark.parametrize("statut", ["suspended", "closed"])
async def test_ca6_migration_sur_tenant_inactif_renvoie_422(client: AsyncClient, exploitant_maintenance: dict, organization: dict, statut: str):
    migration = await enregistre_migration_de_test(nombre=2)
    await fixe_statut_tenant(organization["id"], statut)

    res = await client.post(
        f"{ROUTE_MIGRATIONS}/{migration.id}/run",
        json={"tenantId": organization["id"]},
        headers=entetes(exploitant_maintenance),
    )

    assert res.status_code == 422, res.text
    assert migration.traites == []
    assert await compte_lignes_metier(migration) == 0
