"""Socle d'idempotence et de version optimiste (BE-072).

Ces tests fixent la section BE-072 de `implementation-backend/tasks-abonnements-facturation.md` :

- CA-1 : même clé + même commande rejoue le résultat initial, sans effet de bord ;
- CA-2 : même clé + commande différente renvoie `DUPLICATE` et ne modifie rien ;
- CA-3 : écriture avec `expectedVersion` obsolète renvoie `VERSION_CONFLICT`, sans modification ;
- CA-4 : une clé créée par le principal A n'est pas rejouable par le principal B.

Le mécanisme est testé au niveau service (`create_invoice`, décoré par
`idempotent_command`, et `write_versioned`) : aucune route n'est ajoutée par BE-072.
Les tests de registre (`idempotency_record`) et de version (`subscription.version`,
`invoice.version`) couvrent les colonnes décrites par la définition.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.billing import service
from app.billing.errors import BillingErrorCode
from app.billing.idempotency import write_versioned
from app.billing.models import IdempotencyRecord, Invoice, Subscription
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from tests.test_billing import creer_plan_catalogue


async def _identifiant_utilisateur(client: AsyncClient, access_token: str) -> uuid.UUID:
    res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert res.status_code == 200
    return uuid.UUID(res.json()["id"])


async def _nouvel_utilisateur(client: AsyncClient) -> uuid.UUID:
    """Second principal, distinct du `registered_user` de la fixture."""
    email = f"be072-{uuid.uuid4().hex[:10]}@example.test"
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Autre"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return await _identifiant_utilisateur(client, login.json()["accessToken"])


async def _abonnement(organization_id: uuid.UUID, actor_id: uuid.UUID) -> Subscription:
    plan_code = f"plan-be072-{uuid.uuid4().hex[:8]}"
    await creer_plan_catalogue(plan_code)
    async with AsyncSessionLocal() as db:
        return await service.create_trial_subscription(db, organization_id, plan_code, actor_id)


async def _nombre_factures(subscription_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(Invoice).where(Invoice.subscriptionId == subscription_id))


async def test_rejeu_meme_cle_meme_commande_renvoie_la_facture_initiale(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-1 : la seconde demande renvoie la facture créée par la première, sans en créer une autre."""
    org_id = uuid.UUID(organization["id"])
    actor_id = await _identifiant_utilisateur(client, registered_user["accessToken"])
    subscription = await _abonnement(org_id, actor_id)
    cle = f"cle-{uuid.uuid4().hex}"

    async with AsyncSessionLocal() as db:
        premiere = await service.create_invoice(db, org_id, actor_id, subscription.id, cle)
    async with AsyncSessionLocal() as db:
        rejeu = await service.create_invoice(db, org_id, actor_id, subscription.id, cle)

    assert rejeu.id == premiere.id
    assert await _nombre_factures(subscription.id) == 1


async def test_meme_cle_commande_differente_renvoie_DUPLICATE_sans_modification(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-2 : même clé, autre abonnement (commande différente) : DUPLICATE 409, aucune facture ajoutée."""
    org_id = uuid.UUID(organization["id"])
    actor_id = await _identifiant_utilisateur(client, registered_user["accessToken"])
    premier = await _abonnement(org_id, actor_id)
    second = await _abonnement(org_id, actor_id)
    cle = f"cle-{uuid.uuid4().hex}"

    async with AsyncSessionLocal() as db:
        await service.create_invoice(db, org_id, actor_id, premier.id, cle)
    with pytest.raises(AppError) as erreur:
        async with AsyncSessionLocal() as db:
            await service.create_invoice(db, org_id, actor_id, second.id, cle)

    assert erreur.value.code == BillingErrorCode.DUPLICATE.value
    assert erreur.value.status_code == 409
    assert await _nombre_factures(second.id) == 0
    assert await _nombre_factures(premier.id) == 1


async def test_ecriture_avec_version_obsolete_renvoie_VERSION_CONFLICT_sans_modification(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-3 : après une écriture réussie, une écriture au numéro de version précédent est refusée sans effet."""
    org_id = uuid.UUID(organization["id"])
    actor_id = await _identifiant_utilisateur(client, registered_user["accessToken"])
    subscription = await _abonnement(org_id, actor_id)
    assert subscription.version == 1

    async with AsyncSessionLocal() as db:
        await write_versioned(db, Subscription, subscription.id, expected_version=1, changes={"status": "active"})
    with pytest.raises(AppError) as erreur:
        async with AsyncSessionLocal() as db:
            await write_versioned(db, Subscription, subscription.id, expected_version=1, changes={"status": "cancelled"})

    assert erreur.value.code == BillingErrorCode.VERSION_CONFLICT.value
    assert erreur.value.status_code == 409
    async with AsyncSessionLocal() as db:
        relu = await db.get(Subscription, subscription.id)
    assert relu.status == "active"
    assert relu.version == 2


async def test_version_facture_initialisee_puis_incrementee(client: AsyncClient, registered_user: dict, organization: dict):
    """Colonne `version` sur `invoice` : 1 à la création, +1 à chaque écriture versionnée réussie."""
    org_id = uuid.UUID(organization["id"])
    actor_id = await _identifiant_utilisateur(client, registered_user["accessToken"])
    subscription = await _abonnement(org_id, actor_id)
    async with AsyncSessionLocal() as db:
        facture = await service.create_invoice(db, org_id, actor_id, subscription.id, f"cle-{uuid.uuid4().hex}")
    assert facture.version == 1

    async with AsyncSessionLocal() as db:
        await write_versioned(db, Invoice, facture.id, expected_version=1, changes={"status": "paid"})
    async with AsyncSessionLocal() as db:
        relue = await db.get(Invoice, facture.id)
    assert relue.version == 2
    assert relue.status == "paid"


async def test_cle_creee_par_un_principal_non_rejouable_par_un_autre(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-4 : le principal B, avec la clé de A, obtient sa propre facture (comme une clé inconnue),
    jamais celle de A, et sans erreur qui révélerait l'existence de la clé."""
    org_id = uuid.UUID(organization["id"])
    principal_a = await _identifiant_utilisateur(client, registered_user["accessToken"])
    principal_b = await _nouvel_utilisateur(client)
    subscription = await _abonnement(org_id, principal_a)
    cle = f"cle-{uuid.uuid4().hex}"

    async with AsyncSessionLocal() as db:
        facture_a = await service.create_invoice(db, org_id, principal_a, subscription.id, cle)
    async with AsyncSessionLocal() as db:
        facture_b = await service.create_invoice(db, org_id, principal_b, subscription.id, cle)

    assert facture_b.id != facture_a.id
    assert await _nombre_factures(subscription.id) == 2


async def test_registre_idempotence_porte_principal_route_et_cle(client: AsyncClient, registered_user: dict, organization: dict):
    """Une ligne `idempotency_record` par commande : portée = principal + route + clé, résultat référencé."""
    org_id = uuid.UUID(organization["id"])
    actor_id = await _identifiant_utilisateur(client, registered_user["accessToken"])
    subscription = await _abonnement(org_id, actor_id)
    cle = f"cle-{uuid.uuid4().hex}"

    async with AsyncSessionLocal() as db:
        facture = await service.create_invoice(db, org_id, actor_id, subscription.id, cle)

    async with AsyncSessionLocal() as db:
        lignes = (await db.scalars(select(IdempotencyRecord).where(IdempotencyRecord.scopeKey.contains(cle)))).all()
    assert len(lignes) == 1
    ligne = lignes[0]
    assert str(actor_id) in ligne.scopeKey
    assert "billing.invoice.create" in ligne.scopeKey
    assert ligne.status == "completed"
    assert ligne.resultRef == str(facture.id)
    assert ligne.commandHash


async def test_echec_de_commande_libere_la_cle(client: AsyncClient, registered_user: dict, organization: dict):
    """Une commande qui échoue n'enregistre pas de résultat : la même clé reste utilisable."""
    org_id = uuid.UUID(organization["id"])
    actor_id = await _identifiant_utilisateur(client, registered_user["accessToken"])
    subscription = await _abonnement(org_id, actor_id)
    cle = f"cle-{uuid.uuid4().hex}"

    with pytest.raises(AppError):
        async with AsyncSessionLocal() as db:
            await service.create_invoice(db, org_id, actor_id, uuid.uuid4(), cle)
    async with AsyncSessionLocal() as db:
        facture = await service.create_invoice(db, org_id, actor_id, subscription.id, cle)

    assert await _nombre_factures(subscription.id) == 1
    assert facture.subscriptionId == subscription.id
