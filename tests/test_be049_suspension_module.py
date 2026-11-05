"""BE-049 : suspension et reprise d'un module (tenant-module, disponibilité).

Tests écrits d'après la définition (implementation-backend/tasks-modules-droits.md, section BE-049)
avant le code. Routes attendues (préfixe `/api/v1/organizations/{orgId}/modules/{moduleId}`) :
- `POST .../suspensions` (corps `origin` parmi client|commercial|security, `reason`, `stateVersion`) ;
- `POST .../reactivations` (corps `stateVersion`, `resolutionReference`) ;
- `GET .../{moduleId}` (lecture de l'état, toujours disponible).

Droits (définition, « Droits ») : `organization.module.suspend` pour l'origine `client` ;
`platform.module.suspend` pour `commercial` et `security` (allowlist d'environnement
`PLATFORM_MODULE_SUSPEND_USER_IDS`, comme BE-042). La reprise revalide la permission de l'origine de
la suspension, la release, et l'entitlement.

Points de la définition non tranchés dans ces tests (voir le rapport de BE-049) :
- la matrice nomme un état `suspending` ; la machine à états (BE-041) n'en a pas. La suspension passe
  directement de `active` à `suspended` (transition déjà autorisée). Les tests vérifient `suspended` ;
- `resolutionReference` n'est pas dit obligatoire : il est exigé non vide ici et journalisé comme motif ;
- QE-MOD-06 : la lecture pendant `suspended` est autorisée par défaut (testée ci-dessous).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.billing import service as billing_service
from app.billing.models import Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser
from app.modules_registry.manifeste import VERSIONS_MANIFESTE_SUPPORTEES
from app.modules_registry.models import Module, ModuleInstallation, ModuleStateTransition, ModuleVersion
from app.modules_registry.service import get_or_create_module

MOT_DE_PASSE = "TestPassword123!"
PERMISSION_SUSPENSION_CLIENT = "organization.module.suspend"
VARIABLE_SUSPENSION_PLATEFORME = "PLATFORM_MODULE_SUSPEND_USER_IDS"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Le moteur est un singleton lié à la boucle asyncio : pool neuf avant et après chaque test."""
    await engine.dispose()
    yield
    await engine.dispose()


def _code() -> str:
    return f"be049_{uuid.uuid4().hex[:10]}"


async def _module_avec_version() -> tuple[uuid.UUID, uuid.UUID, str]:
    """Crée un module du catalogue et une version publiée compatible ; retourne (module, version, code)."""
    code = _code()
    async with AsyncSessionLocal() as db:
        module = await get_or_create_module(db, code, f"Module {code}", "Module de test BE-049")
        version = ModuleVersion(
            moduleId=module.id,
            version="1.0.0",
            digest="sha256:be049",
            provenance="test-be049",
            compatibility={"manifestVersion": max(VERSIONS_MANIFESTE_SUPPORTEES)},
            prerequisites=None,
            publicationState="published",
            publishedAt=datetime.now(timezone.utc),
        )
        db.add(version)
        await db.commit()
        return module.id, version.id, code


async def _inscrire(client: AsyncClient) -> dict:
    """Crée un utilisateur réel ; renvoie son identifiant et son jeton d'accès."""
    email = f"be049-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    reponse = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-049"}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return {"id": uuid.UUID(reponse.json()["id"]), "token": login.json()["accessToken"]}


async def _organisation(client: AsyncClient, proprietaire: dict) -> uuid.UUID:
    """Crée une organisation dont `proprietaire` est propriétaire ; renvoie son identifiant."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Org BE-049", "slug": f"be049-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {proprietaire['token']}"},
    )
    assert res.status_code < 300, res.text
    return uuid.UUID(res.json()["id"])


async def _membre_sans_droit(client: AsyncClient, organisation_id: uuid.UUID) -> dict:
    """Utilisateur rattaché à l'organisation, sans aucun rôle de module ; renvoie identifiant et jeton."""
    membre = await _inscrire(client)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organisation_id, userId=membre["id"]))
        await db.commit()
    return membre


async def _entitlement_actif(organisation_id: uuid.UUID, module_code: str) -> uuid.UUID:
    """Abonnement actif et entitlement effectif pour `module_code` (même forme que BE-045).

    Renvoie l'identifiant de la ligne d'entitlement, pour qu'un test puisse la dégrader."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await billing_service.get_or_create_plan(
            db, "zylo_liquid", f"be049-{uuid.uuid4().hex[:10]}", "Plan BE-049", 0, "XAF", 30
        )
        version = await billing_service.ensure_initial_plan_version(db, plan)
        abonnement = Subscription(
            organizationId=organisation_id, planId=plan.id, planVersionId=version.id,
            status="active", startDate=maintenant, endDate=maintenant + timedelta(days=30),
        )
        db.add(abonnement)
        await db.flush()
        ligne = SubscriptionEntitlement(
            organizationId=organisation_id, subscriptionId=abonnement.id, moduleCode=module_code,
            entitlementCode=f"be049.code.{uuid.uuid4().hex[:8]}", status="active",
            startsAt=maintenant, endsAt=maintenant + timedelta(days=30),
            sourceAttribution="offre", niveauApplication="organisation",
        )
        db.add(ligne)
        await db.commit()
        return ligne.id


async def _installer_et_activer(client: AsyncClient, proprietaire: dict, organisation_id: uuid.UUID,
                                module_id: uuid.UUID, version_id: uuid.UUID, code: str) -> None:
    """Installation technique puis activation par la route : le module est `active` au retour."""
    from app.modules_registry.installation import executer_installation

    async with AsyncSessionLocal() as db:
        await executer_installation(
            db, organization_id=organisation_id, acteur_id=proprietaire["id"], module_id=module_id,
            module_version_id=version_id, state_version=0, cle_idempotence=f"be049-{uuid.uuid4().hex[:8]}",
        )
        await db.commit()
    await _entitlement_actif(organisation_id, code)
    etat = await _etat(client, proprietaire, organisation_id, module_id)
    reponse = await client.post(
        _url(organisation_id, module_id, "activation"),
        json={"stateVersion": etat["stateVersion"], "confirm": True},
        headers=_entete(proprietaire["token"], organisation_id),
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["state"] == "active"


async def _etat(client: AsyncClient, acteur: dict, organisation_id: uuid.UUID, module_id: uuid.UUID) -> dict:
    """Lit l'état de disponibilité du module (GET, toujours autorisé pour l'acteur)."""
    reponse = await client.get(_url(organisation_id, module_id), headers=_entete(acteur["token"], organisation_id))
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


async def _lire_installation(organisation_id: uuid.UUID, module_id: uuid.UUID) -> ModuleInstallation:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(ModuleInstallation).where(
                    ModuleInstallation.organizationId == organisation_id,
                    ModuleInstallation.moduleId == module_id,
                    ModuleInstallation.state != "removed",
                )
            )
        ).scalar_one()


async def _journal(installation_id: uuid.UUID) -> list[tuple[str, str]]:
    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(
                select(ModuleStateTransition)
                .where(ModuleStateTransition.subjectId == installation_id)
                .order_by(ModuleStateTransition.stateVersionAfter)
            )
        ).scalars().all()
        return [(ligne.fromState, ligne.toState) for ligne in lignes]


def _url(organisation_id: uuid.UUID, module_id: uuid.UUID, action: str = "") -> str:
    base = f"/api/v1/organizations/{organisation_id}/modules/{module_id}"
    return f"{base}/{action}" if action else base


def _entete(token: str, organisation_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": str(organisation_id)}


def _code_erreur(reponse) -> str:
    return reponse.json()["error"]["code"]


async def _suspendre(client: AsyncClient, acteur: dict, organisation_id: uuid.UUID, module_id: uuid.UUID,
                     etat_version: int, origine: str = "client") -> object:
    """Pose une suspension par la route ; renvoie la réponse HTTP brute."""
    return await client.post(
        _url(organisation_id, module_id, "suspensions"),
        json={"origin": origine, "reason": "Impayé constaté (test BE-049)", "stateVersion": etat_version},
        headers=_entete(acteur["token"], organisation_id),
    )


async def _module_suspendu(client: AsyncClient, proprietaire: dict) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Module installé, activé puis suspendu par le propriétaire (origine client)."""
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _installer_et_activer(client, proprietaire, organisation_id, module_id, version_id, code)
    etat = await _etat(client, proprietaire, organisation_id, module_id)
    reponse = await _suspendre(client, proprietaire, organisation_id, module_id, etat["stateVersion"])
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["state"] == "suspended"
    return organisation_id, module_id, code


# --- CA-1 : une suspension sans origine ou sans motif renvoie 422 ------------------------------------


async def test_ca1_suspension_sans_origin_422_etat_inchange(client: AsyncClient):
    """CA-1 : sans `origin`, la suspension est refusée en 422 ; le module reste `active`."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _installer_et_activer(client, proprietaire, organisation_id, module_id, version_id, code)
    etat = await _etat(client, proprietaire, organisation_id, module_id)

    reponse = await client.post(
        _url(organisation_id, module_id, "suspensions"),
        json={"reason": "Motif présent, origine absente", "stateVersion": etat["stateVersion"]},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 422
    assert (await _lire_installation(organisation_id, module_id)).state == "active"


async def test_ca1_suspension_sans_reason_422_etat_inchange(client: AsyncClient):
    """CA-1 : sans `reason`, la suspension est refusée en 422 ; le module reste `active`."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _installer_et_activer(client, proprietaire, organisation_id, module_id, version_id, code)
    etat = await _etat(client, proprietaire, organisation_id, module_id)

    reponse = await client.post(
        _url(organisation_id, module_id, "suspensions"),
        json={"origin": "client", "stateVersion": etat["stateVersion"]},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 422
    assert (await _lire_installation(organisation_id, module_id)).state == "active"


# --- CA-2 : un acteur client ne peut pas poser une suspension `security` -----------------------------


async def test_ca2_acteur_client_ne_pose_pas_suspension_security_403(client: AsyncClient, monkeypatch):
    """CA-2 : le propriétaire (droits client) ne peut pas poser une suspension `security` : 403.

    Même avec `organization.module.suspend`, l'origine `security` exige le droit plateforme, que le
    propriétaire n'a pas dans l'allowlist. L'état reste `active`."""
    monkeypatch.setenv(VARIABLE_SUSPENSION_PLATEFORME, "")
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _installer_et_activer(client, proprietaire, organisation_id, module_id, version_id, code)
    etat = await _etat(client, proprietaire, organisation_id, module_id)

    reponse = await _suspendre(client, proprietaire, organisation_id, module_id, etat["stateVersion"], "security")

    assert reponse.status_code == 403
    assert (await _lire_installation(organisation_id, module_id)).state == "active"


async def test_ca2_membre_sans_droit_suspension_client_403(client: AsyncClient):
    """CA-2 : un membre sans `organization.module.suspend` reçoit 403 pour une suspension `client`."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _installer_et_activer(client, proprietaire, organisation_id, module_id, version_id, code)
    membre = await _membre_sans_droit(client, organisation_id)
    etat = await _etat(client, proprietaire, organisation_id, module_id)

    reponse = await _suspendre(client, membre, organisation_id, module_id, etat["stateVersion"], "client")

    assert reponse.status_code == 403
    assert (await _lire_installation(organisation_id, module_id)).state == "active"


# --- CA-3 : pendant `suspended`, mutation sensible refusée, lecture disponible -----------------------


async def test_ca3_suspendu_mutations_refusees_409_lecture_disponible(client: AsyncClient):
    """CA-3 : en `suspended`, désactivation et activation renvoient 409 MODULE_SUSPENDED ; la lecture
    de l'état reste accessible (200) et indique `suspended`. L'état ne change pas."""
    proprietaire = await _inscrire(client)
    organisation_id, module_id, _ = await _module_suspendu(client, proprietaire)
    etat = await _etat(client, proprietaire, organisation_id, module_id)

    desactivation = await client.post(
        _url(organisation_id, module_id, "deactivation"),
        json={"stateVersion": etat["stateVersion"], "confirm": True},
        headers=_entete(proprietaire["token"], organisation_id),
    )
    activation = await client.post(
        _url(organisation_id, module_id, "activation"),
        json={"stateVersion": etat["stateVersion"], "confirm": True},
        headers=_entete(proprietaire["token"], organisation_id),
    )
    lecture = await _etat(client, proprietaire, organisation_id, module_id)

    assert desactivation.status_code == 409
    assert _code_erreur(desactivation) == "MODULE_SUSPENDED"
    assert activation.status_code == 409
    assert _code_erreur(activation) == "MODULE_SUSPENDED"
    assert lecture["state"] == "suspended"
    assert (await _lire_installation(organisation_id, module_id)).state == "suspended"


# --- CA-4 : la reprise échoue si l'entitlement n'est plus `granted` ----------------------------------


async def test_ca4_reprise_refusee_si_entitlement_non_granted_etat_reste_suspended(client: AsyncClient):
    """CA-4 : après dégradation de l'entitlement (ligne non `active`), la reprise renvoie 409 et le
    module reste `suspended`. La projection BE-045 `active` équivaut au statut `granted` de la définition."""
    proprietaire = await _inscrire(client)
    organisation_id, module_id, code = await _module_suspendu(client, proprietaire)
    async with AsyncSessionLocal() as db:
        ligne = (
            await db.execute(
                select(SubscriptionEntitlement).where(
                    SubscriptionEntitlement.organizationId == organisation_id,
                    SubscriptionEntitlement.moduleCode == code,
                )
            )
        ).scalar_one()
        ligne.status = "suspended"
        await db.commit()
    etat = await _etat(client, proprietaire, organisation_id, module_id)

    reponse = await client.post(
        _url(organisation_id, module_id, "reactivations"),
        json={"stateVersion": etat["stateVersion"], "resolutionReference": "RES-BE049-CA4"},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 409
    assert (await _lire_installation(organisation_id, module_id)).state == "suspended"


# --- CA-5 : une reprise avec `stateVersion` obsolète renvoie 409 -------------------------------------


async def test_ca5_reprise_state_version_obsolete_409(client: AsyncClient):
    """CA-5 : une reprise avec une version d'état obsolète renvoie 409 MODULE_STATE_VERSION_CONFLICT."""
    proprietaire = await _inscrire(client)
    organisation_id, module_id, _ = await _module_suspendu(client, proprietaire)
    etat = await _etat(client, proprietaire, organisation_id, module_id)

    reponse = await client.post(
        _url(organisation_id, module_id, "reactivations"),
        json={"stateVersion": etat["stateVersion"] - 1, "resolutionReference": "RES-BE049-CA5"},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_STATE_VERSION_CONFLICT"
    assert (await _lire_installation(organisation_id, module_id)).state == "suspended"


# --- Droits et release de la reprise (définition, « Droits ») ----------------------------------------


async def test_reprise_revalide_la_permission_de_l_origine(client: AsyncClient, monkeypatch):
    """La reprise d'une suspension `commercial` exige le droit plateforme : sans lui, 403 ; l'état
    reste `suspended`. Le propriétaire est membre de l'allowlist pour la suspension seulement."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _installer_et_activer(client, proprietaire, organisation_id, module_id, version_id, code)
    monkeypatch.setenv(VARIABLE_SUSPENSION_PLATEFORME, str(proprietaire["id"]))
    etat = await _etat(client, proprietaire, organisation_id, module_id)
    suspension = await _suspendre(client, proprietaire, organisation_id, module_id, etat["stateVersion"], "commercial")
    assert suspension.status_code == 200, suspension.text

    monkeypatch.setenv(VARIABLE_SUSPENSION_PLATEFORME, "")
    etat = await _etat(client, proprietaire, organisation_id, module_id)
    reponse = await client.post(
        _url(organisation_id, module_id, "reactivations"),
        json={"stateVersion": etat["stateVersion"], "resolutionReference": "RES-BE049-DROIT"},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 403
    assert (await _lire_installation(organisation_id, module_id)).state == "suspended"


async def test_reprise_refusee_si_release_incompatible_etat_reste_suspended(client: AsyncClient):
    """La reprise revalide la release : une ligne de registre non supportée fait échouer la reprise
    (409) ; le module reste `suspended`."""
    proprietaire = await _inscrire(client)
    organisation_id, module_id, _ = await _module_suspendu(client, proprietaire)
    async with AsyncSessionLocal() as db:
        module = (await db.execute(select(Module).where(Module.id == module_id))).scalar_one()
        module.manifestVersion = "version-non-supportee-be049"
        await db.commit()
    etat = await _etat(client, proprietaire, organisation_id, module_id)

    reponse = await client.post(
        _url(organisation_id, module_id, "reactivations"),
        json={"stateVersion": etat["stateVersion"], "resolutionReference": "RES-BE049-RELEASE"},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 409
    assert (await _lire_installation(organisation_id, module_id)).state == "suspended"


# --- Parcours nominal : suspension puis reprise, journal et colonnes de suspension -------------------


async def test_suspension_puis_reprise_journal_et_colonnes(client: AsyncClient):
    """Suspension (origine client) puis reprise : états `active` à `suspended` à `active` journalisés ;
    les colonnes de suspension sont renseignées à la suspension, puis vidées à la reprise."""
    proprietaire = await _inscrire(client)
    organisation_id, module_id, _ = await _module_suspendu(client, proprietaire)

    installation = await _lire_installation(organisation_id, module_id)
    assert installation.suspensionOrigin == "client"
    assert installation.suspensionReason == "Impayé constaté (test BE-049)"
    assert installation.suspendedBy == proprietaire["id"]

    etat = await _etat(client, proprietaire, organisation_id, module_id)
    reponse = await client.post(
        _url(organisation_id, module_id, "reactivations"),
        json={"stateVersion": etat["stateVersion"], "resolutionReference": "RES-BE049-NOMINAL"},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["state"] == "active"
    installation = await _lire_installation(organisation_id, module_id)
    assert installation.state == "active"
    assert installation.suspensionOrigin is None
    assert installation.suspensionReason is None
    assert installation.suspendedBy is None
    journal = await _journal(installation.id)
    assert journal[-2:] == [("active", "suspended"), ("suspended", "active")]
