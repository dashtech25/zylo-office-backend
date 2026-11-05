"""Suite adversariale d'isolation tenant et de permissions HTTP (BE-038).

Tests écrits d'après la définition `### BE-038` de
implementation-backend/tasks-socle-tenant-identite.md, avant toute correction.

Périmètre : toutes les routes d'organisation, lues dans l'inventaire réel de
l'application (`tests/route_inventory.py`) : une route est « d'organisation » si
sa garde d'appartenance (`get_current_organization_id`) est présente. La liste
n'est donc pas écrite à la main : une route ajoutée plus tard est testée sans
modification de ce fichier.

Quatre familles de cas, chacune paramétrée par route (« METHODE /chemin ») :
- refus d'intrus (CA-1, CA-2) : un utilisateur sans appartenance reçoit 404
  `organization_not_found` uniforme, sans donnée de l'organisation ;
- refus de permission (CA-1) : un membre sans rôle reçoit 403 `permission_denied`
  sur chaque route qui exige une permission ;
- isolation entre deux organisations (CA-2) : le propriétaire de A, qui a tous
  ses droits sur A, est refusé (404) dès que le chemin ou l'en-tête désigne B,
  y compris pour un changement de contexte (en-tête A, chemin B et inverse) ;
- niveau inférieur (CA-5) : un membre ne détenant que `organization.members.read`
  est refusé (403) sur toute route qui exige une autre permission.

Scénarios explicites :
- CA-3 : un identifiant d'objet d'une autre organisation (deviné ou réel) donne
  la même réponse qu'un identifiant inexistant (statut et corps, hors
  `request_id`) ;
- CA-4 : un jeton d'accès expiré, ou dont la session est révoquée, est refusé en
  401 sans aucune donnée d'organisation dans la réponse ;
- CA-5 : un membre disposant de `rbac.role.manage` ne peut pas s'accorder un
  grant (`rbac.grant.manage`), privilège supérieur.

Couverture : `test_couverture_routes_organisation` vérifie que l'ensemble
paramétré correspond exactement à l'inventaire, pour qu'une suite vide ne
passe pas en silence.

Les rôles et appartenances de test sont posés directement en base, comme dans
test_be017_grants_membres.py.
"""

import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.main import app
from app.auth.models import RefreshToken
from app.core.database import AsyncSessionLocal
from app.core.security import famille_du_jeton_d_acces
from app.core.config import settings
from app.identity.models import OrganizationUser
from app.rbac.models import Permission, Role, RolePermission, UserRole
from tests.route_inventory import inventaire

# Le monde de test (deux organisations, cinq comptes) est construit une seule fois par module
# (bcrypt coûte ~0,3 s par hachage) : tous les tests partagent donc une boucle d'événements
# de module et un client ASGI de module, déclarés ici pour remplacer ceux de conftest.py.
pytestmark = pytest.mark.asyncio(loop_scope="module")

MOT_DE_PASSE = "TestPassword123!"
PERMISSION_INFERIEURE = "organization.members.read"
PERMISSION_ROLES = "rbac.role.manage"
PERMISSION_GRANTS = "rbac.grant.manage"
CODE_INTROUVABLE = "organization_not_found"
CODE_PERMISSION = "permission_denied"

ROUTES_ORGANISATION = sorted(i.cle for i in inventaire(app) if i.appartenance)
ROUTES_AVEC_PERMISSION = sorted(
    i.cle for i in inventaire(app) if i.appartenance and i.permissions
)
ROUTES_SANS_PERMISSION_EXPLICITE = sorted(
    i.cle for i in inventaire(app) if i.appartenance and not i.permissions
)
PERMISSIONS_PAR_ROUTE = {i.cle: i.permissions for i in inventaire(app)}


# ---------------------------------------------------------------------------
# Aides de construction des requêtes
# ---------------------------------------------------------------------------


# Paramètre de chemin -> clé de l'objet réel de l'organisation A (`_objets_organisation`).
# Un paramètre absent de ce tableau reçoit un identifiant au hasard.
OBJET_PAR_PARAMETRE = {
    "alert_id": "alerte",
    "tank_id": "cuve",
    "delivery_id": "livraison",
    "leak_event_id": "fuite",
    "price_id": "prix",
    "pump_id": "pompe",
    "report_id": "rapport",
    "line_id": "ligne_pompe",
    "movement_id": "mouvement",
    "handover_id": "passation",
    "item_id": "ligne_passation",
}


def _url(cle: str, organisation: str, objets: dict | None = None) -> tuple[str, str]:
    """Méthode et URL d'une route de l'inventaire, chemin instancié.

    Le paramètre `organization_id` reçoit l'organisation visée ; `module_code`
    reçoit un module réel ; un paramètre de ressource reçoit l'objet réel de
    l'organisation A quand il existe (`objets`), sinon un identifiant au hasard.
    Un objet réel est nécessaire : les gardes à portée (`require_permission_scoped_via`)
    chargent la ressource avant le contrôle de permission, donc un identifiant
    inexistant répond 404 au lieu du 403 attendu pour un membre sans droit.
    Le corps est vide : les gardes s'exécutent avant la validation du corps, donc
    un refus doit être émis sans corps valide."""
    methode, chemin = cle.split(" ", 1)

    def remplace(m: re.Match) -> str:
        nom = m.group(1)
        if nom == "organization_id":
            return organisation
        if nom == "module_code":
            return "zylo_liquid"
        if objets and OBJET_PAR_PARAMETRE.get(nom) in objets:
            return str(objets[OBJET_PAR_PARAMETRE[nom]])
        return str(uuid.uuid4())

    return methode, re.sub(r"\{(\w+)\}", remplace, chemin)


async def _appeler(client: AsyncClient, cle: str, headers: dict, organisation: str, objets: dict | None = None):
    methode, url = _url(cle, organisation, objets)
    kwargs: dict = {"headers": headers}
    if methode in {"POST", "PUT", "PATCH"}:
        kwargs["json"] = {}
    return await client.request(methode, url, **kwargs)


def _entetes(jeton: str, organisation: str) -> dict:
    return {"Authorization": f"Bearer {jeton}", "X-Organization-Id": organisation}


def _sans_request_id(corps):
    """Corps de réponse sans identifiant de requête (propre à chaque appel)."""
    if isinstance(corps, dict):
        return {k: _sans_request_id(v) for k, v in corps.items() if k != "request_id"}
    if isinstance(corps, list):
        return [_sans_request_id(v) for v in corps]
    return corps


async def _inscrire(client: AsyncClient, nom: str) -> dict:
    email = f"be038-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": nom})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    jeton = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton}"})
    assert me.status_code == 200, me.text
    return {"jeton": jeton, "userId": me.json()["id"], "nom": nom, "email": email}


async def _nouvelle_session(client: AsyncClient, email: str) -> str:
    """Connexion supplémentaire : une famille de session distincte, pour les tests qui la révoquent."""
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    return login.json()["accessToken"]


async def _creer_organisation(client: AsyncClient, proprietaire: dict, nom: str) -> str:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be038-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": f"Bearer {proprietaire['jeton']}"},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _permission(db, code: str) -> Permission:
    permission = await db.scalar(select(Permission).where(Permission.code == code))
    if permission is None:
        permission = Permission(code=code, moduleCode="identity", description="Permission de test BE-038")
        db.add(permission)
        await db.flush()
    return permission


async def _ajouter_membre(organisation_id: str, utilisateur_id: str, permissions: list[str]) -> None:
    """Rattache l'utilisateur à l'organisation avec un rôle ne contenant que `permissions`."""
    org = uuid.UUID(organisation_id)
    user = uuid.UUID(utilisateur_id)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=org, userId=user))
        if permissions:
            role = Role(organizationId=org, code=f"be038-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-038")
            db.add(role)
            await db.flush()
            for code in permissions:
                permission = await _permission(db, code)
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=user, organizationId=org, roleId=role.id))
        await db.commit()


async def _objets_organisation(client: AsyncClient, proprietaire: dict, org_a: str) -> dict:
    """Objets réels du module zylo_liquid dans l'organisation A, pour que chaque route à portée
    atteigne sa vérification de permission (voir `_url`).

    Station, produit, cuve, pompes et définition de tour sont créés par l'API. Occurrence de tour,
    rapport, ligne de pompe, prix, alerte, fuite, livraison, passation, ligne de passation et
    mouvement de personnel sont posés directement en base, comme dans test_zylo_liquid_pump_closing.py
    (`_open_tour`) : ces objets ne sont produits par aucune route de création, ou le seraient
    seulement après un planning qui exige des pompistes activés."""
    from app.alerts.models import Alert
    from app.modules.zylo_liquid.models import (
        DeliveryDetected,
        LeakageRecord,
        PriceHistory,
        ShiftHandover,
        ShiftHandoverItem,
        ShiftOccurrence,
        ShiftReport,
        ShiftReportPumpLine,
        ShiftStaffMovement,
    )
    from app.shared.currency import Currency

    h = _entetes(proprietaire["jeton"], org_a)
    suffixe = uuid.uuid4().hex[:6]

    async def zl(methode: str, chemin: str, corps: dict | None = None):
        res = await client.request(methode, f"/api/v1/zylo-liquid{chemin}", json=corps, headers=h)
        assert res.status_code in (200, 201), res.text
        return res.json()

    station = (await zl("post", "/stations", {"name": f"Station BE-038 {suffixe}", "code": f"E{suffixe}"}))["id"]
    produit = (await zl("post", "/fuel-products", {"name": f"Super{suffixe}", "code": f"SU{suffixe}"}))["id"]
    cuve = (await zl("post", "/tanks", {
        "stationId": station, "fuelProductId": produit, "tankNumber": 1, "displayName": "Cuve BE-038",
        "capacityLiters": 20000, "tankHeightMm": 3000, "heightAlarmMm": 2800, "heightAlertMm": 2600, "lowAlarmMm": 300,
    }))["id"]
    pompes = [p["id"] for p in (await zl("post", "/pumps/bulk", {"stationId": station, "rows": [
        {"rowNumber": 1, "tankId": cuve, "pumpNumber": 1},
        {"rowNumber": 2, "tankId": cuve, "pumpNumber": 2},
    ]}))["data"]]
    definition = (await zl("post", "/shift-definitions/bulk", {"stationId": station, "rows": [
        {"rowNumber": 1, "shiftNumber": 1, "name": "Journée", "startTime": "00:00", "endTime": "00:00"},
    ]}))["data"][0]
    # Le propriétaire tient le tour : une personne invitée reste inactive tant qu'elle n'a pas activé
    # son compte, et le planning la refuserait (`person_inactive`).
    rt = proprietaire["userId"]
    maintenant = datetime.now(timezone.utc)
    aujourdhui = date.today()
    async with AsyncSessionLocal() as db:
        occ = ShiftOccurrence(
            stationId=uuid.UUID(station), shiftDefinitionId=uuid.UUID(definition["id"]), shiftDate=aujourdhui, shiftNumber=1,
            name="Journée", startTime="00:00", endTime="00:00", startsAt=datetime.combine(aujourdhui, time(0, 0)),
            endsAt=datetime.combine(aujourdhui, time(0, 0)) + timedelta(days=1), status="opened", openedAt=maintenant,
            openedByUserId=uuid.UUID(rt), offPlanning=True,
        )
        db.add(occ)
        await db.flush()
        rapport = ShiftReport(
            stationId=uuid.UUID(station), occurrenceId=occ.id, shiftDate=occ.shiftDate, shiftNumber=occ.shiftNumber, shiftName=occ.name,
            startTime=occ.startTime, endTime=occ.endTime, responsibleUserId=uuid.UUID(rt), openedByUserId=uuid.UUID(rt), openedAt=maintenant,
        )
        db.add(rapport)
        await db.flush()
        lignes = []
        for numero, pompe in enumerate(pompes, start=1):
            ligne = ShiftReportPumpLine(
                reportId=rapport.id, pumpId=uuid.UUID(pompe), pumpNumber=numero, pumpName=f"Pompe {numero}", tankId=uuid.UUID(cuve),
                fuelProductName="Super", openingIndex=Decimal("1000.00"), openingSource="initial",
            )
            db.add(ligne)
            lignes.append(ligne)
        await db.flush()

        mouvement = ShiftStaffMovement(
            reportId=rapport.id, stationId=uuid.UUID(station), kind="break_start", occurredAt=maintenant, recordedAt=maintenant,
            recordedByUserId=uuid.UUID(rt), subjectUserId=uuid.UUID(rt),
        )
        db.add(mouvement)

        devise = (await db.execute(select(Currency).limit(1))).scalar_one_or_none()
        if devise is None:
            devise = Currency(code="XAF", name="Franc CFA", symbol="FCFA", decimalPlaces=0)
            db.add(devise)
            await db.flush()
        prix = PriceHistory(
            stationId=uuid.UUID(station), fuelProductId=uuid.UUID(produit), currencyId=devise.id, priceAmount=Decimal("840"),
            effectiveFrom=maintenant.replace(tzinfo=None) - timedelta(days=1), createdBy=uuid.UUID(rt),
        )
        db.add(prix)

        # Ces colonnes sont sans fuseau (naïves, UTC) : leur passer une date aware échoue côté asyncpg.
        naif = maintenant.replace(tzinfo=None)
        alerte = Alert(stationId=uuid.UUID(station), tankId=uuid.UUID(cuve), type="level_high", severity="high", status="active", triggeredAt=naif)
        db.add(alerte)

        fuite = LeakageRecord(
            tankId=uuid.UUID(cuve), startTime=naif - timedelta(hours=2), startHeightMm=1000, endTime=naif - timedelta(hours=1),
            endHeightMm=1000, result="normal",
        )
        db.add(fuite)

        livraison = DeliveryDetected(
            tankId=uuid.UUID(cuve), startTime=naif - timedelta(hours=3), startHeightMm=500, endTime=naif - timedelta(hours=2),
            endHeightMm=1500,
        )
        db.add(livraison)

        passation = ShiftHandover(
            stationId=uuid.UUID(station), occurrenceId=occ.id, nothingToReport=False, firstSignedByUserId=uuid.UUID(rt),
            firstSignedAt=maintenant, lastSignedByUserId=uuid.UUID(rt), lastSignedAt=maintenant,
        )
        db.add(passation)
        await db.flush()

        ligne_passation = ShiftHandoverItem(
            handoverId=passation.id, position=1, kind="open_issue", category="other", description="Anomalie de test BE-038",
            importance="normal", status="open", authorUserId=uuid.UUID(rt), authorRole="station_admin", declaredAt=maintenant,
        )
        db.add(ligne_passation)
        # Identifiants lus avant le commit : après commit, les attributs expirent et leur relecture
        # exigerait un accès base hors contexte asynchrone.
        await db.flush()
        objets = {
            "station": station,
            "cuve": cuve,
            "pompe": pompes[0],
            "pompes": pompes,
            "rapport": str(rapport.id),
            "ligne_pompe": str(lignes[0].id),
            "mouvement": str(mouvement.id),
            "prix": str(prix.id),
            "alerte": str(alerte.id),
            "fuite": str(fuite.id),
            "livraison": str(livraison.id),
            "passation": str(passation.id),
            "ligne_passation": str(ligne_passation.id),
        }
        await db.commit()
        return objets


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client():
    """Client ASGI de module : remplace le client par test de conftest.py (même démarrage)."""
    from app.core.database import engine
    from app.modules.zylo_liquid.seed import seed_known_permissions
    from app.modules.zylo_tanker.seed import seed_known_permissions as seed_zylo_tanker_permissions
    from app.modules_registry.seed import seed_known_modules

    await engine.dispose()
    await seed_known_modules()
    await seed_known_permissions()
    await seed_zylo_tanker_permissions()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def monde(client: AsyncClient) -> dict:
    """Deux organisations A et B, chacune avec son propriétaire ; un intrus sans
    appartenance ; dans A, un membre sans rôle et un membre de niveau inférieur
    (`organization.members.read` seul) ; dans A, un membre administrateur des
    rôles (`rbac.role.manage` seul)."""
    proprietaire_a = await _inscrire(client, "Proprietaire A")
    org_a = await _creer_organisation(client, proprietaire_a, "Organisation A BE-038")
    proprietaire_b = await _inscrire(client, "Proprietaire B")
    org_b = await _creer_organisation(client, proprietaire_b, "Organisation B BE-038")

    intrus = await _inscrire(client, "Intrus")
    membre_sans_droit = await _inscrire(client, "Membre sans droit")
    inferieur = await _inscrire(client, "Membre inferieur")
    gestionnaire_roles = await _inscrire(client, "Gestionnaire des rôles")
    await _ajouter_membre(org_a, membre_sans_droit["userId"], [])
    await _ajouter_membre(org_a, inferieur["userId"], [PERMISSION_INFERIEURE])
    await _ajouter_membre(org_a, gestionnaire_roles["userId"], [PERMISSION_ROLES])

    # Les modules métier sont activés dans A et B : sinon `module_inactive` masquerait le
    # contrôle de permission des routes de module (le propriétaire reçoit alors les droits du module).
    for org, proprietaire in ((org_a, proprietaire_a), (org_b, proprietaire_b)):
        for code in ("zylo_liquid", "zylo_tanker"):
            res = await client.post(
                f"/api/v1/modules/organizations/{org}/activate",
                json={"moduleCode": code},
                headers={"Authorization": f"Bearer {proprietaire['jeton']}", "X-Organization-Id": org},
            )
            assert res.status_code == 200, res.text

    objets = await _objets_organisation(client, proprietaire_a, org_a)

    return {
        "a": {"id": org_a, "nom": "Organisation A BE-038", "proprietaire": proprietaire_a},
        "b": {"id": org_b, "nom": "Organisation B BE-038", "proprietaire": proprietaire_b},
        "intrus": intrus,
        "membre_sans_droit": membre_sans_droit,
        "inferieur": inferieur,
        "gestionnaire_roles": gestionnaire_roles,
        "objets": objets,
    }


# ---------------------------------------------------------------------------
# Couverture (CA-1, CA-2)
# ---------------------------------------------------------------------------


def test_couverture_routes_organisation():
    """L'ensemble paramétré est l'inventaire réel : aucune route d'organisation oubliée,
    et la suite n'est pas vide (garde contre un test vacueux)."""
    inventaire_appartenance = {i.cle for i in inventaire(app) if i.appartenance}
    assert len(ROUTES_ORGANISATION) > 300
    assert set(ROUTES_ORGANISATION) == inventaire_appartenance
    assert ROUTES_AVEC_PERMISSION, "aucune route avec permission : l'inventaire est inopérant"


# ---------------------------------------------------------------------------
# CA-1 et CA-2 : refus d'intrus, refus de permission, isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cle", ROUTES_ORGANISATION)
async def test_intrus_sans_appartenance_recoit_404_uniforme(client: AsyncClient, monde: dict, cle: str):
    """CA-1, CA-2 : sans appartenance à A, aucune réponse de succès et aucune donnée de A."""
    org_a = monde["a"]["id"]
    res = await _appeler(client, cle, _entetes(monde["intrus"]["jeton"], org_a), org_a, monde["objets"])
    assert res.status_code == 404, f"{cle} -> {res.status_code} {res.text[:300]}"
    assert res.json()["error"]["code"] == CODE_INTROUVABLE
    assert monde["a"]["nom"] not in res.text


@pytest.mark.parametrize("cle", ROUTES_AVEC_PERMISSION)
async def test_membre_sans_permission_recoit_403(client: AsyncClient, monde: dict, cle: str):
    """CA-1 : un membre sans rôle reçoit 403 `permission_denied` sur chaque route qui exige
    une permission, et jamais de succès."""
    org_a = monde["a"]["id"]
    res = await _appeler(client, cle, _entetes(monde["membre_sans_droit"]["jeton"], org_a), org_a, monde["objets"])
    assert res.status_code == 403, f"{cle} -> {res.status_code} {res.text[:300]}"
    assert res.json()["error"]["code"] == CODE_PERMISSION


@pytest.mark.parametrize("cle", ROUTES_SANS_PERMISSION_EXPLICITE)
async def test_route_sans_permission_explicite_reste_gardee_par_appartenance(client: AsyncClient, monde: dict, cle: str):
    """CA-1 : pour une route sans permission déclarée, le membre n'a pas de refus de droit
    à attendre, mais l'appartenance reste exigée : l'intrus est refusé (déjà couvert ci-dessus) et
    un membre d'une AUTRE organisation ne peut pas agir sur A."""
    org_a = monde["a"]["id"]
    res = await _appeler(client, cle, _entetes(monde["b"]["proprietaire"]["jeton"], org_a), org_a, monde["objets"])
    assert res.status_code == 404, f"{cle} -> {res.status_code} {res.text[:300]}"
    assert res.json()["error"]["code"] == CODE_INTROUVABLE


@pytest.mark.parametrize("cle", ROUTES_ORGANISATION)
async def test_proprietaire_de_a_refuse_sur_b_et_changement_de_contexte(client: AsyncClient, monde: dict, cle: str):
    """CA-2 : le propriétaire de A, qui a tous ses droits sur A, est refusé (404) sur B
    (chemin et en-tête), et sur tout changement de contexte entre A et B."""
    org_a, org_b = monde["a"]["id"], monde["b"]["id"]
    jeton_a = monde["a"]["proprietaire"]["jeton"]
    if "{organization_id}" in cle:
        # Le chemin porte l'organisation : on croise en-tête et chemin pour tester la cohérence.
        cas = {
            "en-tête B, chemin B": (_entetes(jeton_a, org_b), org_b),
            "en-tête A, chemin B": (_entetes(jeton_a, org_a), org_b),
            "en-tête B, chemin A": (_entetes(jeton_a, org_b), org_a),
        }
    else:
        # Pas d'organisation dans le chemin : seul l'en-tête désigne B. (Un en-tête A avec un
        # chemin sans organisation est une requête légitime sur A, pas un cas d'isolation.)
        cas = {"en-tête B": (_entetes(jeton_a, org_b), org_b)}
    for nom, (entetes, chemin_org) in cas.items():
        res = await _appeler(client, cle, entetes, chemin_org, monde["objets"])
        assert res.status_code == 404, f"{cle} [{nom}] -> {res.status_code} {res.text[:300]}"
        assert res.json()["error"]["code"] == CODE_INTROUVABLE, f"{cle} [{nom}]"
        assert monde["b"]["nom"] not in res.text, f"{cle} [{nom}] fuite du nom de B"


# ---------------------------------------------------------------------------
# CA-5 : niveau inférieur, privilège supérieur
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cle",
    [c for c in ROUTES_AVEC_PERMISSION if PERMISSION_INFERIEURE not in PERMISSIONS_PAR_ROUTE[c]],
)
async def test_membre_de_niveau_inferieur_ne_reussit_pas_action_reservee(client: AsyncClient, monde: dict, cle: str):
    """CA-5 : un membre qui ne détient que `organization.members.read` ne peut pas exécuter
    une route réservée à une autre permission."""
    org_a = monde["a"]["id"]
    res = await _appeler(client, cle, _entetes(monde["inferieur"]["jeton"], org_a), org_a, monde["objets"])
    assert res.status_code == 403, f"{cle} -> {res.status_code} {res.text[:300]}"
    assert res.json()["error"]["code"] == CODE_PERMISSION


async def test_administrateur_des_roles_ne_peut_pas_s_accorder_un_grant(client: AsyncClient, monde: dict):
    """CA-5 (privilège supérieur) : détenir `rbac.role.manage` ne donne pas `rbac.grant.manage`.
    Le gestionnaire ne peut ni créer un grant sur lui-même, ni en révoquer un."""
    org_a = monde["a"]["id"]
    gestionnaire = monde["gestionnaire_roles"]
    entetes = _entetes(gestionnaire["jeton"], org_a)
    res = await client.post(
        f"/api/v1/organizations/current/members/{gestionnaire['userId']}/grants",
        json={"permissionCode": PERMISSION_GRANTS, "effect": "allow"},
        headers=entetes,
    )
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == CODE_PERMISSION
    res = await client.delete(
        f"/api/v1/organizations/current/members/{gestionnaire['userId']}/grants/{uuid.uuid4()}",
        headers=entetes,
    )
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == CODE_PERMISSION


# ---------------------------------------------------------------------------
# CA-3 : objets devinés ou d'une autre organisation
# ---------------------------------------------------------------------------


async def test_identifiant_devine_d_une_autre_organisation_repond_comme_un_inexistant(client: AsyncClient, monde: dict):
    """CA-3 : un rôle réel de B, demandé depuis A, donne la même réponse qu'un identifiant
    inexistant. Les deux routes testées sont celle d'organisation courante et celle du chemin."""
    org_a, org_b = monde["a"]["id"], monde["b"]["id"]
    jeton_a = monde["a"]["proprietaire"]["jeton"]
    liste = await client.get(f"/api/v1/rbac/organizations/{org_b}/roles", headers=_entetes(monde["b"]["proprietaire"]["jeton"], org_b))
    assert liste.status_code == 200, liste.text
    roles_b = liste.json()
    assert roles_b, "B doit avoir au moins un rôle pour ce test"
    role_b = roles_b[0]["id"]
    inexistant = str(uuid.uuid4())

    gabarits = [
        (f"/api/v1/organizations/current/roles/{{}}", _entetes(jeton_a, org_a)),
        (f"/api/v1/rbac/organizations/{org_a}/roles/{{}}", _entetes(jeton_a, org_a)),
    ]
    for gabarit, entetes in gabarits:
        devine = await client.get(gabarit.format(role_b), headers=entetes)
        absent = await client.get(gabarit.format(inexistant), headers=entetes)
        assert devine.status_code == absent.status_code == 404, (gabarit, devine.text, absent.text)
        assert _sans_request_id(devine.json()) == _sans_request_id(absent.json()), gabarit
        assert role_b not in devine.text, gabarit


async def test_identifiant_de_membre_devine_repond_comme_un_inexistant(client: AsyncClient, monde: dict):
    """CA-3 : un membre de B (identifiant réel) visé dans A, comme un identifiant inexistant."""
    org_a = monde["a"]["id"]
    jeton_a = monde["a"]["proprietaire"]["jeton"]
    cible_b = monde["b"]["proprietaire"]["userId"]
    entetes = _entetes(jeton_a, org_a)
    devine = await client.get(f"/api/v1/rbac/organizations/{org_a}/users/{cible_b}/grants", headers=entetes)
    absent = await client.get(f"/api/v1/rbac/organizations/{org_a}/users/{uuid.uuid4()}/grants", headers=entetes)
    assert devine.status_code == absent.status_code, (devine.text, absent.text)
    assert _sans_request_id(devine.json()) == _sans_request_id(absent.json())


# ---------------------------------------------------------------------------
# CA-4 : session expirée ou révoquée pendant la requête
# ---------------------------------------------------------------------------

ROUTES_SESSION = [
    "GET /api/v1/organizations/current",
    "GET /api/v1/organizations/current/members",
    "GET /api/v1/rbac/organizations/{organization_id}/roles",
]


@pytest.mark.parametrize("cle", ROUTES_SESSION)
async def test_jeton_d_acces_expire_est_refuse_sans_fuite(client: AsyncClient, monde: dict, cle: str):
    """CA-4 : un jeton d'accès dont l'expiration est passée est refusé en 401, et la réponse
    ne contient aucune donnée de l'organisation."""
    org_a = monde["a"]["id"]
    jeton_valide = monde["a"]["proprietaire"]["jeton"]
    famille = famille_du_jeton_d_acces(jeton_valide)
    assert famille is not None
    maintenant = datetime.now(timezone.utc)
    expire = jwt.encode(
        {
            "sub": monde["a"]["proprietaire"]["userId"],
            "type": "access",
            "iat": maintenant - timedelta(hours=2),
            "exp": maintenant - timedelta(hours=1),
            "jti": str(uuid.uuid4()),
            "fam": str(famille),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    methode, url = _url(cle, org_a, monde["objets"])
    res = await client.request(methode, url, headers=_entetes(expire, org_a))
    assert res.status_code == 401, res.text
    assert monde["a"]["nom"] not in res.text
    assert monde["a"]["proprietaire"]["nom"] not in res.text


async def test_session_revoquee_pendant_l_usage_est_refusee_sans_fuite(client: AsyncClient, monde: dict):
    """CA-4 : une session révoquée (refresh token de la famille révoqué) rend refusé le jeton
    d'accès encore valide, sur une route qui renverrait normalement la liste des membres.
    Une session fraîche est utilisée, pour ne pas révoquer celle des autres tests du module."""
    org_a = monde["a"]["id"]
    jeton = await _nouvelle_session(client, monde["a"]["proprietaire"]["email"])
    avant = await client.get("/api/v1/organizations/current/members", headers=_entetes(jeton, org_a))
    assert avant.status_code == 200, avant.text
    famille = famille_du_jeton_d_acces(jeton)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.familyId == famille)
            .values(revokedAt=datetime.now(timezone.utc))
        )
        await db.commit()
    apres = await client.get("/api/v1/organizations/current/members", headers=_entetes(jeton, org_a))
    assert apres.status_code == 401, apres.text
    assert monde["a"]["nom"] not in apres.text
    assert "@zylo-office-test.example.com" not in apres.text
