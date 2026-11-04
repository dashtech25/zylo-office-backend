"""BE-047 : installation technique d'un module pour un tenant.

Tests écrits d'après la définition (implementation-backend/tasks-modules-droits.md, section BE-047)
avant le code. Le service est `app.modules_registry.installation.executer_installation` ; les routes
sont `POST /api/v1/organizations/{orgId}/modules/{moduleId}/installations` (en-tête
`Idempotency-Key`) et `GET .../installations/{operationId}`.

Fournisseur d'exécution : les tests injectent un fournisseur enregistreur ou en échec. Aucun appel
réseau n'est fait ; l'échec de provisionnement est simulé par une exception levée par le fournisseur.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.core.idempotency import EN_TETE_IDEMPOTENCE
from app.identity.models import OrganizationUser
from app.modules_registry.manifeste import VERSIONS_MANIFESTE_SUPPORTEES
from app.modules_registry.models import ModuleInstallation, ModuleStateTransition, ModuleVersion
from app.modules_registry.service import get_or_create_module
from app.modules_registry.transitions import TYPE_SUJET_INSTALLATION, transition_autorisee, transitionner

MOT_DE_PASSE = "TestPassword123!"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Le moteur est un singleton lié à la boucle asyncio : pool neuf avant et après chaque test."""
    await engine.dispose()
    yield
    await engine.dispose()


class FournisseurEnregistreur:
    """Fournisseur d'exécution simulé : réussit et garde la trace de ses appels."""

    def __init__(self) -> None:
        self.appels: list[uuid.UUID] = []

    async def provisionner(self, installation_id: uuid.UUID, module_version_id: uuid.UUID) -> None:
        self.appels.append(installation_id)


class FournisseurEnEchec:
    """Fournisseur d'exécution simulé : chaque provisionnement échoue."""

    async def provisionner(self, installation_id: uuid.UUID, module_version_id: uuid.UUID) -> None:
        raise RuntimeError("provisionnement simulé en échec")


def _code() -> str:
    return f"be047_{uuid.uuid4().hex[:10]}"


async def _module_avec_version(
    *,
    publiee: bool = True,
    compatibility: dict | None = None,
    prerequisites: list | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Crée un module du catalogue et une version ; retourne (module, version).

    Par défaut la version est publiée et compatible (manifeste supporté par le registre)."""
    if compatibility is None:
        compatibility = {"manifestVersion": max(VERSIONS_MANIFESTE_SUPPORTEES)}
    code = _code()
    async with AsyncSessionLocal() as db:
        module = await get_or_create_module(db, code, f"Module {code}", "Module de test BE-047")
        version = ModuleVersion(
            moduleId=module.id,
            version="1.0.0",
            digest="sha256:be047",
            provenance="test-be047",
            compatibility=compatibility,
            prerequisites=prerequisites,
            publicationState="published" if publiee else "draft",
            publishedAt=datetime.now(timezone.utc) if publiee else None,
        )
        db.add(version)
        await db.commit()
        return module.id, version.id


async def _inscrire(client: AsyncClient) -> dict:
    """Crée un utilisateur réel ; renvoie son identifiant et son jeton d'accès."""
    email = f"be047-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    reponse = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-047"}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return {"id": uuid.UUID(reponse.json()["id"]), "token": login.json()["accessToken"]}


async def _organisation(client: AsyncClient, proprietaire: dict) -> str:
    """Crée une organisation dont `proprietaire` est propriétaire ; renvoie son identifiant."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Org BE-047", "slug": f"be047-{uuid.uuid4().hex[:8]}"},
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
    return f"/api/v1/organizations/{organisation_id}/modules/{module_id}/installations"


def _corps(version_id: uuid.UUID, state_version: int = 0) -> dict:
    return {"moduleVersionId": str(version_id), "stateVersion": state_version}


def _code_erreur(reponse) -> str:
    return reponse.json()["error"]["code"]


async def _installer(
    *,
    organisation_id: uuid.UUID,
    acteur_id: uuid.UUID,
    module_id: uuid.UUID,
    version_id: uuid.UUID,
    cle: str,
    fournisseur=None,
) -> dict:
    """Appelle directement le service et valide la transaction ; renvoie les valeurs lues avant commit."""
    from app.modules_registry.installation import executer_installation

    async with AsyncSessionLocal() as db:
        try:
            installation = await executer_installation(
                db,
                organization_id=organisation_id,
                acteur_id=acteur_id,
                module_id=module_id,
                module_version_id=version_id,
                state_version=0,
                cle_idempotence=cle,
                fournisseur=fournisseur,
            )
            resultat = {
                "id": installation.id,
                "state": installation.state,
                "stateVersion": installation.stateVersion,
                "lastErrorCode": installation.lastErrorCode,
                "operationId": installation.operationId,
            }
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return resultat


async def _journal(installation_id: uuid.UUID) -> list[tuple[str, str]]:
    """Transitions journalisées du sujet, dans l'ordre : liste de (de_etat, vers_etat)."""
    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(
                select(ModuleStateTransition)
                .where(ModuleStateTransition.subjectId == installation_id)
                .order_by(ModuleStateTransition.stateVersionAfter)
            )
        ).scalars().all()
        return [(ligne.fromState, ligne.toState) for ligne in lignes]


async def _nombre_installations(module_id: uuid.UUID, organisation_id: uuid.UUID | None = None) -> int:
    async with AsyncSessionLocal() as db:
        requete = select(func.count()).select_from(ModuleInstallation).where(ModuleInstallation.moduleId == module_id)
        if organisation_id is not None:
            requete = requete.where(ModuleInstallation.organizationId == organisation_id)
        return (await db.execute(requete)).scalar_one()


async def _nombre_transitions_organisation(organisation_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count())
                .select_from(ModuleStateTransition)
                .where(
                    ModuleStateTransition.subjectType == TYPE_SUJET_INSTALLATION,
                    ModuleStateTransition.organizationId == organisation_id,
                )
            )
        ).scalar_one()


# --- CA-1 : séquence d'installation produite par le service, fournisseur simulé -----------------


async def test_ca1_sequence_not_installed_preflight_provisioning_installed(client: AsyncClient):
    """CA-1 : la séquence not_installed -> preflight -> provisioning -> installed est journalisée,
    et le fournisseur est appelé une fois pour l'installation créée."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id = await _module_avec_version()
    fournisseur = FournisseurEnregistreur()

    resultat = await _installer(
        organisation_id=uuid.UUID(organisation_id),
        acteur_id=proprietaire["id"],
        module_id=module_id,
        version_id=version_id,
        cle="ca1-sequence",
        fournisseur=fournisseur,
    )

    assert resultat["state"] == "installed"
    assert resultat["lastErrorCode"] is None
    assert await _journal(resultat["id"]) == [
        ("not_installed", "preflight"),
        ("preflight", "provisioning"),
        ("provisioning", "installed"),
    ]
    assert fournisseur.appels == [resultat["id"]]


# --- CA-2 : échec pendant provisioning -> failed, jamais active -----------------------------------


async def test_ca2_echec_de_provisionnement_place_en_failed_avec_code_erreur(client: AsyncClient):
    """CA-2 : un échec pendant provisioning donne l'état `failed` avec `lastErrorCode` renseigné."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id = await _module_avec_version()

    resultat = await _installer(
        organisation_id=uuid.UUID(organisation_id),
        acteur_id=proprietaire["id"],
        module_id=module_id,
        version_id=version_id,
        cle="ca2-echec",
        fournisseur=FournisseurEnEchec(),
    )

    assert resultat["state"] == "failed"
    assert resultat["lastErrorCode"] == "MODULE_PROVISIONING_FAILED"
    assert (await _journal(resultat["id"]))[-1] == ("provisioning", "failed")


async def test_ca2_depuis_failed_le_passage_a_active_est_refuse(client: AsyncClient):
    """CA-2 : aucun passage à `active` (BE-048) n'est possible depuis `failed`."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id = await _module_avec_version()
    resultat = await _installer(
        organisation_id=uuid.UUID(organisation_id),
        acteur_id=proprietaire["id"],
        module_id=module_id,
        version_id=version_id,
        cle="ca2-active",
        fournisseur=FournisseurEnEchec(),
    )

    assert resultat["state"] == "failed"
    assert not transition_autorisee(TYPE_SUJET_INSTALLATION, "failed", "active")
    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as exc:
            await transitionner(
                db,
                type_sujet=TYPE_SUJET_INSTALLATION,
                id_sujet=resultat["id"],
                vers_etat="active",
                version_attendue=resultat["stateVersion"],
                acteur_id=proprietaire["id"],
                origine="client",
                cle_idempotence="ca2-active-refus",
            )
        await db.rollback()
    assert exc.value.code == "MODULE_TRANSITION_NOT_ALLOWED"
    assert ("failed", "active") not in await _journal(resultat["id"])


# --- CA-3 : rejeu de la même Idempotency-Key ------------------------------------------------------


async def test_ca3_meme_idempotency_key_ne_cree_pas_de_seconde_operation(client: AsyncClient):
    """CA-3 : rejouer la même clé renvoie le même `operationId`, sans seconde installation ni
    seconde suite de transitions."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id = await _module_avec_version()
    cle = str(uuid.uuid4())
    entetes = {**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: cle}

    premiere = await client.post(_url(organisation_id, module_id), json=_corps(version_id), headers=entetes)
    rejeu = await client.post(_url(organisation_id, module_id), json=_corps(version_id), headers=entetes)

    assert premiere.status_code < 300, premiere.text
    assert rejeu.status_code == premiere.status_code
    assert rejeu.json()["operationId"] == premiere.json()["operationId"]
    assert await _nombre_installations(module_id) == 1
    assert len(await _journal(uuid.UUID(premiere.json()["id"]))) == 3


async def test_ca3_lecture_d_une_operation_renvoie_son_etat(client: AsyncClient):
    """Relecture d'une opération (cas du résultat incertain) : même `operationId`, état courant."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id = await _module_avec_version()
    cree = await client.post(
        _url(organisation_id, module_id),
        json=_corps(version_id),
        headers={**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )
    operation_id = cree.json()["operationId"]

    lue = await client.get(
        f"{_url(organisation_id, module_id)}/{operation_id}",
        headers=_entete(proprietaire["token"], organisation_id),
    )

    assert lue.status_code == 200, lue.text
    assert lue.json()["operationId"] == operation_id
    assert lue.json()["state"] == "installed"


# --- CA-4 : sans organization.module.install -> 403, aucune ligne ----------------------------------


async def test_ca4_acteur_sans_droit_d_installation_recoit_403_sans_ligne(client: AsyncClient):
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id = await _module_avec_version()
    membre = await _membre_sans_droit(client, organisation_id)

    reponse = await client.post(
        _url(organisation_id, module_id),
        json=_corps(version_id),
        headers={**_entete(membre["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert reponse.status_code == 403
    assert await _nombre_installations(module_id) == 0
    assert await _nombre_transitions_organisation(uuid.UUID(organisation_id)) == 0


# --- CA-5 : isolation entre organisations ----------------------------------------------------------


async def test_ca5_installer_dans_une_autre_organisation_repond_404(client: AsyncClient):
    """CA-5 : un acteur de A qui installe dans B reçoit 404, en chemin comme en en-tête."""
    proprietaire_a = await _inscrire(client)
    org_a = await _organisation(client, proprietaire_a)
    proprietaire_b = await _inscrire(client)
    org_b = await _organisation(client, proprietaire_b)
    module_id, version_id = await _module_avec_version()
    cle = str(uuid.uuid4())

    chemin = await client.post(
        _url(org_b, module_id),
        json=_corps(version_id),
        headers={**_entete(proprietaire_a["token"], org_a), EN_TETE_IDEMPOTENCE: cle},
    )
    entete = await client.post(
        _url(org_b, module_id),
        json=_corps(version_id),
        headers={**_entete(proprietaire_a["token"], org_b), EN_TETE_IDEMPOTENCE: cle},
    )

    assert chemin.status_code == 404
    assert entete.status_code == 404
    assert await _nombre_installations(module_id, uuid.UUID(org_b)) == 0


async def test_ca5_installation_de_a_invisible_dans_la_lecture_de_b(client: AsyncClient):
    proprietaire_a = await _inscrire(client)
    org_a = await _organisation(client, proprietaire_a)
    proprietaire_b = await _inscrire(client)
    org_b = await _organisation(client, proprietaire_b)
    module_id, version_id = await _module_avec_version()
    cree = await client.post(
        _url(org_a, module_id),
        json=_corps(version_id),
        headers={**_entete(proprietaire_a["token"], org_a), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )
    assert cree.status_code < 300, cree.text
    operation_id = cree.json()["operationId"]

    lue_par_b = await client.get(
        f"{_url(org_b, module_id)}/{operation_id}",
        headers=_entete(proprietaire_b["token"], org_b),
    )
    lue_par_a_sous_b = await client.get(
        f"{_url(org_b, module_id)}/{operation_id}",
        headers=_entete(proprietaire_a["token"], org_a),
    )

    assert lue_par_b.status_code == 404
    assert lue_par_a_sous_b.status_code == 404
    assert operation_id not in lue_par_b.text


# --- CA-6 : version incompatible -> 409, aucune étape de preflight --------------------------------


async def test_ca6_version_incompatible_renvoie_409_sans_etape_de_preflight(client: AsyncClient):
    """CA-6 : une version `incompatible` (BE-044) renvoie 409, sans ligne d'installation ni transition."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id = await _module_avec_version(compatibility={"manifestVersion": 999999})

    reponse = await client.post(
        _url(organisation_id, module_id),
        json=_corps(version_id),
        headers={**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_VERSION_INCOMPATIBLE"
    assert await _nombre_installations(module_id) == 0
    assert await _nombre_transitions_organisation(uuid.UUID(organisation_id)) == 0


# --- Vérifications préalables et contraintes complémentaires ----------------------------------------


async def test_version_non_publiee_renvoie_422(client: AsyncClient):
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id = await _module_avec_version(publiee=False)

    reponse = await client.post(
        _url(organisation_id, module_id),
        json=_corps(version_id),
        headers={**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert reponse.status_code == 422
    assert _code_erreur(reponse) == "MODULE_VERSION_NOT_PUBLISHED"
    assert await _nombre_installations(module_id) == 0


async def test_prerequis_publie_mais_non_installe_dans_l_organisation_renvoie_409(client: AsyncClient):
    """Le prérequis existe au catalogue (publié) mais n'est pas installé dans l'organisation : 409."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    prerequis_module_id, _ = await _module_avec_version()
    prerequis_code = (await _code_du_module(prerequis_module_id))
    module_id, version_id = await _module_avec_version(prerequisites=[{"code": prerequis_code, "version": None}])

    reponse = await client.post(
        _url(organisation_id, module_id),
        json=_corps(version_id),
        headers={**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_PREREQUISITE_MISSING"
    assert await _nombre_installations(module_id) == 0


async def test_prerequis_absent_du_catalogue_renvoie_409(client: AsyncClient):
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id = await _module_avec_version(
        prerequisites=[{"code": f"absent_{uuid.uuid4().hex[:8]}", "version": None}]
    )

    reponse = await client.post(
        _url(organisation_id, module_id),
        json=_corps(version_id),
        headers={**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert reponse.status_code == 409
    assert _code_erreur(reponse) == "MODULE_PREREQUISITE_MISSING"


async def test_deuxieme_installation_non_retiree_renvoie_409(client: AsyncClient):
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id = await _module_avec_version()
    premiere = await client.post(
        _url(organisation_id, module_id),
        json=_corps(version_id),
        headers={**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )
    assert premiere.status_code < 300, premiere.text

    seconde = await client.post(
        _url(organisation_id, module_id),
        json=_corps(version_id),
        headers={**_entete(proprietaire["token"], organisation_id), EN_TETE_IDEMPOTENCE: str(uuid.uuid4())},
    )

    assert seconde.status_code == 409
    assert _code_erreur(seconde) == "MODULE_ALREADY_INSTALLED"
    assert await _nombre_installations(module_id) == 1


async def test_ca_base_refuse_deux_installations_non_retirees_pour_un_couple(client: AsyncClient):
    """Contrainte d'unicité (niveau base) : une seule installation non `removed` par (organisation, module)."""
    proprietaire = await _inscrire(client)
    organisation_id = await _organisation(client, proprietaire)
    module_id, version_id = await _module_avec_version()
    def _ligne() -> ModuleInstallation:
        return ModuleInstallation(
            organizationId=uuid.UUID(organisation_id),
            moduleId=module_id,
            moduleVersionId=version_id,
            state="installed",
            stateVersion=3,
            operationId=uuid.uuid4(),
        )

    async with AsyncSessionLocal() as db:
        db.add(_ligne())
        await db.commit()
    async with AsyncSessionLocal() as db:
        db.add(_ligne())
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def _code_du_module(module_id: uuid.UUID) -> str:
    from app.modules_registry.models import Module

    async with AsyncSessionLocal() as db:
        return (await db.get(Module, module_id)).code
