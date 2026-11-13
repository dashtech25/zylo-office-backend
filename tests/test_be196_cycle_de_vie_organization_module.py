"""BE-196 : cycle de vie OrganizationModule (activation d'un module par une organisation).

Tests écrits d'après implementation-backend/tasks-donnees-api-contrats.md (section BE-196) avant le
code. Dépendance : BE-195 (manifeste et registre) n'est pas fusionné ; ces tests ne l'utilisent pas
directement, mais BE-196 ne peut être livré qu'après sa fusion.

Route testée (préfixe `/api/v1/organizations/{organization_id}/modules/{module_code}`) :
- `POST .../activate`. Les autres routes du lot (preflight, suspend, resume, upgrade, uninstall) ne
  sont pas couvertes ici : les critères CA-1 à CA-6 ne les concernent pas.

Hypothèses de forme, à confirmer par la suite du lot (QE-API-01, QE-API-13) :
- corps de `activate` : `{"expectedVersion": int, "operationId": uuid}` ;
- réponse : champs `state` (ex. `active`, `failed`) et `version` ;
- code HTTP d'un échec de hook : non fixé par la spec. Le test lit l'état `failed` dans le corps ;
- hook de provisionnement : `enregistre_hook_activation` (app/modules_registry/service.py) ;
- table `organization_module` : colonnes camelCase du spec (`organizationId`, `moduleId`, `state`,
  `version`, `operationId`). Le modèle actuel s'appelle `organizationModule` et a d'autres colonnes :
  écart signalé dans le rapport de BE-196.

Droits : le spec nomme `module.manage` ; le code expose `modules.module.manage`. Les tests ne
nomment pas la permission : le propriétaire la reçoit, un membre sans rôle ne la reçoit pas.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.billing import service as billing_service
from app.billing.models import Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser
from app.modules_registry.manifeste import VERSIONS_MANIFESTE_SUPPORTEES
from app.modules_registry.models import ModuleVersion
from app.modules_registry.service import enregistre_hook_activation, get_or_create_module
from tests.conftest import _affecte_role_owner, unique_email

MOT_DE_PASSE = "TestPassword123!"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Le moteur est un singleton lié à la boucle asyncio : pool neuf avant et après chaque test."""
    await engine.dispose()
    yield
    await engine.dispose()


def _code() -> str:
    return f"be196_{uuid.uuid4().hex[:10]}"


async def _module_publie(code: str) -> uuid.UUID:
    """Crée un module du catalogue avec une version publiée compatible ; renvoie l'identifiant du module."""
    async with AsyncSessionLocal() as db:
        module = await get_or_create_module(db, code, f"Module {code}", "Module de test BE-196")
        db.add(
            ModuleVersion(
                moduleId=module.id,
                version="1.0.0",
                digest="sha256:be196",
                provenance="test-be196",
                compatibility={"manifestVersion": max(VERSIONS_MANIFESTE_SUPPORTEES)},
                prerequisites=None,
                publicationState="published",
                publishedAt=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        return module.id


async def _entitlement_actif(organisation_id: uuid.UUID, code: str) -> None:
    """Abonnement actif et entitlement effectif pour `code` (même forme que BE-045 et BE-049)."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await billing_service.get_or_create_plan(
            db, code, f"plan-be196-{uuid.uuid4().hex[:10]}", "Plan BE-196", 0, "XAF", 30
        )
        version = await billing_service.ensure_initial_plan_version(db, plan)
        abonnement = Subscription(
            organizationId=organisation_id, planId=plan.id, planVersionId=version.id,
            status="active", startDate=maintenant, endDate=maintenant + timedelta(days=30),
        )
        db.add(abonnement)
        await db.flush()
        db.add(
            SubscriptionEntitlement(
                organizationId=organisation_id, subscriptionId=abonnement.id, moduleCode=code,
                entitlementCode=f"be196.code.{uuid.uuid4().hex[:8]}", status="active",
                startsAt=maintenant, endsAt=maintenant + timedelta(days=30),
                sourceAttribution="offre", niveauApplication="organisation",
            )
        )
        await db.commit()


def _hook(code: str, echecs: int = 0) -> list[uuid.UUID]:
    """Enregistre le hook de provisionnement de test pour `code`.

    Le hook journalise chaque organisation provisionnée ; il lève une erreur pour les `echecs`
    premiers appels (CA-4). Renvoie la liste des appels, lue par les tests.
    """
    appels: list[uuid.UUID] = []

    async def hook(db, organization_id: uuid.UUID) -> None:
        appels.append(organization_id)
        if len(appels) <= echecs:
            raise RuntimeError("échec de hook simulé (BE-196 CA-4)")

    enregistre_hook_activation(code, hook)
    return appels


async def _inscrire(client: AsyncClient) -> dict:
    """Crée un utilisateur réel ; renvoie son identifiant, son courriel et son jeton d'accès."""
    email = unique_email()
    reponse = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-196"}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return {"id": uuid.UUID(reponse.json()["id"]), "email": email, "token": login.json()["accessToken"]}


async def _membre_sans_droit(client: AsyncClient, organisation_id: uuid.UUID) -> dict:
    """Utilisateur rattaché à l'organisation, sans aucun rôle de module (aucune permission `module.manage`)."""
    membre = await _inscrire(client)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organisation_id, userId=membre["id"]))
        await db.commit()
    return membre


def _url(organisation_id: uuid.UUID, code: str, action: str = "activate") -> str:
    return f"/api/v1/organizations/{organisation_id}/modules/{code}/{action}"


def _entete(token: str, organisation_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": str(organisation_id)}


async def _activer(client: AsyncClient, token: str, organisation_id: uuid.UUID, code: str,
                   expected_version: int):
    """Appelle `activate` avec un identifiant d'opération neuf ; renvoie la réponse HTTP brute."""
    return await client.post(
        _url(organisation_id, code),
        json={"expectedVersion": expected_version, "operationId": str(uuid.uuid4())},
        headers=_entete(token, organisation_id),
    )


async def _ligne(organisation_id: uuid.UUID, module_code: str) -> dict | None:
    """Ligne `organization_module` du couple (organisation, code du module), ou None si absente."""
    async with AsyncSessionLocal() as db:
        ligne = (
            await db.execute(
                text(
                    'SELECT "state", "version", "operationId" FROM "organizationModule" '
                    'WHERE "organizationId" = :organisation AND "moduleCode" = :moduleCode'
                ),
                {"organisation": organisation_id, "moduleCode": module_code},
            )
        ).mappings().first()
        return dict(ligne) if ligne is not None else None


async def _compte_audit(organisation_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                text('SELECT count(*) FROM audit_event WHERE "organizationId" = :organisation'),
                {"organisation": organisation_id},
            )
        ).scalar_one()


async def _compte_outbox(organisation_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                text(
                    'SELECT count(*) FROM outbox_evenement WHERE "tenantId" = :organisation '
                    "OR CAST(payload AS TEXT) LIKE :motif"
                ),
                {"organisation": organisation_id, "motif": f"%{organisation_id}%"},
            )
        ).scalar_one()


async def test_ca1_deux_activations_ne_provisionnent_qu_une_fois(client, registered_user, organization):
    """CA-1 : deux activations successives du même module ne provisionnent qu'une fois (idempotence)."""
    organisation_id = uuid.UUID(organization["id"])
    code = _code()
    module_id = await _module_publie(code)
    await _entitlement_actif(organisation_id, code)
    appels = _hook(code)

    premiere = await _activer(client, registered_user["accessToken"], organisation_id, code, expected_version=0)
    assert premiere.status_code in (200, 201), premiere.text
    assert premiere.json()["state"] == "active"

    seconde = await _activer(
        client, registered_user["accessToken"], organisation_id, code, expected_version=premiere.json()["version"]
    )
    assert seconde.status_code in (200, 201), seconde.text
    assert seconde.json()["state"] == "active"

    assert len(appels) == 1, "le provisionnement doit n'avoir lieu qu'une seule fois"
    assert await _ligne(organisation_id, code) is not None


async def test_ca2_entitlement_absent_bloque_activation_422(client, registered_user, organization):
    """CA-2 : sans entitlement, l'activation est refusée 422 et rien n'est provisionné."""
    organisation_id = uuid.UUID(organization["id"])
    code = _code()
    module_id = await _module_publie(code)
    appels = _hook(code)

    reponse = await _activer(client, registered_user["accessToken"], organisation_id, code, expected_version=0)

    assert reponse.status_code == 422, reponse.text
    assert appels == []
    ligne = await _ligne(organisation_id, code)
    assert ligne is None or ligne["state"] != "active"


async def test_ca3_permission_module_manage_absente_renvoie_403(client, registered_user, organization):
    """CA-3 : un membre sans permission `module.manage` reçoit 403 ; l'entitlement est présent,
    donc seule la permission peut expliquer le refus."""
    organisation_id = uuid.UUID(organization["id"])
    code = _code()
    module_id = await _module_publie(code)
    await _entitlement_actif(organisation_id, code)
    appels = _hook(code)
    membre = await _membre_sans_droit(client, organisation_id)

    reponse = await _activer(client, membre["token"], organisation_id, code, expected_version=0)

    assert reponse.status_code == 403, reponse.text
    assert appels == []
    ligne = await _ligne(organisation_id, code)
    assert ligne is None or ligne["state"] != "active"


async def test_ca4_echec_de_hook_laisse_failed_recuperable_et_rejouable(client, registered_user, organization):
    """CA-4 : un échec de hook laisse l'état `failed` ; une reprise par nouvelle activation réussit."""
    organisation_id = uuid.UUID(organization["id"])
    code = _code()
    module_id = await _module_publie(code)
    await _entitlement_actif(organisation_id, code)
    appels = _hook(code, echecs=1)
    token = registered_user["accessToken"]

    echec = await _activer(client, token, organisation_id, code, expected_version=0)
    assert echec.json().get("state") == "failed", echec.text
    ligne_echec = await _ligne(organisation_id, code)
    assert ligne_echec is not None and ligne_echec["state"] == "failed"

    reprise = await _activer(client, token, organisation_id, code, expected_version=echec.json()["version"])
    assert reprise.status_code in (200, 201), reprise.text
    assert reprise.json()["state"] == "active"
    assert len(appels) == 2, "un appel en échec puis un appel réussi"


async def test_ca5_activation_isolee_par_organisation(client, registered_user, organization):
    """CA-5 : activer un module pour l'organisation A ne modifie pas l'organisation B."""
    organisation_a = uuid.UUID(organization["id"])
    autre = await _inscrire(client)
    reponse_b = await client.post(
        "/api/v1/organizations",
        json={"name": "Org B BE-196", "slug": f"be196-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {autre['token']}"},
    )
    assert reponse_b.status_code < 300, reponse_b.text
    organisation_b = uuid.UUID(reponse_b.json()["id"])
    await _affecte_role_owner(str(organisation_b), autre["email"])

    code = _code()
    module_id = await _module_publie(code)
    await _entitlement_actif(organisation_a, code)
    await _entitlement_actif(organisation_b, code)
    appels = _hook(code)

    activation_a = await _activer(client, registered_user["accessToken"], organisation_a, code, expected_version=0)
    assert activation_a.json()["state"] == "active", activation_a.text
    assert await _ligne(organisation_b, code) is None
    ligne_a = await _ligne(organisation_a, code)

    activation_b = await _activer(client, autre["token"], organisation_b, code, expected_version=0)
    assert activation_b.json()["state"] == "active", activation_b.text

    assert [str(x) for x in appels] == [str(organisation_a), str(organisation_b)]
    assert await _ligne(organisation_a, code) == ligne_a, "la ligne de l'organisation A ne doit pas bouger"


async def test_ca6_chaque_activation_ecrit_audit_et_outbox(client, registered_user, organization):
    """CA-6 : chaque activation écrit une entrée d'audit et une entrée outbox."""
    organisation_id = uuid.UUID(organization["id"])
    code = _code()
    await _module_publie(code)
    await _entitlement_actif(organisation_id, code)
    _hook(code)
    token = registered_user["accessToken"]

    audit_avant = await _compte_audit(organisation_id)
    outbox_avant = await _compte_outbox(organisation_id)
    premiere = await _activer(client, token, organisation_id, code, expected_version=0)
    assert premiere.json()["state"] == "active", premiere.text
    assert await _compte_audit(organisation_id) > audit_avant, "entrée d'audit attendue (1re activation)"
    assert await _compte_outbox(organisation_id) > outbox_avant, "entrée outbox attendue (1re activation)"

    audit_avant = await _compte_audit(organisation_id)
    outbox_avant = await _compte_outbox(organisation_id)
    seconde = await _activer(client, token, organisation_id, code, expected_version=premiere.json()["version"])
    assert seconde.status_code in (200, 201), seconde.text
    assert await _compte_audit(organisation_id) > audit_avant, "entrée d'audit attendue (2e activation)"
    assert await _compte_outbox(organisation_id) > outbox_avant, "entrée outbox attendue (2e activation)"
