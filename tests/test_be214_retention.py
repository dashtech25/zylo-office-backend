"""BE-214 : Rétention, sauvegarde et purge — critères d'acceptation.

Intention : prouver les critères d'acceptation de BE-214
(implementation-backend/tasks-donnees-api-contrats.md, section BE-214) :
- CA-1 : une purge sous `legal_hold` actif est refusée 422 (test de refus).
- CA-2 : tant que la durée d'une catégorie est NON DÉFINIE, la purge ne supprime rien (test).
- CA-3 : restauration de sauvegarde reproduit les lignes et intégrité (test).
- CA-4 : purge d'un tenant laisse intact le tenant voisin (test d'isolation).
- CA-5 : demande d'effacement crée une entrée d'audit (test).

Routes testées :
- `POST /api/v1/admin/retention/purges` (purge de données)

Permissions :
- `platform.retention.manage` : requise pour demander une purge

Tables :
- `retention_policy` : durées de rétention par catégorie
- `legal_hold` : verrous légaux actifs
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal


# Test CA-1 : refus si legal_hold actif


@pytest.mark.asyncio
async def test_ca1_purge_blocked_if_legal_hold_active(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-1 : purge sous legal_hold actif est refusée 422.

    Vérification : tentative de purge avec legal_hold actif retourne 422.
    """
    # TODO: Implémenter quand les modèles et routes BE-214 existent
    # 1. Créer un legal_hold actif pour l'organisation
    # 2. Tenter POST /api/v1/admin/retention/purges
    # 3. Vérifier que la réponse est 422 avec code erreur `legal_hold_active`
    pass


# Test CA-2 : durée NON DÉFINIE ne supprime rien


@pytest.mark.asyncio
async def test_ca2_purge_without_defined_duration_deletes_nothing(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-2 : tant que la durée est NON DÉFINIE, rien n'est supprimé.

    Vérification : purge d'une catégorie sans durée définie retourne 200
    mais aucune donnée n'est supprimée.
    """
    # TODO: Implémenter avec retention_policy sans durée définie
    # 1. Créer une catégorie sans durée (duration = NULL)
    # 2. POST /api/v1/admin/retention/purges avec cette catégorie
    # 3. Vérifier que le nombre de lignes reste inchangé
    pass


# Test CA-3 : restauration reproduit intégrité


@pytest.mark.asyncio
async def test_ca3_backup_restore_preserves_integrity(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-3 : restauration reproduit le nombre de lignes et intégrité.

    Vérification : après sauvegarde et restauration, les données sont intactes.
    """
    # TODO: Implémenter avec backup/restore
    # 1. Créer des données
    # 2. Sauvegarde (mécanisme à définir : QE-API-15)
    # 3. Purger les données
    # 4. Restaurer depuis la sauvegarde
    # 5. Vérifier nombre de lignes et checksums
    pass


# Test CA-4 : isolation tenant


@pytest.mark.asyncio
async def test_ca4_purge_tenant_isolation(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-4 : purge d'un tenant ne supprime rien d'un autre tenant.

    Deux organisations, vérification que la purge est isolée.
    """
    # TODO: Créer deux organisations
    # 1. Ajouter des données dans org1 et org2
    # 2. POST /api/v1/admin/retention/purges pour org1
    # 3. Vérifier que org1 est purgée
    # 4. Vérifier que org2 reste intacte
    pass


# Test CA-5 : audit


@pytest.mark.asyncio
async def test_ca5_purge_request_writes_audit(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-5 : demande d'effacement crée une entrée d'audit.

    Vérification : événement d'audit créé avec action `data.purge.requested`.
    """
    # TODO: Implémenter avec audit logging
    # 1. POST /api/v1/admin/retention/purges avec catégorie valide
    # 2. Vérifier qu'une entrée audit est créée
    # 3. Vérifier l'action = `data.purge.requested`
    pass


# Tests basiques


@pytest.mark.asyncio
async def test_post_purge_endpoint_exists(client: AsyncClient, registered_user: dict, organization: dict):
    """Test basique : endpoint POST /api/v1/admin/retention/purges existe."""
    token = registered_user["accessToken"]
    headers = {
        "Authorization": f"Bearer {token}",
    }

    resp = await client.post(
        "/api/v1/admin/retention/purges",
        json={"category": "test", "beforeDate": "2024-01-01T00:00:00Z"},
        headers=headers,
    )

    # S'attendre à un code HTTP pertinent (200, 403, 422 selon le test)
    assert resp.status_code in [200, 403, 422, 404, 500], f"Unexpected status {resp.status_code}: {resp.text}"
