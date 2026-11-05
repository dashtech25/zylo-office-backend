"""BE-050 : désinstallation d'un module sans purge des données.

Tests écrits d'après la définition (implementation-backend/tasks-modules-droits.md, section BE-050)
avant le code. Service attendu dans `app.modules_registry.desinstallation` :
- `desinstaller_module(db, *, organization_id, acteur_id, module_id, state_version, confirm,
  cle_idempotence)` : passe `installed|inactive -> removing -> removed` ; ne purge aucune donnée.

Route : `DELETE /api/v1/organizations/{orgId}/modules/{moduleId}/installation` (en-tête
`Idempotency-Key` obligatoire ; corps `stateVersion`, `confirm`). Permission :
`organization.module.uninstall` (QE-MOD-16, code recommandé), distincte de `organization.module.activate`.

Points de la définition non tranchés dans ces tests :
- La définition ne fixe pas le code du 409 de garde `confirm` : les tests exigent un 409 sans code
  précis sur ce point (on vérifie seulement le statut et l'état inchangé).
- Le statut de succès n'est pas fixé ; les tests attendent 200 et la forme `ModuleInstallationResponse`.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.billing import service as billing_service
from app.billing.models import Subscription, SubscriptionEntitlement
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.core.idempotency import EN_TETE_IDEMPOTENCE
from app.identity.models import OrganizationUser
from app.modules.zylo_tanker.models import Vessel
from app.modules_registry.manifeste import VERSIONS_MANIFESTE_SUPPORTEES
from app.modules_registry.models import ModuleInstallation, ModuleStateTransition, ModuleVersion
from app.modules_registry.service import get_or_create_module
from app.modules_registry.transitions import TYPE_SUJET_INSTALLATION

MOT_DE_PASSE = "TestPassword123!"
PERMISSION_DESINSTALLATION = "organization.module.uninstall"
PERMISSION_ACTIVATION = "organization.module.activate"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Le moteur est un singleton lié à la boucle asyncio : pool neuf avant et après chaque test."""
    await engine.dispose()
    yield
    await engine.dispose()


def _code() -> str:
    return f"be050_{uuid.uuid4().hex[:10]}"


async def _module_avec_version(*, code: str | None = None) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Crée (ou reprend) un module du catalogue et une version publiée ; retourne (module, version, code)."""
    code = code or _code()
    async with AsyncSessionLocal() as db:
        module = await get_or_create_module(db, code, f"Module {code}", "Module de test BE-050")
        version = ModuleVersion(
            moduleId=module.id,
            version="1.0.0",
            digest="sha256:be050",
            provenance="test-be050",
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
    email = f"be050-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    reponse = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-050"}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return {"id": uuid.UUID(reponse.json()["id"]), "token": login.json()["accessToken"]}


async def _organisation(client: AsyncClient, proprietaire: dict) -> uuid.UUID:
    """Crée une organisation dont `proprietaire` est propriétaire ; renvoie son identifiant."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Org BE-050", "slug": f"be050-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {proprietaire['token']}"},
    )
    assert res.status_code < 300, res.text
    return uuid.UUID(res.json()["id"])


async def _membre_avec_permissions(
    client: AsyncClient, proprietaire: dict, organisation_id: uuid.UUID, permissions: list[str]
) -> dict:
    """Membre rattaché à l'organisation, avec un rôle custom ne portant que `permissions`."""
    from app.rbac.service import assign_role, create_role

    membre = await _inscrire(client)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organisation_id, userId=membre["id"]))
        await db.flush()
        role = await create_role(
            db, organisation_id, proprietaire["id"], f"be050-{uuid.uuid4().hex[:8]}", "Rôle BE-050", permissions
        )
        await assign_role(db, organisation_id, proprietaire["id"], membre["id"], role.id)
        await db.commit()
    return membre


async def _entitlement_actif(organisation_id: uuid.UUID, module_code: str) -> None:
    """Abonnement actif et entitlement effectif pour `module_code` (même forme que BE-045 et BE-048)."""
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        plan = await billing_service.get_or_create_plan(
            db, "zylo_liquid", f"be050-{uuid.uuid4().hex[:10]}", "Plan BE-050", 0, "XAF", 30
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
            entitlementCode=f"be050.code.{uuid.uuid4().hex[:8]}", status="active",
            startsAt=maintenant, endsAt=maintenant + timedelta(days=30),
            sourceAttribution="offre", niveauApplication="organisation",
        ))
        await db.commit()


async def _installer(organisation_id: uuid.UUID, acteur_id: uuid.UUID, module_id: uuid.UUID, version_id: uuid.UUID,
                     cle: str) -> dict:
    """Installation technique (BE-047) menée à `installed` par le service."""
    from app.modules_registry.installation import executer_installation

    async with AsyncSessionLocal() as db:
        installation = await executer_installation(
            db, organization_id=organisation_id, acteur_id=acteur_id, module_id=module_id,
            module_version_id=version_id, state_version=0, cle_idempotence=cle,
        )
        resultat = {"id": installation.id, "state": installation.state, "stateVersion": installation.stateVersion}
        await db.commit()
    return resultat


async def _activer(organisation_id: uuid.UUID, acteur_id: uuid.UUID, module_id: uuid.UUID, state_version: int) -> int:
    """Active le module (BE-048) ; renvoie la version d'état après activation."""
    from app.modules_registry.disponibilite import executer_activation

    async with AsyncSessionLocal() as db:
        installation = await executer_activation(
            db, organization_id=organisation_id, acteur_id=acteur_id, module_id=module_id,
            state_version=state_version, confirm=True,
        )
        version = installation.stateVersion
        await db.commit()
    return version


async def _lire_installation(organisation_id: uuid.UUID, module_id: uuid.UUID) -> ModuleInstallation:
    """Dernière installation du couple (organisation, module), y compris `removed`."""
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(ModuleInstallation)
                .where(ModuleInstallation.organizationId == organisation_id, ModuleInstallation.moduleId == module_id)
                .order_by(ModuleInstallation.createdAt.desc())
                .limit(1)
            )
        ).scalar_one()


async def _journal(installation_id: uuid.UUID) -> list[tuple[str, str]]:
    """Transitions journalisées du sujet, dans l'ordre : liste de (de_etat, vers_etat)."""
    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(
                select(ModuleStateTransition)
                .where(ModuleStateTransition.subjectType == TYPE_SUJET_INSTALLATION,
                       ModuleStateTransition.subjectId == installation_id)
                .order_by(ModuleStateTransition.stateVersionAfter)
            )
        ).scalars().all()
        return [(ligne.fromState, ligne.toState) for ligne in lignes]


async def _nombre_lignes_vessel(organisation_id: uuid.UUID) -> int:
    """Nombre de lignes de données d'un module (ici `zyloTankerVessel`) pour l'organisation."""
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(func.count()).select_from(Vessel).where(Vessel.organizationId == organisation_id))
        ).scalar_one()


def _url(organisation_id: uuid.UUID, module_id: uuid.UUID) -> str:
    return f"/api/v1/organizations/{organisation_id}/modules/{module_id}/installation"


def _entete(token: str, organisation_id: uuid.UUID, cle: str | None = None) -> dict:
    entete = {"Authorization": f"Bearer {token}", "X-Organization-Id": str(organisation_id)}
    if cle is not None:
        entete[EN_TETE_IDEMPOTENCE] = cle
    return entete


async def _desinstaller(client: AsyncClient, token: str, organisation_id: uuid.UUID, module_id: uuid.UUID,
                        state_version: int, cle: str, confirm: bool = True):
    return await client.request(
        "DELETE",
        _url(organisation_id, module_id),
        json={"stateVersion": state_version, "confirm": confirm},
        headers=_entete(token, organisation_id, cle),
    )


def _code_erreur(reponse) -> str:
    return reponse.json()["error"]["code"]


# --- CA-1 : un module `active` ne se désinstalle pas -----------------------------------------------


async def test_ca1_module_active_refuse_409_et_aucun_etat_change(client: AsyncClient):
    """CA-1 : désinstaller un module `active` renvoie 409 MODULE_MUST_BE_INACTIVE ; rien ne change."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _entitlement_actif(organisation_id, code)
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "ca1-install")
    version_active = await _activer(organisation_id, proprietaire["id"], module_id, installee["stateVersion"])
    avant = await _lire_installation(organisation_id, module_id)
    assert avant.state == "active"

    reponse = await _desinstaller(client, proprietaire["token"], organisation_id, module_id, version_active, "ca1-del")

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_MUST_BE_INACTIVE"
    apres = await _lire_installation(organisation_id, module_id)
    assert apres.state == "active"
    assert apres.stateVersion == version_active


# --- CA-2 : les données du module restent présentes après `removed` ------------------------------


async def test_ca2_apres_removed_les_lignes_de_donnees_restent_identiques(client: AsyncClient):
    """CA-2 : après `removed`, le nombre de lignes de données du module est inchangé ; aucune purge."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, _ = await _module_avec_version(code="zylo_tanker")
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "ca2-install")
    async with AsyncSessionLocal() as db:
        db.add(Vessel(organizationId=organisation_id, name="Navire BE-050", code=f"BE050-{uuid.uuid4().hex[:6]}"))
        await db.commit()
    lignes_avant = await _nombre_lignes_vessel(organisation_id)
    assert lignes_avant == 1

    reponse = await _desinstaller(
        client, proprietaire["token"], organisation_id, module_id, installee["stateVersion"], "ca2-del"
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["state"] == "removed"
    assert await _nombre_lignes_vessel(organisation_id) == lignes_avant


# --- CA-3 : droit de désinstallation distinct de l'activation ------------------------------------


async def test_ca3_acteur_qui_peut_desactiver_sans_le_droit_de_desinstaller_recoit_403(client: AsyncClient):
    """CA-3 : un membre qui a `organization.module.activate` mais pas `organization.module.uninstall`
    reçoit 403 ; l'installation reste `inactive`."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _entitlement_actif(organisation_id, code)
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "ca3-install")
    version_active = await _activer(organisation_id, proprietaire["id"], module_id, installee["stateVersion"])
    async with AsyncSessionLocal() as db:
        from app.modules_registry.disponibilite import executer_desactivation

        await executer_desactivation(
            db, organization_id=organisation_id, acteur_id=proprietaire["id"], module_id=module_id,
            state_version=version_active, confirm=True,
        )
        await db.commit()
    avant = await _lire_installation(organisation_id, module_id)
    assert avant.state == "inactive"
    membre = await _membre_avec_permissions(client, proprietaire, organisation_id, [PERMISSION_ACTIVATION])

    reponse = await _desinstaller(client, membre["token"], organisation_id, module_id, avant.stateVersion, "ca3-del")

    assert reponse.status_code == 403
    apres = await _lire_installation(organisation_id, module_id)
    assert apres.state == "inactive"
    assert apres.stateVersion == avant.stateVersion


# --- CA-4 : rejeu de la même Idempotency-Key -----------------------------------------------------


async def test_ca4_rejeu_de_la_meme_cle_ne_repasse_pas_en_removing(client: AsyncClient):
    """CA-4 : rejouer la même `Idempotency-Key` renvoie la réponse initiale ; le journal ne contient
    qu'un seul passage en `removing`."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, _ = await _module_avec_version()
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "ca4-install")
    corps_version = installee["stateVersion"]

    premiere = await _desinstaller(client, proprietaire["token"], organisation_id, module_id, corps_version, "ca4-rejeu")
    rejeu = await _desinstaller(client, proprietaire["token"], organisation_id, module_id, corps_version, "ca4-rejeu")

    assert premiere.status_code == 200, premiere.text
    assert rejeu.status_code == premiere.status_code
    assert rejeu.json() == premiere.json()
    journal = await _journal(installee["id"])
    assert journal.count(("installed", "removing")) == 1
    assert [etat for _, etat in journal].count("removing") == 1


# --- CA-5 : isolation entre organisations --------------------------------------------------------


async def test_ca5_desinstaller_dans_une_autre_organisation_repond_404(client: AsyncClient):
    """CA-5 : un acteur de A qui désinstalle dans `orgId = B` reçoit 404 ; l'installation de B reste."""
    proprietaire_a = await _inscrire(client)
    await _organisation(client, proprietaire_a)
    proprietaire_b = await _inscrire(client)
    organisation_b = await _organisation(client, proprietaire_b)
    module_id, version_id, _ = await _module_avec_version()
    installee = await _installer(organisation_b, proprietaire_b["id"], module_id, version_id, "ca5-b")

    reponse = await _desinstaller(
        client, proprietaire_a["token"], organisation_b, module_id, installee["stateVersion"], "ca5-del"
    )

    assert reponse.status_code == 404
    assert (await _lire_installation(organisation_b, module_id)).state == "installed"


# --- Garde de confirmation, version d'état et séquence nominale ----------------------------------


async def test_confirmation_absente_refusee_et_etat_inchange(client: AsyncClient):
    """Sans `confirm: true`, la désinstallation est refusée en 409 ; l'état ne change pas."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, _ = await _module_avec_version()
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "conf-install")

    reponse = await _desinstaller(
        client, proprietaire["token"], organisation_id, module_id, installee["stateVersion"], "conf-del", confirm=False
    )

    assert reponse.status_code == 409
    assert (await _lire_installation(organisation_id, module_id)).state == "installed"


async def test_version_d_etat_obsolete_refusee_409(client: AsyncClient):
    """Une `stateVersion` différente de la version courante renvoie 409 MODULE_STATE_VERSION_CONFLICT."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, _ = await _module_avec_version()
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "obs-install")

    reponse = await _desinstaller(
        client, proprietaire["token"], organisation_id, module_id, installee["stateVersion"] + 5, "obs-del"
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_STATE_VERSION_CONFLICT"
    assert (await _lire_installation(organisation_id, module_id)).state == "installed"


async def test_sequence_nominale_installed_vers_removing_vers_removed(client: AsyncClient):
    """Désinstallation d'un module `installed` : journal `installed -> removing -> removed`, ligne
    conservée, aucune installation non retirée restante pour le couple."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, _ = await _module_avec_version()
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "seq-install")

    reponse = await _desinstaller(
        client, proprietaire["token"], organisation_id, module_id, installee["stateVersion"], "seq-del"
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["state"] == "removed"
    journal = await _journal(installee["id"])
    assert journal[-2:] == [("installed", "removing"), ("removing", "removed")]
    async with AsyncSessionLocal() as db:
        restantes = (
            await db.execute(
                select(func.count()).select_from(ModuleInstallation).where(
                    ModuleInstallation.organizationId == organisation_id,
                    ModuleInstallation.moduleId == module_id,
                    ModuleInstallation.state != "removed",
                )
            )
        ).scalar_one()
    assert restantes == 0


async def test_service_refuse_un_module_active_sans_ecriture(client: AsyncClient):
    """Niveau service : un module `active` lève AppError 409 et ne journalise aucune transition."""
    from app.modules_registry.desinstallation import desinstaller_module

    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id, code = await _module_avec_version()
    await _entitlement_actif(organisation_id, code)
    installee = await _installer(organisation_id, proprietaire["id"], module_id, version_id, "svc-install")
    version_active = await _activer(organisation_id, proprietaire["id"], module_id, installee["stateVersion"])
    journal_avant = await _journal(installee["id"])

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as exc:
            await desinstaller_module(
                db, organization_id=organisation_id, acteur_id=proprietaire["id"], module_id=module_id,
                state_version=version_active, confirm=True, cle_idempotence="svc-del",
            )
        await db.rollback()

    assert exc.value.status_code == 409
    assert await _journal(installee["id"]) == journal_avant
