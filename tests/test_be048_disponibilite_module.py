"""BE-048 : disponibilité tenant-module (activation et désactivation).

Tests écrits d'après la définition (implementation-backend/tasks-modules-droits.md, section BE-048)
avant le code. Services attendus dans `app.modules_registry.disponibilite` :
- `executer_activation(db, *, organization_id, acteur_id, module_id, state_version, confirm,
  fournisseur=None)` ; `fournisseur` a une méthode `activer(installation_id, module_version_id)` ;
- `executer_desactivation(db, *, organization_id, acteur_id, module_id, state_version, confirm)`.

Routes : `POST .../modules/{moduleId}/activation`, `POST .../modules/{moduleId}/deactivation`
(corps `stateVersion`, `confirm`) et `GET .../modules/{moduleId}` (état et explication).
Permission d'activation : `organization.module.activate` (QE-MOD-16, code recommandé).

Points de la définition non tranchés dans ces tests (voir le rapport de BE-048) :
- CA-1 écrit « non `installed` » ; la matrice admet aussi `inactive` -> `active` (réactivation).
  Les tests admettent `installed` et `inactive` ; une installation `failed` est refusée.
- CA-2 : l'entitlement exigé est lu via `billing` (BE-045) ; sans entitlement actif, aucun accès
  implicite. La capacité qui l'exige reste NON DÉFINI (QE-MOD-13) : la règle s'applique à tout module.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.billing import service as billing_service
from app.billing.models import Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.identity.models import OrganizationUser
from app.modules_registry.manifeste import VERSIONS_MANIFESTE_SUPPORTEES
from app.modules_registry.models import ModuleInstallation, ModuleStateTransition, ModuleVersion
from app.modules_registry.service import get_or_create_module
from app.modules_registry.transitions import TYPE_SUJET_INSTALLATION, transition_autorisee

MOT_DE_PASSE = "TestPassword123!"
PERMISSION_ACTIVATION = "organization.module.activate"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Le moteur est un singleton lié à la boucle asyncio : pool neuf avant et après chaque test."""
    await engine.dispose()
    yield
    await engine.dispose()


class FournisseurActivationEnEchec:
    """Fournisseur d'activation simulé : chaque activation échoue (panne pendant `activation_pending`)."""

    async def activer(self, installation_id: uuid.UUID, module_version_id: uuid.UUID) -> None:
        raise RuntimeError("activation simulée en échec")


def _code() -> str:
    return f"be048_{uuid.uuid4().hex[:10]}"


async def _module_avec_version(*, prerequisites: list | None = None) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Crée un module du catalogue et une version publiée compatible ; retourne (module, version, code)."""
    code = _code()
    async with AsyncSessionLocal() as db:
        module = await get_or_create_module(db, code, f"Module {code}", "Module de test BE-048")
        version = ModuleVersion(
            moduleId=module.id,
            version="1.0.0",
            digest="sha256:be048",
            provenance="test-be048",
            compatibility={"manifestVersion": max(VERSIONS_MANIFESTE_SUPPORTEES)},
            prerequisites=prerequisites,
            publicationState="published",
            publishedAt=datetime.now(timezone.utc),
        )
        db.add(version)
        await db.commit()
        return module.id, version.id, code


async def _inscrire(client: AsyncClient) -> dict:
    """Crée un utilisateur réel ; renvoie son identifiant et son jeton d'accès."""
    email = f"be048-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    reponse = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-048"}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return {"id": uuid.UUID(reponse.json()["id"]), "token": login.json()["accessToken"]}


async def _organisation(client: AsyncClient, proprietaire: dict) -> uuid.UUID:
    """Crée une organisation dont `proprietaire` est propriétaire ; renvoie son identifiant."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Org BE-048", "slug": f"be048-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {proprietaire['token']}"},
    )
    assert res.status_code < 300, res.text
    return uuid.UUID(res.json()["id"])


async def _membre_sans_droit(client: AsyncClient, organisation_id: uuid.UUID) -> dict:
    """Utilisateur rattaché à l'organisation, sans rôle d'activation ; renvoie identifiant et jeton."""
    membre = await _inscrire(client)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organisation_id, userId=membre["id"]))
        await db.commit()
    return membre


async def _entitlement_actif(organisation_id: uuid.UUID, module_code: str) -> None:
    """Abonnement actif et entitlement effectif pour `module_code` (même forme que BE-045)."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await billing_service.get_or_create_plan(
            db, "zylo_liquid", f"be048-{uuid.uuid4().hex[:10]}", "Plan BE-048", 0, "XAF", 30
        )
        version = await billing_service.ensure_initial_plan_version(db, plan)
        abonnement = Subscription(
            organizationId=organisation_id, planId=plan.id, planVersionId=version.id,
            status="active", startDate=maintenant, endDate=maintenant + timedelta(days=30),
        )
        db.add(abonnement)
        await db.flush()
        db.add(SubscriptionEntitlement(
            organizationId=organisation_id, subscriptionId=abonnement.id, moduleCode=module_code,
            entitlementCode=f"be048.code.{uuid.uuid4().hex[:8]}", status="active",
            startsAt=maintenant, endsAt=maintenant + timedelta(days=30),
            sourceAttribution="offre", niveauApplication="organisation",
        ))
        await db.commit()


async def _installer(organisation_id: uuid.UUID, acteur_id: uuid.UUID, module_id: uuid.UUID, version_id: uuid.UUID,
                     cle: str, fournisseur=None) -> dict:
    """Installation technique (BE-047) menée à `installed` ou `failed`, par le service."""
    from app.modules_registry.installation import executer_installation

    async with AsyncSessionLocal() as db:
        installation = await executer_installation(
            db, organization_id=organisation_id, acteur_id=acteur_id, module_id=module_id,
            module_version_id=version_id, state_version=0, cle_idempotence=cle, fournisseur=fournisseur,
        )
        resultat = {"id": installation.id, "state": installation.state, "stateVersion": installation.stateVersion}
        await db.commit()
    return resultat


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


async def _activer_service(organisation_id: uuid.UUID, acteur_id: uuid.UUID, module_id: uuid.UUID,
                           state_version: int, fournisseur=None) -> dict:
    """Appelle le service d'activation et valide la transaction ; renvoie l'état lu avant commit."""
    from app.modules_registry.disponibilite import executer_activation

    async with AsyncSessionLocal() as db:
        try:
            installation = await executer_activation(
                db, organization_id=organisation_id, acteur_id=acteur_id, module_id=module_id,
                state_version=state_version, confirm=True, fournisseur=fournisseur,
            )
            resultat = {"state": installation.state, "stateVersion": installation.stateVersion,
                        "lastErrorCode": installation.lastErrorCode}
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return resultat


def _url(organisation_id: uuid.UUID, module_id: uuid.UUID, action: str = "") -> str:
    base = f"/api/v1/organizations/{organisation_id}/modules/{module_id}"
    return f"{base}/{action}" if action else base


def _entete(token: str, organisation_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": str(organisation_id)}


def _code_erreur(reponse) -> str:
    return reponse.json()["error"]["code"]


# --- CA-1 : activation refusée si l'installation n'est pas dans un état activable --------------------


async def test_ca1_installation_failed_refusee_409_etat_inchange(client: AsyncClient):
    """CA-1 : une installation `failed` ne peut pas être activée ; 409 et l'état reste inchangé."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _entitlement_actif(organisation_id, code)
    from app.modules_registry.installation import FournisseurSimule  # noqa: F401  (import de contrôle)

    class EchecProvisionnement:
        async def provisionner(self, installation_id, module_version_id):
            raise RuntimeError("provisionnement simulé en échec")

    avant = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "ca1-failed",
                             fournisseur=EchecProvisionnement())
    assert avant["state"] == "failed"

    with pytest.raises(AppError) as exc:
        await _activer_service(organisation_id, proprietaire["id"], module_id, avant["stateVersion"])

    assert exc.value.status_code == 409
    apres = await _lire_installation(organisation_id, module_id)
    assert apres.state == "failed"
    assert apres.stateVersion == avant["stateVersion"]


# --- CA-2 : pas d'accès implicite sans entitlement ---------------------------------------------------


async def test_ca2_sans_entitlement_409_entitlement_required_etat_inchange(client: AsyncClient):
    """CA-2 : sans entitlement valide, l'activation renvoie 409 ENTITLEMENT_REQUIRED ; l'état ne change pas."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, _ = await _module_avec_version()
    avant = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "ca2-sans-entitlement")

    reponse = await client.post(
        _url(organisation_id, module_id, "activation"),
        json={"stateVersion": avant["stateVersion"], "confirm": True},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "ENTITLEMENT_REQUIRED"
    apres = await _lire_installation(organisation_id, module_id)
    assert apres.state == "installed"
    assert apres.state != "active"


# --- CA-3 : droit d'activation requis ----------------------------------------------------------------


async def test_ca3_acteur_sans_droit_d_activation_403(client: AsyncClient):
    """CA-3 : un membre sans `organization.module.activate` reçoit 403 ; aucun état modifié."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _entitlement_actif(organisation_id, code)
    avant = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "ca3-droit")
    membre = await _membre_sans_droit(client, organisation_id)

    reponse = await client.post(
        _url(organisation_id, module_id, "activation"),
        json={"stateVersion": avant["stateVersion"], "confirm": True},
        headers=_entete(membre["token"], organisation_id),
    )

    assert reponse.status_code == 403
    assert (await _lire_installation(organisation_id, module_id)).state == "installed"


# --- CA-4 : désactivation bloquée par un dépendant actif --------------------------------------------


async def test_ca4_desactivation_avec_dependant_actif_409_liste_des_dependants(client: AsyncClient):
    """CA-4 : désactiver A alors que B (qui requiert A) est `active` renvoie 409
    MODULE_HAS_ACTIVE_DEPENDANTS, avec B dans le corps ; A reste `active`."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_a, version_a, code_a = await _module_avec_version()
    await _entitlement_actif(organisation_id, code_a)
    await _installer(organisation_id, proprietaire["id"], module_a, version_a, "ca4-a")
    await _activer_service(organisation_id, proprietaire["id"], module_a, 0)
    module_b, version_b, code_b = await _module_avec_version(prerequisites=[{"code": code_a}])
    await _entitlement_actif(organisation_id, code_b)
    await _installer(organisation_id, proprietaire["id"], module_b, version_b, "ca4-b")
    await _activer_service(organisation_id, proprietaire["id"], module_b, 0)
    avant_a = await _lire_installation(organisation_id, module_a)

    reponse = await client.post(
        _url(organisation_id, module_a, "deactivation"),
        json={"stateVersion": avant_a.stateVersion, "confirm": True},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_HAS_ACTIVE_DEPENDANTS"
    dependants = reponse.json()["error"]["details"]
    assert any(dependant.get("moduleCode") == code_b for dependant in dependants)
    assert (await _lire_installation(organisation_id, module_a)).state == "active"


# --- CA-5 : panne pendant activation_pending -> inactive_error, jamais active par défaut -------------


async def test_ca5_panne_pendant_activation_pending_etat_inactive_error(client: AsyncClient):
    """CA-5 : une panne pendant `activation_pending` place l'installation en `inactive_error` ; la
    relecture renvoie cet état exact, jamais `active`."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _entitlement_actif(organisation_id, code)
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "ca5-installation")

    resultat = await _activer_service(
        organisation_id, proprietaire["id"], module_id, installee["stateVersion"],
        fournisseur=FournisseurActivationEnEchec(),
    )

    assert resultat["state"] == "inactive_error"
    assert resultat["lastErrorCode"] is not None
    relecture = await client.get(
        _url(organisation_id, module_id), headers=_entete(proprietaire["token"], organisation_id)
    )
    assert relecture.status_code == 200
    assert relecture.json()["state"] == "inactive_error"
    assert relecture.json()["state"] != "active"


# --- CA-6 : isolation tenant --------------------------------------------------------------------------


async def test_ca6_activation_dans_une_autre_organisation_404(client: AsyncClient):
    """CA-6 : un acteur de A qui active dans `orgId = B` reçoit 404 ; l'installation de B reste inchangée."""
    proprietaire_a = await _inscrire(client)
    await _organisation(client, proprietaire_a)
    proprietaire_b = await _inscrire(client)
    organisation_b = await _organisation(client, proprietaire_b)
    module_id, version_id, code = await _module_avec_version()
    await _entitlement_actif(organisation_b, code)
    installee = await _installer(organisation_b, proprietaire_b["id"], module_id, version_id, "ca6-b")

    reponse = await client.post(
        _url(organisation_b, module_id, "activation"),
        json={"stateVersion": installee["stateVersion"], "confirm": True},
        headers=_entete(proprietaire_a["token"], organisation_b),
    )

    assert reponse.status_code == 404
    assert (await _lire_installation(organisation_b, module_id)).state == "installed"


# --- Gardes et séquences complémentaires -------------------------------------------------------------


async def test_activation_nominale_passe_par_activation_pending_et_journal(client: AsyncClient):
    """Activation réussie : installed -> activation_pending -> active, journalisé, état `active`."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _entitlement_actif(organisation_id, code)
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "nominal")

    reponse = await client.post(
        _url(organisation_id, module_id, "activation"),
        json={"stateVersion": installee["stateVersion"], "confirm": True},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["state"] == "active"
    journal = await _journal(installee["id"])
    assert journal[-2:] == [("installed", "activation_pending"), ("activation_pending", "active")]


async def test_version_d_etat_obsolete_409(client: AsyncClient):
    """Un `stateVersion` différent de la version courante renvoie 409 MODULE_STATE_VERSION_CONFLICT."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _entitlement_actif(organisation_id, code)
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "obsolete")

    reponse = await client.post(
        _url(organisation_id, module_id, "activation"),
        json={"stateVersion": installee["stateVersion"] + 7, "confirm": False},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_STATE_VERSION_CONFLICT"


async def test_confirmation_absente_garde_en_echec_409(client: AsyncClient):
    """Sans `confirm: true`, la garde de confirmation échoue : 409 MODULE_ACTIVATION_GUARD_FAILED."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _entitlement_actif(organisation_id, code)
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "sans-confirm")

    reponse = await client.post(
        _url(organisation_id, module_id, "activation"),
        json={"stateVersion": installee["stateVersion"], "confirm": False},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_ACTIVATION_GUARD_FAILED"
    assert reponse.json()["error"]["details"][0]["guard"] == "confirmation"
    assert (await _lire_installation(organisation_id, module_id)).state == "installed"


async def test_dependance_non_active_garde_dependencies_409(client: AsyncClient):
    """Activer B alors que son prérequis A n'est pas `active` : 409 MODULE_ACTIVATION_GUARD_FAILED,
    garde `dependencies`, et B reste `installed`."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_a, version_a, code_a = await _module_avec_version()
    await _installer(organisation_id, proprietaire["id"], module_a, version_a, "dep-a")
    module_b, version_b, code_b = await _module_avec_version(prerequisites=[{"code": code_a}])
    await _entitlement_actif(organisation_id, code_b)
    installee_b = await _installer(organisation_id, proprietaire["id"], module_b, version_b, "dep-b")

    reponse = await client.post(
        _url(organisation_id, module_b, "activation"),
        json={"stateVersion": installee_b["stateVersion"], "confirm": True},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_ACTIVATION_GUARD_FAILED"
    assert reponse.json()["error"]["details"][0]["guard"] == "dependencies"
    assert (await _lire_installation(organisation_id, module_b)).state == "installed"


async def test_desactivation_nominale_active_vers_inactive(client: AsyncClient):
    """Désactivation d'un module `active` sans dépendant actif : état `inactive`, journal `active -> inactive`."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _entitlement_actif(organisation_id, code)
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "desactiv")
    await _activer_service(organisation_id, proprietaire["id"], module_id, installee["stateVersion"])
    avant = await _lire_installation(organisation_id, module_id)

    reponse = await client.post(
        _url(organisation_id, module_id, "deactivation"),
        json={"stateVersion": avant.stateVersion, "confirm": True},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["state"] == "inactive"
    assert (await _journal(installee["id"]))[-1] == ("active", "inactive")


async def test_lecture_etat_de_disponibilite_et_explication(client: AsyncClient):
    """GET du module : renvoie l'état courant et une explication non vide."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, _ = await _module_avec_version()
    await _installer(organisation_id, proprietaire["id"], module_id, version_id, "lecture")

    reponse = await client.get(_url(organisation_id, module_id), headers=_entete(proprietaire["token"], organisation_id))

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["state"] == "installed"
    assert reponse.json()["explanation"]


def test_transitions_d_activation_autorisees_et_saut_interdit():
    """Table BE-041 étendue : installed/inactive -> activation_pending -> active | inactive_error ;
    le saut direct depuis `not_installed` reste interdit."""
    assert transition_autorisee(TYPE_SUJET_INSTALLATION, "installed", "activation_pending")
    assert transition_autorisee(TYPE_SUJET_INSTALLATION, "inactive", "activation_pending")
    assert transition_autorisee(TYPE_SUJET_INSTALLATION, "activation_pending", "active")
    assert transition_autorisee(TYPE_SUJET_INSTALLATION, "activation_pending", "inactive_error")
    assert transition_autorisee(TYPE_SUJET_INSTALLATION, "inactive_error", "activation_pending")
    assert not transition_autorisee(TYPE_SUJET_INSTALLATION, "not_installed", "activation_pending")
    assert not transition_autorisee(TYPE_SUJET_INSTALLATION, "failed", "activation_pending")


async def test_sans_entitlement_d_un_autre_module_ne_donne_pas_acces(client: AsyncClient):
    """Un entitlement actif pour un AUTRE module ne vaut pas accès : CA-2 reste refusé."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, _ = await _module_avec_version()
    await _entitlement_actif(organisation_id, _code())
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "autre-module")

    reponse = await client.post(
        _url(organisation_id, module_id, "activation"),
        json={"stateVersion": installee["stateVersion"], "confirm": True},
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "ENTITLEMENT_REQUIRED"
