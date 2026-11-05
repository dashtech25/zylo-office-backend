"""BE-051 : mise à jour d'une installation de version rN vers rN+1.

Tests écrits d'après la définition (implementation-backend/tasks-modules-droits.md, section BE-051)
avant le code. La route est `POST /api/v1/organizations/{orgId}/modules/{moduleId}/upgrades` (en-tête
`Idempotency-Key` ; corps `targetModuleVersionId`, `stateVersion`, et `confirmationForwardOnly`
optionnel pour un plan sans retour arrière). Le service est
`app.modules_registry.mise_a_jour.executer_mise_a_jour`.

Le plan lu est celui de BE-044 (`module_upgrade_plans`), calculé ici par le service de compatibilité.
Le fournisseur de migration est injecté par les tests : aucun appel réseau, l'échec est simulé par une
exception levée par le fournisseur.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.core.idempotency import EN_TETE_IDEMPOTENCE
from app.identity.models import OrganizationUser
from app.modules_registry.compatibilite_service import planifier_mise_a_jour
from app.modules_registry.installation import executer_installation
from app.modules_registry.manifeste import VERSIONS_MANIFESTE_SUPPORTEES
from app.modules_registry.models import ModuleInstallation, ModuleVersion
from app.modules_registry.service import get_or_create_module

MOT_DE_PASSE = "TestPassword123!"
VERSION_SOURCE = "1.0.0"
VERSION_CIBLE = "1.1.0"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Le moteur est un singleton lié à la boucle asyncio : pool neuf avant et après chaque test."""
    await engine.dispose()
    yield
    await engine.dispose()


class FournisseurMigrationEnEchec:
    """Fournisseur de migration simulé : la migration échoue, rien n'est modifié côté fournisseur."""

    async def migrer(self, installation_id: uuid.UUID, source_id: uuid.UUID, cible_id: uuid.UUID) -> None:
        raise RuntimeError("migration simulée en échec")


def _code() -> str:
    return f"be051_{uuid.uuid4().hex[:10]}"


def _compatibilite(rollback_possible: bool = False, manifeste_inconnu: bool = False) -> dict:
    """Compatibilité d'une version ; `manifeste_inconnu` rend la version incompatible (BE-044)."""
    manifeste = 999 if manifeste_inconnu else max(VERSIONS_MANIFESTE_SUPPORTEES)
    return {"manifestVersion": manifeste, "rollbackPossible": rollback_possible}


async def _module_source_installe_et_plan(
    *,
    cible_publiee: bool = True,
    cible_incompatible: bool = False,
    rollback_possible: bool = False,
    avec_plan: bool = True,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Crée un module à deux versions, installe la source et calcule le plan source -> cible.

    Renvoie (module, version source, version cible). Le plan est écrit par le service BE-044 ; si
    `avec_plan` est faux, aucune ligne de plan n'existe pour ce couple."""
    code = _code()
    async with AsyncSessionLocal() as db:
        module = await get_or_create_module(db, code, f"Module {code}", "Module de test BE-051")
        source = ModuleVersion(
            moduleId=module.id,
            version=VERSION_SOURCE,
            digest="sha256:be051-source",
            provenance="test-be051",
            compatibility=_compatibilite(rollback_possible=rollback_possible),
            publicationState="published",
            publishedAt=datetime.now(timezone.utc),
        )
        cible = ModuleVersion(
            moduleId=module.id,
            version=VERSION_CIBLE,
            digest="sha256:be051-cible",
            provenance="test-be051",
            compatibility=_compatibilite(manifeste_inconnu=cible_incompatible),
            publicationState="published" if cible_publiee else "draft",
            publishedAt=datetime.now(timezone.utc) if cible_publiee else None,
        )
        db.add_all([source, cible])
        await db.commit()
        module_id, source_id, cible_id = module.id, source.id, cible.id

    if avec_plan:
        async with AsyncSessionLocal() as db:
            await planifier_mise_a_jour(db, module_id, from_version=VERSION_SOURCE, to_version=VERSION_CIBLE)
            await db.commit()
    return module_id, source_id, cible_id


async def _inscrire(client: AsyncClient) -> dict:
    """Crée un utilisateur réel ; renvoie son identifiant et son jeton d'accès."""
    email = f"be051-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    reponse = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-051"}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return {"id": uuid.UUID(reponse.json()["id"]), "token": login.json()["accessToken"]}


async def _organisation(client: AsyncClient, proprietaire: dict) -> str:
    """Crée une organisation dont `proprietaire` est propriétaire ; renvoie son identifiant."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Org BE-051", "slug": f"be051-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {proprietaire['token']}"},
    )
    assert res.status_code < 300, res.text
    return res.json()["id"]


async def _membre_sans_droit(client: AsyncClient, organisation_id: str) -> dict:
    """Crée un utilisateur rattaché à l'organisation, sans rôle ; renvoie son identifiant et son jeton."""
    membre = await _inscrire(client)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=membre["id"]))
        await db.commit()
    return membre


def _entete(token: str, organisation_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organisation_id}


def _url(organisation_id: str, module_id: uuid.UUID) -> str:
    return f"/api/v1/organizations/{organisation_id}/modules/{module_id}/upgrades"


def _corps(cible_id: uuid.UUID, state_version: int = 0, confirmation: bool | None = None) -> dict:
    corps = {"targetModuleVersionId": str(cible_id), "stateVersion": state_version}
    if confirmation is not None:
        corps["confirmationForwardOnly"] = confirmation
    return corps


async def _version_courante(module_id: uuid.UUID, organisation_id: str) -> int:
    """Lit la version d'état courante de l'installation : la commande doit la reprendre (BE-047 l'a
    portée à 3 après une installation réussie)."""
    return (await _etat_installation(module_id, organisation_id)).stateVersion


def _code_erreur(reponse) -> str:
    return reponse.json()["error"]["code"]


async def _etat_installation(module_id: uuid.UUID, organisation_id: str) -> ModuleInstallation:
    """Relit la ligne d'installation non retirée du couple, dans une session neuve."""
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(ModuleInstallation).where(
                    ModuleInstallation.moduleId == module_id,
                    ModuleInstallation.organizationId == uuid.UUID(organisation_id),
                    ModuleInstallation.state != "removed",
                )
            )
        ).scalar_one()


async def _installer_pour_organisation(
    module_id: uuid.UUID, source_id: uuid.UUID, organisation_id: str, acteur_id: uuid.UUID
) -> None:
    """Installe la version source pour une organisation réelle (le plan existe déjà pour le module).

    `acteur_id` doit être un utilisateur réel : le journal d'audit le référence par clé étrangère."""
    async with AsyncSessionLocal() as db:
        await executer_installation(
            db,
            organization_id=uuid.UUID(organisation_id),
            acteur_id=acteur_id,
            module_id=module_id,
            module_version_id=source_id,
            state_version=0,
            cle_idempotence=f"be051-org-{uuid.uuid4().hex}",
        )
        await db.commit()


# --- Refus préalables : version cible, compatibilité, plan -----------------------------------------


async def test_ca1_version_cible_non_publiee_renvoie_422(client: AsyncClient):
    """CA-1 : une mise à jour vers une version non publiée renvoie 422, sans changer l'installation."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, source_id, cible_id = await _module_source_installe_et_plan(cible_publiee=False)
    await _installer_pour_organisation(module_id, source_id, organisation_id, proprietaire["id"])

    reponse = await client.post(
        _url(organisation_id, module_id),
        json=_corps(cible_id, await _version_courante(module_id, organisation_id)),
        headers={**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert reponse.status_code == 422
    assert _code_erreur(reponse) == "MODULE_VERSION_NOT_PUBLISHED"
    assert (await _etat_installation(module_id, organisation_id)).moduleVersionId == source_id


async def test_ca2_mise_a_jour_incompatible_renvoie_409_et_reste_sur_la_source(client: AsyncClient):
    """CA-2 : une mise à jour incompatible renvoie 409 ; l'installation reste sur la version source."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, source_id, cible_id = await _module_source_installe_et_plan(cible_incompatible=True)
    await _installer_pour_organisation(module_id, source_id, organisation_id, proprietaire["id"])

    reponse = await client.post(
        _url(organisation_id, module_id),
        json=_corps(cible_id, await _version_courante(module_id, organisation_id)),
        headers={**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_UPGRADE_NOT_ALLOWED"
    installation = await _etat_installation(module_id, organisation_id)
    assert installation.moduleVersionId == source_id
    assert installation.state == "installed"


async def test_plan_absent_renvoie_409_mise_a_jour_non_autorisee(client: AsyncClient):
    """Définition BE-051 : sans plan BE-044 pour le couple source -> cible, la mise à jour est refusée."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, source_id, cible_id = await _module_source_installe_et_plan(avec_plan=False)
    await _installer_pour_organisation(module_id, source_id, organisation_id, proprietaire["id"])

    reponse = await client.post(
        _url(organisation_id, module_id),
        json=_corps(cible_id, await _version_courante(module_id, organisation_id)),
        headers={**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_UPGRADE_NOT_ALLOWED"
    assert (await _etat_installation(module_id, organisation_id)).moduleVersionId == source_id


async def test_plan_sans_retour_arriere_exige_une_confirmation_explicite(client: AsyncClient):
    """Définition BE-051 : plan `forwardOnly` sans confirmation -> 409 MODULE_UPGRADE_FORWARD_ONLY ;
    avec confirmation explicite, la mise à jour aboutit et l'installation porte la version cible."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, source_id, cible_id = await _module_source_installe_et_plan(rollback_possible=False)
    await _installer_pour_organisation(module_id, source_id, organisation_id, proprietaire["id"])
    entetes = {**_entete(proprietaire["token"], organisation_id)}

    sans_confirmation = await client.post(
        _url(organisation_id, module_id),
        json=_corps(cible_id, await _version_courante(module_id, organisation_id)),
        headers={**entetes, EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )
    assert sans_confirmation.status_code == 409
    assert _code_erreur(sans_confirmation) == "MODULE_UPGRADE_FORWARD_ONLY"
    assert (await _etat_installation(module_id, organisation_id)).moduleVersionId == source_id

    avec_confirmation = await client.post(
        _url(organisation_id, module_id),
        json=_corps(cible_id, await _version_courante(module_id, organisation_id), confirmation=True),
        headers={**entetes, EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )
    assert avec_confirmation.status_code == 200, avec_confirmation.text
    installation = await _etat_installation(module_id, organisation_id)
    assert installation.moduleVersionId == cible_id
    assert installation.state == "installed"


async def test_plan_avec_retour_arriere_prouve_ne_demande_pas_de_confirmation(client: AsyncClient):
    """Définition BE-051 : le rollback n'est autorisé automatiquement que si le plan le prouve possible ;
    un plan avec retour arrière prouvé n'exige donc pas la confirmation `forwardOnly`."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, source_id, cible_id = await _module_source_installe_et_plan(rollback_possible=True)
    await _installer_pour_organisation(module_id, source_id, organisation_id, proprietaire["id"])

    reponse = await client.post(
        _url(organisation_id, module_id),
        json=_corps(cible_id, await _version_courante(module_id, organisation_id)),
        headers={**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert reponse.status_code == 200, reponse.text
    assert (await _etat_installation(module_id, organisation_id)).moduleVersionId == cible_id


# --- CA-3 : échec de migration -> source active de façon cohérente, failed posé -------------------


async def test_ca3_echec_de_migration_pose_failed_et_garde_la_version_source(client: AsyncClient):
    """CA-3 : un échec de migration laisse la version source active (état `installed`, version source),
    pose `upgradeState = failed` et renseigne `lastErrorCode` ; aucun retour arrière automatique."""
    from app.modules_registry.mise_a_jour import executer_mise_a_jour

    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, source_id, cible_id = await _module_source_installe_et_plan(rollback_possible=True)
    await _installer_pour_organisation(module_id, source_id, organisation_id, proprietaire["id"])
    installation = await _etat_installation(module_id, organisation_id)

    async with AsyncSessionLocal() as db:
        try:
            resultat = await executer_mise_a_jour(
                db,
                organization_id=uuid.UUID(organisation_id),
                acteur_id=proprietaire["id"],
                module_id=module_id,
                target_module_version_id=cible_id,
                state_version=installation.stateVersion,
                cle_idempotence=f"be051-echec-{uuid.uuid4().hex}",
                fournisseur_migration=FournisseurMigrationEnEchec(),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    assert resultat.upgradeState == "failed"
    assert resultat.lastErrorCode == "MODULE_UPGRADE_FAILED"
    assert resultat.moduleVersionId == source_id
    assert resultat.state == "installed"


# --- CA-4 : droit d'upgrade ------------------------------------------------------------------------


async def test_ca4_acteur_sans_droit_de_mise_a_jour_recoit_403_sans_changement(client: AsyncClient):
    """CA-4 : un membre sans `organization.module.upgrade` reçoit 403 ; l'installation ne change pas."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, source_id, cible_id = await _module_source_installe_et_plan(rollback_possible=True)
    await _installer_pour_organisation(module_id, source_id, organisation_id, proprietaire["id"])
    membre = await _membre_sans_droit(client, organisation_id)

    reponse = await client.post(
        _url(organisation_id, module_id),
        json=_corps(cible_id, await _version_courante(module_id, organisation_id)),
        headers={**_entete(membre["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert reponse.status_code == 403
    assert (await _etat_installation(module_id, organisation_id)).moduleVersionId == source_id


# --- CA-5 : isolation entre organisations ----------------------------------------------------------


async def test_ca5_mise_a_jour_dans_une_autre_organisation_repond_404(client: AsyncClient):
    """CA-5 : un acteur de A qui met à jour dans B reçoit 404 ; l'installation de B ne change pas."""
    proprietaire_a = await _inscrire(client)
    org_a = await _organisation(client, proprietaire_a)
    proprietaire_b = await _inscrire(client)
    org_b = await _organisation(client, proprietaire_b)
    module_id, source_id, cible_id = await _module_source_installe_et_plan(rollback_possible=True)
    await _installer_pour_organisation(module_id, source_id, org_b, proprietaire_b["id"])

    reponse = await client.post(
        _url(org_b, module_id),
        json=_corps(cible_id, await _version_courante(module_id, org_b)),
        headers={**_entete(proprietaire_a["token"], org_a), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert reponse.status_code == 404
    assert (await _etat_installation(module_id, org_b)).moduleVersionId == source_id


# --- Garde de version d'état et en-tête d'idempotence ----------------------------------------------


async def test_version_d_etat_obsolete_renvoie_409(client: AsyncClient):
    """Une `stateVersion` différente de la version courante de l'installation renvoie 409."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, source_id, cible_id = await _module_source_installe_et_plan(rollback_possible=True)
    await _installer_pour_organisation(module_id, source_id, organisation_id, proprietaire["id"])
    version_courante = (await _etat_installation(module_id, organisation_id)).stateVersion

    reponse = await client.post(
        _url(organisation_id, module_id),
        json=_corps(cible_id, state_version=version_courante + 7),
        headers={**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_STATE_VERSION_CONFLICT"
    assert (await _etat_installation(module_id, organisation_id)).moduleVersionId == source_id


async def test_sans_en_tete_idempotency_key_la_mise_a_jour_est_refusee(client: AsyncClient):
    """L'en-tête `Idempotency-Key` est obligatoire (comme pour l'installation BE-047) : sans lui, refus
    sans aucune modification de l'installation."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, source_id, cible_id = await _module_source_installe_et_plan(rollback_possible=True)
    await _installer_pour_organisation(module_id, source_id, organisation_id, proprietaire["id"])

    reponse = await client.post(
        _url(organisation_id, module_id),
        json=_corps(cible_id, await _version_courante(module_id, organisation_id)),
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert 400 <= reponse.status_code < 500
    assert (await _etat_installation(module_id, organisation_id)).moduleVersionId == source_id
