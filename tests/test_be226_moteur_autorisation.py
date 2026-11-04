"""BE-226 : moteur d'autorisation unique et enforcement.

Couvre les critères d'acceptation de la définition BE-226
(implementation-backend/tasks-exploitation-architecture.md, section BE-226) :
- CA-1 : matrice rôle x action x ressource x tenant (test paramétré), chaque
  combinaison refusée donne le code attendu (401, 403 ou 404) ;
- CA-2 : retrait d'une permission pendant une session, l'action suivante est
  refusée sans délai de cache ;
- CA-3 : route directe, route API et export d'une même ressource donnent la
  même décision ;
- CA-4 : une tâche asynchrone n'hérite pas d'un compte plus puissant que son
  initiateur ;
- CA-5 : aucune décision n'est prise par l'interface seule : la route refuse
  sans droit, malgré un en-tête posé par l'interface.

Les ressources métier complexes ne sont pas montées ici : la ressource protégée
est un rôle de l'organisation (table `role`, portée `role`), ce qui suffit à
prouver l'isolation par tenant et par portée. Les pièces qui dépendent d'un
abonnement réel (entitlement) ou d'un module activé sont remplacées par un
monkeypatch explicite de la porte concernée, nommé dans le test ; aucun test
n'est sauté.

Ce qui n'est pas couvert ici (voir la note de quota dans app/core/authz.py) :
le comptage réel des quotas d'usage.
"""

import uuid

import pytest
from fastapi import Depends, FastAPI, Header, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core import authz
from app.core.authz import (
    ADHESION_INACTIVE,
    AUTHENTIFICATION_REQUISE,
    ENTITLEMENT_ABSENT,
    HORS_PORTEE,
    MODULE_INACTIF,
    MOTIF_OK,
    PERMISSION_ABSENTE,
    POLITIQUE_REFUSEE,
    QUOTA_DEPASSE,
    decide,
    decide_pour_tache,
    exiger_acces,
)
from app.core.database import AsyncSessionLocal
from app.core.security import get_current_user, hash_password
from app.identity.models import OrganizationUser, User
from app.identity.schemas import CreateOrganizationRequest
from app.identity.service import create_organization
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.service import assign_role, get_or_create_permission, user_has_permission

PERM_LIRE = "be226.dossier.lire"
PERM_SUPPRIMER = "be226.dossier.supprimer"
MODULE_TEST = "be226"


# ---------------------------------------------------------------------------
# Helpers de données (aucun montage massif : une organisation, des rôles, des
# utilisateurs, et la ressource « rôle » de l'organisation).
# ---------------------------------------------------------------------------


async def _utilisateur(db, label: str) -> User:
    user = User(
        email=f"be226-{label}-{uuid.uuid4().hex[:8]}@example.com", hashedPassword=hash_password("x"), fullName=label
    )
    db.add(user)
    await db.flush()
    return user


async def _organisation(db, owner: User, label: str):
    return await create_organization(
        db, owner, CreateOrganizationRequest(name=f"BE226 {label}", slug=f"be226-{label}-{uuid.uuid4().hex[:8]}")
    )


async def _membre(db, organization_id: uuid.UUID, user: User) -> None:
    db.add(OrganizationUser(organizationId=organization_id, userId=user.id))
    await db.flush()


async def _droits_du_proprietaire(db, organization_id: uuid.UUID, owner: User, codes: list[str]) -> None:
    """Le propriétaire détient les permissions qu'il attribue (non-élévation)."""
    owner_role = (
        await db.execute(
            select(Role).join(UserRole, UserRole.roleId == Role.id).where(
                UserRole.userId == owner.id, UserRole.organizationId == organization_id, Role.code == "owner"
            )
        )
    ).scalar_one()
    for code in codes:
        permission = await get_or_create_permission(db, code, MODULE_TEST, f"Permission de test {code}")
        db.add(RolePermission(roleId=owner_role.id, permissionId=permission.id))
    await db.flush()


async def _role(db, organization_id: uuid.UUID, code: str, permission_codes: list[str]) -> Role:
    role = Role(organizationId=organization_id, code=code, name=f"Rôle {code}")
    db.add(role)
    await db.flush()
    for permission_code in permission_codes:
        permission = await get_or_create_permission(db, permission_code, MODULE_TEST, f"Permission de test {permission_code}")
        db.add(RolePermission(roleId=role.id, permissionId=permission.id))
    await db.flush()
    return role


async def _monde(db, label: str):
    """Une organisation avec un propriétaire ; retourne (propriétaire, organisation)."""
    owner = await _utilisateur(db, f"proprietaire-{label}")
    org = await _organisation(db, owner, label)
    return owner, org


async def _organisation_du_role(db, role_id: uuid.UUID | None) -> uuid.UUID | None:
    """Tenant réel de la ressource « rôle » ; None si elle n'existe pas."""
    if role_id is None:
        return None
    return (await db.execute(select(Role.organizationId).where(Role.id == role_id))).scalar_one_or_none()


# ---------------------------------------------------------------------------
# CA-1 : matrice rôle x action x ressource x tenant.
# ---------------------------------------------------------------------------

# Chaque cas : (identifiant, attendu autorisé, motif attendu, statut HTTP attendu).
CAS_MATRICE = [
    ("lecture_permise_organisation_entiere", True, MOTIF_OK, None),
    ("action_non_portee_par_le_role", False, PERMISSION_ABSENTE, 403),
    ("membre_sans_role", False, PERMISSION_ABSENTE, 403),
    ("role_scope_sur_autre_ressource_du_tenant", False, PERMISSION_ABSENTE, 403),
    ("role_scope_sur_la_ressource", True, MOTIF_OK, None),
    ("non_membre_de_l_organisation", False, ADHESION_INACTIVE, 404),
    ("ressource_d_un_autre_tenant", False, HORS_PORTEE, 404),
    ("ressource_inexistante", False, HORS_PORTEE, 404),
    ("utilisateur_non_authentifie", False, AUTHENTIFICATION_REQUISE, 401),
]


@pytest.mark.parametrize(("cas", "attendu", "motif", "statut"), CAS_MATRICE, ids=[c[0] for c in CAS_MATRICE])
async def test_ca1_matrice_rolexactionxressourcexlocataire(cas, attendu, motif, statut):
    """CA-1 : chaque combinaison donne la décision et le code attendus."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, f"ca1-{cas}")
        autre_owner, autre_org = await _monde(db, f"ca1-autre-{cas}")
        await _droits_du_proprietaire(db, org.id, owner, [PERM_LIRE, PERM_SUPPRIMER])
        await _droits_du_proprietaire(db, autre_org.id, autre_owner, [PERM_LIRE])

        cible = await _role(db, org.id, "cible", [])
        autre_ressource = await _role(db, org.id, "autre", [])
        ressource_autre_tenant = await _role(db, autre_org.id, "ressource_etrangere", [])
        membre = await _utilisateur(db, f"membre-{cas}")
        await _membre(db, org.id, membre)

        role_lecture = await _role(db, org.id, "lecteur", [PERM_LIRE])
        ressource_id: uuid.UUID | None = cible.id
        ressource_org: uuid.UUID | None = org.id
        action = PERM_LIRE
        utilisateur: User | None = membre

        if cas == "lecture_permise_organisation_entiere":
            await assign_role(db, org.id, owner.id, membre.id, role_lecture.id)
        elif cas == "action_non_portee_par_le_role":
            await assign_role(db, org.id, owner.id, membre.id, role_lecture.id)
            action = PERM_SUPPRIMER
        elif cas == "membre_sans_role":
            pass
        elif cas == "role_scope_sur_autre_ressource_du_tenant":
            await assign_role(db, org.id, owner.id, membre.id, role_lecture.id, "role", autre_ressource.id)
        elif cas == "role_scope_sur_la_ressource":
            await assign_role(db, org.id, owner.id, membre.id, role_lecture.id, "role", cible.id)
        elif cas == "non_membre_de_l_organisation":
            non_membre = await _utilisateur(db, "non-membre-ca1")
            await assign_role(db, org.id, owner.id, membre.id, role_lecture.id)
            utilisateur = non_membre
        elif cas == "ressource_d_un_autre_tenant":
            await assign_role(db, org.id, owner.id, membre.id, role_lecture.id)
            ressource_id = ressource_autre_tenant.id
            ressource_org = await _organisation_du_role(db, ressource_id)
        elif cas == "ressource_inexistante":
            await assign_role(db, org.id, owner.id, membre.id, role_lecture.id)
            ressource_id = uuid.uuid4()
            ressource_org = await _organisation_du_role(db, ressource_id)
        elif cas == "utilisateur_non_authentifie":
            utilisateur = None
        await db.commit()

    async with AsyncSessionLocal() as db:
        decision = await decide(
            db,
            user=utilisateur,
            organization_id=org.id,
            permission_code=action,
            resource_type="role",
            resource_id=ressource_id,
            resource_organization_id=ressource_org,
        )
    assert decision.allowed is attendu, decision
    assert decision.reason == motif
    assert decision.status_code == statut


# ---------------------------------------------------------------------------
# CA-2 : révocation pendant une session, sans délai de cache.
# ---------------------------------------------------------------------------


async def test_ca2_retrait_de_permission_refuse_l_action_suivante():
    """CA-2 : une permission retirée pendant la session est refusée au coup
    suivant, dans la même session comme dans une session neuve."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "ca2")
        await _droits_du_proprietaire(db, org.id, owner, [PERM_LIRE])
        membre = await _utilisateur(db, "membre-ca2")
        await _membre(db, org.id, membre)
        role = await _role(db, org.id, "lecteur_ca2", [PERM_LIRE])
        await assign_role(db, org.id, owner.id, membre.id, role.id)
        await db.commit()

        premiere = await decide(
            db, user=membre, organization_id=org.id, permission_code=PERM_LIRE,
            resource_type="role", resource_id=role.id, resource_organization_id=org.id,
        )
        assert premiere.allowed is True

        await db.execute(delete(UserRole).where(UserRole.userId == membre.id, UserRole.organizationId == org.id))
        await db.flush()
        apres_retrait = await decide(
            db, user=membre, organization_id=org.id, permission_code=PERM_LIRE,
            resource_type="role", resource_id=role.id, resource_organization_id=org.id,
        )
        assert apres_retrait.allowed is False
        assert apres_retrait.reason == PERMISSION_ABSENTE
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert await user_has_permission(db, membre.id, org.id, PERM_LIRE) is False


# ---------------------------------------------------------------------------
# CA-3 : route directe, route API et export donnent la même décision.
# ---------------------------------------------------------------------------


async def _faux_utilisateur(request: Request) -> User:
    """Remplace l'authentification JWT des tests : l'utilisateur est désigné par
    l'en-tête X-Test-Utilisateur (test seulement). La chaîne d'autorisation
    testée, elle, est la vraie."""
    identifiant = uuid.UUID(request.headers["X-Test-Utilisateur"])
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User).where(User.id == identifiant))).scalar_one()


def _application_de_test(application_reelle: FastAPI) -> FastAPI:
    """Trois points d'entrée sur la même ressource, protégés par la même
    garde `exiger_acces` : directe, API, export."""
    application = FastAPI()
    application.exception_handlers.update(application_reelle.exception_handlers)
    application.dependency_overrides[get_current_user] = _faux_utilisateur

    garde = exiger_acces(PERM_LIRE, resource_type="role", resource_param="ressource_id", resolve_resource_org=_organisation_du_role)

    @application.get("/organisations/{organization_id}/roles/{ressource_id}", dependencies=[Depends(garde)])
    async def directe() -> dict:
        return {"route": "directe"}

    @application.get("/api/v1/organisations/{organization_id}/roles/{ressource_id}", dependencies=[Depends(garde)])
    async def api() -> dict:
        return {"route": "api"}

    @application.get("/organisations/{organization_id}/roles/{ressource_id}/export", dependencies=[Depends(garde)])
    async def export() -> dict:
        return {"route": "export"}

    return application


@pytest.fixture
async def application_de_test():
    from app.main import app as application_reelle

    return _application_de_test(application_reelle)


async def test_ca3_directe_api_export_donnent_la_meme_decision(application_de_test):
    """CA-3 : pour un utilisateur autorisé et un utilisateur refusé, les trois
    routes répondent le même statut et le même code."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "ca3")
        await _droits_du_proprietaire(db, org.id, owner, [PERM_LIRE])
        ressource = await _role(db, org.id, "ressource_ca3", [])
        autorise = await _utilisateur(db, "autorise-ca3")
        refuse = await _utilisateur(db, "refuse-ca3")
        await _membre(db, org.id, autorise)
        await _membre(db, org.id, refuse)
        role = await _role(db, org.id, "lecteur_ca3", [PERM_LIRE])
        await assign_role(db, org.id, owner.id, autorise.id, role.id)
        await db.commit()

    resultats = {}
    transport = ASGITransport(app=application_de_test)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for etiquette, utilisateur in (("autorise", autorise), ("refuse", refuse)):
            statuts = []
            for chemin in (
                f"/organisations/{org.id}/roles/{ressource.id}",
                f"/api/v1/organisations/{org.id}/roles/{ressource.id}",
                f"/organisations/{org.id}/roles/{ressource.id}/export",
            ):
                reponse = await client.get(
                    chemin,
                    headers={"X-Organization-Id": str(org.id), "X-Test-Utilisateur": str(utilisateur.id)},
                )
                statuts.append(reponse.status_code)
            resultats[etiquette] = statuts

    assert resultats["autorise"] == [200, 200, 200]
    assert resultats["refuse"] == [403, 403, 403]


# ---------------------------------------------------------------------------
# CA-4 : une tâche asynchrone ne dépasse pas son initiateur.
# ---------------------------------------------------------------------------


async def test_ca4_tache_refusee_si_l_initiateur_n_a_pas_le_droit_meme_si_le_proprietaire_l_a():
    """CA-4 : la tâche est jugée sur les droits de son initiateur ; le
    propriétaire, qui détient la permission, ne la prête pas."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "ca4-a")
        await _droits_du_proprietaire(db, org.id, owner, [PERM_LIRE])
        initiateur = await _utilisateur(db, "initiateur-ca4-a")
        await _membre(db, org.id, initiateur)
        await db.commit()

        decision = await decide_pour_tache(
            db, initiateur_id=initiateur.id, organization_id=org.id, permission_code=PERM_LIRE
        )
    assert decision.allowed is False
    assert decision.reason == PERMISSION_ABSENTE


async def test_ca4_tache_sans_initiateur_est_refusee():
    """CA-4 : une tâche sans initiateur identifié n'hérite d'aucun droit."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "ca4-b")
        await _droits_du_proprietaire(db, org.id, owner, [PERM_LIRE])
        await db.commit()

        decision = await decide_pour_tache(db, initiateur_id=None, organization_id=org.id, permission_code=PERM_LIRE)
    assert decision.allowed is False
    assert decision.reason == AUTHENTIFICATION_REQUISE


async def test_ca4_tache_suit_la_revocation_de_l_initiateur():
    """CA-4 : une tâche lancée avec un droit, exécutée après le retrait de ce
    droit, est refusée : la décision est reprise à l'exécution."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "ca4-c")
        await _droits_du_proprietaire(db, org.id, owner, [PERM_LIRE])
        initiateur = await _utilisateur(db, "initiateur-ca4-c")
        await _membre(db, org.id, initiateur)
        role = await _role(db, org.id, "lecteur_ca4_c", [PERM_LIRE])
        await assign_role(db, org.id, owner.id, initiateur.id, role.id)
        await db.commit()

        avant = await decide_pour_tache(db, initiateur_id=initiateur.id, organization_id=org.id, permission_code=PERM_LIRE)
        assert avant.allowed is True

        await db.execute(delete(UserRole).where(UserRole.userId == initiateur.id, UserRole.organizationId == org.id))
        await db.commit()

        apres = await decide_pour_tache(db, initiateur_id=initiateur.id, organization_id=org.id, permission_code=PERM_LIRE)
    assert apres.allowed is False
    assert apres.reason == PERMISSION_ABSENTE


# ---------------------------------------------------------------------------
# CA-5 : l'interface seule ne décide jamais.
# ---------------------------------------------------------------------------


async def test_ca5_la_route_refuse_sans_droit_malgre_un_en_tete_d_interface(application_de_test):
    """CA-5 : un en-tête posé par l'interface (rôle ou droit affiché) ne
    donne aucun accès ; seul le serveur décide."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "ca5")
        ressource = await _role(db, org.id, "ressource_ca5", [])
        sans_droit = await _utilisateur(db, "sans-droit-ca5")
        await _membre(db, org.id, sans_droit)
        await db.commit()

    entetes_interface = {
        "X-Organization-Id": str(org.id),
        "X-Test-Utilisateur": str(sans_droit.id),
        "X-Ui-Role": "owner",
        "X-Ui-Permissions": f"{PERM_LIRE},{PERM_SUPPRIMER}",
    }
    transport = ASGITransport(app=application_de_test)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.get(f"/organisations/{org.id}/roles/{ressource.id}", headers=entetes_interface)
    assert reponse.status_code == 403
    assert reponse.json()["error"]["code"] == "permission_denied"


# ---------------------------------------------------------------------------
# Portes d'entitlement, d'état de module, de quota et de politique.
# ---------------------------------------------------------------------------


async def test_entitlement_refuse_quand_l_abonnement_ne_couvre_pas_le_module(monkeypatch):
    """La porte d'entitlement refuse (403) même si le rôle et le module sont
    en ordre. L'état d'abonnement est remplacé par un monkeypatch explicite ;
    le calcul réel des entitlements est couvert par BE-024."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "entitlement")
        await _droits_du_proprietaire(db, org.id, owner, [PERM_LIRE])
        membre = await _utilisateur(db, "membre-entitlement")
        await _membre(db, org.id, membre)
        role = await _role(db, org.id, "lecteur_entitlement", [PERM_LIRE])
        await assign_role(db, org.id, owner.id, membre.id, role.id)
        await db.commit()

    async def _module_actif(*_args, **_kwargs) -> bool:
        return True

    async def _entitlement_expire(*_args, **_kwargs) -> tuple[str, bool]:
        return ("expired", False)

    monkeypatch.setattr(authz, "is_module_active", _module_actif)
    monkeypatch.setattr(authz, "get_module_entitlement_access", _entitlement_expire)

    async with AsyncSessionLocal() as db:
        decision = await decide(
            db, user=membre, organization_id=org.id, permission_code=PERM_LIRE, module_code=MODULE_TEST
        )
    assert decision.allowed is False
    assert decision.reason == ENTITLEMENT_ABSENT
    assert decision.status_code == 403


async def test_module_inactif_refuse_meme_avec_la_permission():
    """Un module non enregistré ou inactif refuse (403), même avec la permission."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "module-inactif")
        await _droits_du_proprietaire(db, org.id, owner, [PERM_LIRE])
        membre = await _utilisateur(db, "membre-module-inactif")
        await _membre(db, org.id, membre)
        role = await _role(db, org.id, "lecteur_module_inactif", [PERM_LIRE])
        await assign_role(db, org.id, owner.id, membre.id, role.id)
        await db.commit()

        decision = await decide(
            db, user=membre, organization_id=org.id, permission_code=PERM_LIRE, module_code=MODULE_TEST
        )
    assert decision.allowed is False
    assert decision.reason == MODULE_INACTIF
    assert decision.status_code == 403


async def test_politique_refuse_une_permission_d_un_autre_module(monkeypatch):
    """La politique de module refuse une permission qui n'appartient ni au
    module demandé ni au socle partagé (un rôle CRM ne donne jamais un droit Stock)."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "politique")
        await _droits_du_proprietaire(db, org.id, owner, [PERM_LIRE])
        membre = await _utilisateur(db, "membre-politique")
        await _membre(db, org.id, membre)
        role = await _role(db, org.id, "lecteur_politique", [PERM_LIRE])
        await assign_role(db, org.id, owner.id, membre.id, role.id)
        await db.commit()

    async def _module_actif(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(authz, "is_module_active", _module_actif)

    async with AsyncSessionLocal() as db:
        decision = await decide(
            db, user=membre, organization_id=org.id, permission_code=PERM_LIRE, module_code="autre_module_be226"
        )
    assert decision.allowed is False
    assert decision.reason == POLITIQUE_REFUSEE
    assert decision.status_code == 403


async def test_quota_depasse_refuse_malgre_la_permission():
    """La porte de quota, quand elle est branchée, refuse (403) après le reste."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "quota")
        await _droits_du_proprietaire(db, org.id, owner, [PERM_LIRE])
        membre = await _utilisateur(db, "membre-quota")
        await _membre(db, org.id, membre)
        role = await _role(db, org.id, "lecteur_quota", [PERM_LIRE])
        await assign_role(db, org.id, owner.id, membre.id, role.id)
        await db.commit()

        async def _quota_atteint() -> bool:
            return False

        decision = await decide(
            db, user=membre, organization_id=org.id, permission_code=PERM_LIRE, quota=_quota_atteint
        )
    assert decision.allowed is False
    assert decision.reason == QUOTA_DEPASSE
    assert decision.status_code == 403


async def test_documentation_de_la_decision_et_absence_d_entree_d_interface():
    """La fonction de décision n'accepte aucune entrée venant de l'interface :
    pas de paramètre de rôle ou de droit affiché."""
    import inspect

    parametres = set(inspect.signature(decide).parameters)
    assert not {p for p in parametres if "ui" in p.lower() or "interface" in p.lower() or "front" in p.lower()}
    assert decide.__doc__ and "entitlement" in decide.__doc__
