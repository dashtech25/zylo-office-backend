"""BE-248 : tests bout en bout d'isolation et d'autorisation.

Couvre les critères d'acceptation de la définition BE-248
(implementation-backend/tasks-exploitation-architecture.md, section BE-248) :
- CA-1 : matrice allow/deny par parcours critique, sur les routes HTTP réelles
  (test paramétré). Le dénominateur des parcours critiques est NON DÉFINI
  (QE-EXP-22) : les parcours retenus ici sont une proposition explicite, à
  valider ; ils ne couvrent pas tout le produit.
- CA-2 : un tenant adversaire ne lit ni n'écrit rien de B, ni par l'API, ni par
  l'export des données de facturation, ni par une tâche asynchrone.
- CA-3 : une panne de la dépendance d'autorisation donne un refus fermé, jamais
  un accès ni une donnée.
- CA-4 : les fixtures de test n'introduisent aucun compte privilégié par défaut.

Tenants : A (le tenant adversaire, dont le propriétaire détient tous les droits
chez lui), B (le tenant cible, avec ses rôles), et un utilisateur non membre de
B. Les données sont minimales : une organisation par tenant, un rôle par cas.
Aucun montage massif de fixtures.

Limites connues (à traiter ailleurs, voir QE-EXP-22) : l'export complet d'un
compte payeur n'est pas monté (il exige un compte payeur réel), donc seul le refus
côté adversaire est vérifié pour l'export.
"""

import ast
import pathlib
import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core import authz
from app.core.authz import (
    ADHESION_INACTIVE,
    AUTHENTIFICATION_REQUISE,
    PERMISSION_ABSENTE,
    decide,
    decide_pour_tache,
)
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.main import app
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.permissions import ROLE_MANAGE
from app.rbac.service import get_or_create_permission
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
ROUTE_ROLES = "/api/v1/organizations/current/roles"
ROUTE_ROLE = "/api/v1/organizations/current/roles/{role_id}"
ROUTE_EXPORT = "/api/v1/billing/data-exports"
ROUTE_CREER_ROLE = "/api/v1/organizations/{organisation_id}/roles"
RACINE_TESTS = pathlib.Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Helpers : comptes et tenants passés par les routes réelles quand c'est possible,
# rôles et appartenances insérés en base quand la route d'attribution exige un
# contexte que ce test n'a pas besoin de monter.
# ---------------------------------------------------------------------------


def _entete(compte: dict, organisation_id: uuid.UUID | None = None) -> dict:
    entete = {"Authorization": f"Bearer {compte['token']}"}
    if organisation_id is not None:
        entete["X-Organization-Id"] = str(organisation_id)
    return entete


async def _compte(client: AsyncClient, libelle: str) -> dict:
    """Crée un compte ordinaire par l'API et retourne son identifiant et son jeton."""
    email = unique_email()
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": libelle}
    )
    connexion = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert connexion.status_code == 200, connexion.text
    async with AsyncSessionLocal() as db:
        utilisateur = (await db.execute(select(User).where(User.email == email))).scalar_one()
        identifiant = utilisateur.id
    return {"id": identifiant, "token": connexion.json()["accessToken"], "libelle": libelle}


async def _organisation(client: AsyncClient, proprietaire: dict, nom: str) -> uuid.UUID:
    """Crée une organisation par l'API ; le créateur en devient propriétaire."""
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be248-{uuid.uuid4().hex[:10]}"},
        headers=_entete(proprietaire),
    )
    assert reponse.status_code in (200, 201), reponse.text
    return uuid.UUID(reponse.json()["id"])


async def _membre_avec_role(
    organisation_id: uuid.UUID, utilisateur_id: uuid.UUID, code_role: str, permissions: list[str]
) -> uuid.UUID:
    """Rattache l'utilisateur à l'organisation avec un rôle portant `permissions`.

    Retourne l'identifiant du rôle. Un rôle sans permission sert au cas « membre
    sans droit ». L'insertion directe évite de rejouer la chaîne d'attribution,
    qui n'est pas l'objet de ces tests.
    """
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organisation_id, userId=utilisateur_id))
        role = Role(organizationId=organisation_id, code=code_role, name=f"Rôle {code_role}")
        db.add(role)
        await db.flush()
        for code in permissions:
            permission = await get_or_create_permission(db, code, "rbac", f"Permission de test {code}")
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        db.add(UserRole(userId=utilisateur_id, organizationId=organisation_id, roleId=role.id))
        await db.commit()
        return role.id


async def _role_seul(organisation_id: uuid.UUID, code_role: str) -> uuid.UUID:
    """Un rôle de l'organisation, sans attribution : ressource à lire ou à refuser."""
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=organisation_id, code=code_role, name=f"Rôle {code_role}")
        db.add(role)
        await db.commit()
        return role.id


async def _nombre_de_roles(organisation_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(func.count()).select_from(Role).where(Role.organizationId == organisation_id))
        ).scalar_one()


@pytest.fixture
async def monde(client: AsyncClient) -> dict:
    """Tenants A et B, leurs propriétaires, un membre de B qui a ROLE_MANAGE, un
    membre de B sans droit, un non-membre de B, et un rôle de B et un rôle de A.

    Le tenant A est l'adversaire : son propriétaire a tous les droits chez lui
    mais aucun chez B."""
    proprietaire_b = await _compte(client, "proprietaire-b")
    proprietaire_a = await _compte(client, "proprietaire-a")
    organisation_b = await _organisation(client, proprietaire_b, "Tenant B")
    organisation_a = await _organisation(client, proprietaire_a, "Tenant A")

    membre_droit = await _compte(client, "membre-droit-b")
    membre_sans_droit = await _compte(client, "membre-sans-droit-b")
    non_membre = await _compte(client, "non-membre-b")
    await _membre_avec_role(organisation_b, membre_droit["id"], "gestionnaire_b", [ROLE_MANAGE])
    await _membre_avec_role(organisation_b, membre_sans_droit["id"], "lecteur_b", [])

    role_b = await _role_seul(organisation_b, "cible_b")
    role_a = await _role_seul(organisation_a, "cible_a")
    return {
        "organisation_a": organisation_a,
        "organisation_b": organisation_b,
        "adversaire": proprietaire_a,
        "membre_droit": membre_droit,
        "membre_sans_droit": membre_sans_droit,
        "non_membre": non_membre,
        "role_b": role_b,
        "role_a": role_a,
    }


# ---------------------------------------------------------------------------
# CA-1 : matrice allow/deny par parcours critique (routes HTTP réelles).
# ---------------------------------------------------------------------------

# Parcours retenus (proposition, dénominateur NON DÉFINI, QE-EXP-22) :
#   LISTE   : lire les rôles de l'organisation courante ;
#   LECTURE : lire un rôle précis de l'organisation courante.
# Chaque cas : (identifiant, acteur, organisation visée, ressource, statut attendu).
CAS_MATRICE = [
    ("liste_membre_avec_droit", "membre_droit", "organisation_b", None, "liste", 200),
    ("liste_membre_sans_droit", "membre_sans_droit", "organisation_b", None, "liste", 403),
    ("liste_non_membre", "non_membre", "organisation_b", None, "liste", 404),
    ("liste_adversaire_proprietaire_de_a", "adversaire", "organisation_b", None, "liste", 404),
    ("liste_non_authentifie", None, "organisation_b", None, "liste", 401),
    ("lecture_membre_avec_droit", "membre_droit", "organisation_b", "role_b", "lecture", 200),
    ("lecture_membre_sans_droit", "membre_sans_droit", "organisation_b", "role_b", "lecture", 403),
    ("lecture_non_membre", "non_membre", "organisation_b", "role_b", "lecture", 404),
    ("lecture_ressource_d_un_autre_tenant", "membre_droit", "organisation_b", "role_a", "lecture", 404),
    ("lecture_ressource_inexistante", "membre_droit", "organisation_b", "inexistant", "lecture", 404),
    ("lecture_non_authentifie", None, "organisation_b", "role_b", "lecture", 401),
]


@pytest.mark.parametrize(
    ("cas", "acteur", "organisation", "ressource", "parcours", "attendu"),
    CAS_MATRICE,
    ids=[c[0] for c in CAS_MATRICE],
)
async def test_ca1_matrice_allow_deny_par_parcours_critique(
    client: AsyncClient, monde: dict, cas, acteur, organisation, ressource, parcours, attendu
):
    """CA-1 : chaque combinaison acteur x tenant x ressource donne le statut attendu."""
    organisation_id = monde[organisation]
    if parcours == "liste":
        url = ROUTE_ROLES
    else:
        role_id = uuid.uuid4() if ressource == "inexistant" else monde[ressource]
        url = ROUTE_ROLE.format(role_id=role_id)

    entetes = {"X-Organization-Id": str(organisation_id)}
    if acteur is not None:
        entetes["Authorization"] = f"Bearer {monde[acteur]['token']}"
    reponse = await client.get(url, headers=entetes)
    assert reponse.status_code == attendu, f"{cas} : {reponse.status_code} {reponse.text}"


# ---------------------------------------------------------------------------
# CA-2 : le tenant adversaire ne lit ni n'écrit rien de B (API, export, tâche).
# ---------------------------------------------------------------------------


async def test_ca2_adversaire_ne_lit_rien_de_b_par_api(client: AsyncClient, monde: dict):
    """L'adversaire, propriétaire de A, ne voit ni la liste des rôles de B, ni un
    rôle de B : aucune réponse ne contient le code d'un rôle de B."""
    adversaire = monde["adversaire"]
    organisation_b = monde["organisation_b"]
    entetes = _entete(adversaire, organisation_b)

    liste = await client.get(ROUTE_ROLES, headers=entetes)
    lecture = await client.get(ROUTE_ROLE.format(role_id=monde["role_b"]), headers=entetes)

    assert liste.status_code == 404, liste.text
    assert lecture.status_code == 404, lecture.text
    assert "cible_b" not in liste.text and "gestionnaire_b" not in liste.text
    assert "cible_b" not in lecture.text


async def test_ca2_adversaire_n_ecrit_rien_dans_b_par_api(client: AsyncClient, monde: dict):
    """L'adversaire ne crée aucun rôle dans B : la réponse est refusée et le nombre
    de rôles de B ne change pas."""
    avant = await _nombre_de_roles(monde["organisation_b"])
    reponse = await client.post(
        ROUTE_CREER_ROLE.format(organisation_id=monde["organisation_b"]),
        json={"code": "intrus", "name": "Intrus", "permissionCodes": [ROLE_MANAGE]},
        headers=_entete(monde["adversaire"], monde["organisation_b"]),
    )
    apres = await _nombre_de_roles(monde["organisation_b"])

    assert reponse.status_code == 404, reponse.text
    assert apres == avant


async def test_ca2_export_de_facturation_refuse_a_l_adversaire(client: AsyncClient, monde: dict):
    """L'export des données de facturation de B est refusé à l'adversaire, quel que
    soit le compte payeur demandé. La réponse ne contient aucun identifiant de B."""
    reponse = await client.post(
        ROUTE_EXPORT,
        json={"accountId": str(uuid.uuid4()), "scope": "payeur"},
        headers=_entete(monde["adversaire"], monde["organisation_b"]),
    )
    assert reponse.status_code in (403, 404), reponse.text
    assert str(monde["organisation_b"]) not in reponse.text


async def test_ca2_tache_de_l_adversaire_ne_lit_rien_de_b(monde: dict):
    """Une tâche lancée par l'adversaire sur B est refusée (initiateur non membre
    de B) ; une tâche sans initiateur est refusée aussi."""
    async with AsyncSessionLocal() as db:
        par_adversaire = await decide_pour_tache(
            db,
            initiateur_id=monde["adversaire"]["id"],
            organization_id=monde["organisation_b"],
            permission_code=ROLE_MANAGE,
            resource_type="role",
            resource_id=monde["role_b"],
            resource_organization_id=monde["organisation_b"],
        )
        sans_initiateur = await decide_pour_tache(
            db,
            initiateur_id=None,
            organization_id=monde["organisation_b"],
            permission_code=ROLE_MANAGE,
        )
    assert par_adversaire.allowed is False
    assert par_adversaire.reason == ADHESION_INACTIVE
    assert sans_initiateur.allowed is False
    assert sans_initiateur.reason == AUTHENTIFICATION_REQUISE


# ---------------------------------------------------------------------------
# CA-3 : une panne de la dépendance d'autorisation donne un refus fermé.
# ---------------------------------------------------------------------------


async def test_ca3_panne_de_permission_ne_donne_jamais_une_decision_permise(monkeypatch, monde: dict):
    """Si le contrôle de permission échoue, `decide` ne renvoie pas « permis » : il
    propage l'erreur, et aucune décision favorable n'est produite."""

    async def panne(*args, **kwargs):
        raise RuntimeError("dépendance d'autorisation indisponible")

    monkeypatch.setattr(authz, "user_has_permission", panne)
    async with AsyncSessionLocal() as db:
        with pytest.raises(RuntimeError):
            await decide(
                db,
                user=await db.get(User, monde["membre_droit"]["id"]),
                organization_id=monde["organisation_b"],
                permission_code=ROLE_MANAGE,
                resource_type="role",
                resource_id=monde["role_b"],
                resource_organization_id=monde["organisation_b"],
            )


async def test_ca3_route_en_panne_d_autorisation_ne_livre_aucune_donnee(monkeypatch, monde: dict):
    """La route des rôles, pendant une panne du contrôle de permission, ne répond
    jamais 2xx et ne contient aucun rôle de B."""
    import app.rbac.service as rbac_service

    async def panne(*args, **kwargs):
        raise RuntimeError("dépendance d'autorisation indisponible")

    monkeypatch.setattr(rbac_service, "user_has_permission", panne)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client_panne:
        reponse = await client_panne.get(
            ROUTE_ROLES,
            headers=_entete(monde["membre_droit"], monde["organisation_b"]),
        )
    assert not (200 <= reponse.status_code < 300), reponse.text
    assert reponse.status_code >= 400
    assert "gestionnaire_b" not in reponse.text


# ---------------------------------------------------------------------------
# CA-4 : fixtures sans compte privilégié par défaut (inventaire).
# ---------------------------------------------------------------------------

AUTORISE_EN_AUTOUSE = {"apply_migrations"}
# Motif construit par concaténation : le fichier ne contient pas le mot recherché,
# sinon le test se trouverait lui-même.
MOTIF_PRIVILEGIE = re.compile(
    "is_super" + r"user|isSuper" + "user|super" + "admin|super_" + "admin|PLATFORM_" + "ADMIN",
    re.IGNORECASE,
)


def _fixtures_autouse(chemin: pathlib.Path) -> set[str]:
    """Noms des fixtures `autouse=True` déclarées dans un fichier de test."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    noms = set()
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorateur in noeud.decorator_list:
            if not isinstance(decorateur, ast.Call):
                continue
            if not (isinstance(decorateur.func, ast.Attribute) and decorateur.func.attr == "fixture"):
                continue
            for mot_cle in decorateur.keywords:
                if mot_cle.arg == "autouse" and isinstance(mot_cle.value, ast.Constant) and mot_cle.value.value is True:
                    noms.add(noeud.name)
    return noms


def test_ca4_inventaire_aucune_fixture_autouse_ne_cree_de_compte():
    """Seule la fixture de migration est autouse dans conftest.py : aucune autre ne
    crée un compte, donc aucun compte privilégié n'existe par défaut."""
    assert _fixtures_autouse(RACINE_TESTS / "conftest.py") == AUTORISE_EN_AUTOUSE


def test_ca4_inventaire_aucune_reference_a_un_compte_privilegie():
    """Ni les fixtures ni les tests de l'isolation ne font référence à un compte
    super-utilisateur ou plateforme."""
    fichiers = [RACINE_TESTS / "conftest.py", RACINE_TESTS / "test_be248_isolation_autorisation_bout_en_bout.py"]
    for fichier in fichiers:
        assert not MOTIF_PRIVILEGIE.search(fichier.read_text(encoding="utf-8")), fichier
