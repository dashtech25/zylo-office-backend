"""BE-159 : approbation des changements de paramètres sensibles.

Tests écrits d'après la définition `### BE-159` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : un changement d'un paramètre sensible crée une demande en attente (202) et ne modifie
  pas la valeur active ;
- CA-2 : une approbation par un autre utilisateur applique la valeur (nouvelle version appliquée)
  et journalise EVT-SET-02 avec demande, approbateur et motif ;
- CA-3 : un demandeur ne peut pas décider sa propre demande (403) ; sans `settings.approve`,
  une décision est refusée (403), sans rien écrire ;
- CA-4 : une seconde décision sur une demande déjà approuvée ou rejetée renvoie 409
  VERSION_CONFLICT et n'écrit rien ;
- CA-5 : un approbateur d'un autre tenant ne peut pas décider la demande (404) ;
- rejet : une demande rejetée ne modifie pas la valeur active ; `GET` lit le statut.

Hypothèses de test (points NON DÉFINI, à confirmer en QE) :
- routes : `POST /api/v1/approbations/{demande_id}/decisions` et `GET /api/v1/approbations/{demande_id}`
  (QE-PAR-02) ; corps de décision `{"decision": "approuver" | "rejeter", "motif": ...}` ;
- création de la demande : `PUT /api/v1/parametres/organisation/{org}/{cle}` sur un paramètre
  `sensitive` renvoie 202 avec `id` et `statut` (code 202 non tranché par la définition) ;
- permission de décision : `settings.approve` (QE-PAR-03, nom tel qu'écrit par la définition) ;
- statuts : `en_attente`, `approuvé`, `rejeté` (valeurs de la définition) ;
- « sensible » est lu comme l'attribut existant `SettingDefinition.sensitive` (QE à trancher :
  ce drapeau sert aussi à masquer les valeurs dans l'audit, BE-154) ;
- journal : entrée `AuditEvent` dont `entityId` est l'identifiant de la demande et dont
  `changes["evenement"] == "EVT-SET-02"`.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.parametres.models import SettingDefinition, SettingValue
from app.parametres.service import ecrire_version
from app.rbac.models import Permission, Role, RolePermission, UserRole
from app.rbac.service import get_or_create_permission

URL_PARAMETRES = "/api/v1/parametres"
URL_APPROBATIONS = "/api/v1/approbations"
PERMISSION_APPLIQUER = "parametres.setting.apply"
PERMISSION_APPROUVER = "settings.approve"
MOT_DE_PASSE = "TestPassword123!"


async def _accorder_au_proprietaire(permission_code: str, org_id: uuid.UUID) -> None:
    """Accorde une permission au rôle propriétaire de l'organisation (helper local au test)."""
    async with AsyncSessionLocal() as db:
        role = (await db.execute(select(Role).where(Role.organizationId == org_id, Role.code == "owner"))).scalar_one()
        permission = await get_or_create_permission(db, permission_code, "parametres", "Permission de test BE-159.")
        db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        await db.commit()


async def _inscrire_membre(client: AsyncClient, org_id: uuid.UUID, permissions: list[str]) -> dict:
    """Crée un second compte, le rattache à l'organisation avec un rôle ne portant que `permissions`.

    Renvoie son jeton d'accès et son identifiant. Les appartenances et rôles sont posés directement
    en base, comme dans test_be015 ; le compte lui-même passe par la route d'inscription.
    """
    email = f"be159-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Membre BE-159"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    user_id = await _utilisateur_id(email)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=org_id, userId=user_id))
        if permissions:
            role = Role(organizationId=org_id, code=f"be159-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-159")
            db.add(role)
            await db.flush()
            for code in permissions:
                permission = await get_or_create_permission(db, code, "parametres", "Permission de test BE-159.")
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=user_id, organizationId=org_id, roleId=role.id))
        await db.commit()
    return {"id": str(user_id), "email": email, "accessToken": login.json()["accessToken"]}


async def _definition_sensible(valeur_par_defaut: str = "defaut") -> str:
    """Crée une définition de paramètre sensible de portée organisation."""
    cle = f"be159.{uuid.uuid4().hex[:12]}"
    async with AsyncSessionLocal() as db:
        db.add(
            SettingDefinition(
                key=cle, scopeKind="organisation", owner="test", valueType="texte",
                defaultValue=valeur_par_defaut, sensitive=True,
            )
        )
        await db.commit()
    return cle


async def _version_appliquee(cle: str, org_id: uuid.UUID, user_id: uuid.UUID, valeur: str) -> None:
    """Insère la version 1 appliquée du paramètre pour l'organisation."""
    async with AsyncSessionLocal() as db:
        await ecrire_version(db, cle, "organisation", org_id, 1, valeur, user_id, "initial", applied=True)


async def _valeurs(cle: str, org_id: uuid.UUID) -> list[tuple[int, bool, object]]:
    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(
                select(SettingValue.version, SettingValue.applied, SettingValue.value)
                .where(SettingValue.definitionKey == cle, SettingValue.scopeId == org_id)
                .order_by(SettingValue.version)
            )
        ).all()
    return [tuple(ligne) for ligne in lignes]


async def _nombre_evenements_approbation(demande_id: str) -> int:
    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(select(AuditEvent.changes).where(AuditEvent.entityId == uuid.UUID(demande_id)))
        ).scalars().all()
    return sum(1 for changes in lignes if changes and changes.get("evenement") == "EVT-SET-02")


async def _utilisateur_id(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


def _entetes(acteur: dict, org_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {acteur['accessToken']}", "X-Organization-Id": org_id}


async def _demander(client: AsyncClient, demandeur: dict, org_id: str, cle: str, valeur: str, motif: str) -> dict:
    """Crée une demande de changement de `cle` via la route de paramètres (CA-1)."""
    reponse = await client.put(
        f"{URL_PARAMETRES}/organisation/{org_id}/{cle}",
        json={"value": valeur, "reason": motif},
        headers={**_entetes(demandeur, org_id), "X-Expected-Version": "1"},
    )
    assert reponse.status_code == 202, reponse.text
    return reponse.json()


async def test_be159_ca1_changement_sensible_cree_demande_sans_modifier_la_valeur(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = organization["id"]
    cle = await _definition_sensible()
    await _version_appliquee(cle, uuid.UUID(org_id), await _utilisateur_id(registered_user["email"]), "v1")
    await _accorder_au_proprietaire(PERMISSION_APPLIQUER, uuid.UUID(org_id))

    demande = await _demander(client, registered_user, org_id, cle, "v2", "passage en production")

    assert demande["statut"] == "en_attente", "la demande attend une décision"
    assert await _valeurs(cle, uuid.UUID(org_id)) == [(1, True, "v1")], "la valeur active ne change pas"


async def test_be159_ca2_approbation_par_un_autre_utilisateur_applique_la_valeur(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = organization["id"]
    cle = await _definition_sensible()
    await _version_appliquee(cle, uuid.UUID(org_id), await _utilisateur_id(registered_user["email"]), "v1")
    await _accorder_au_proprietaire(PERMISSION_APPLIQUER, uuid.UUID(org_id))
    demande = await _demander(client, registered_user, org_id, cle, "v2", "passage en production")
    approbateur = await _inscrire_membre(client, uuid.UUID(org_id), [PERMISSION_APPROUVER])

    reponse = await client.post(
        f"{URL_APPROBATIONS}/{demande['id']}/decisions",
        json={"decision": "approuver", "motif": "validé par la direction"},
        headers=_entetes(approbateur, org_id),
    )

    assert reponse.status_code == 200, reponse.text
    assert await _valeurs(cle, uuid.UUID(org_id)) == [(1, False, "v1"), (2, True, "v2")], "la valeur approuvée devient la version appliquée"
    assert await _nombre_evenements_approbation(demande["id"]) == 1, "EVT-SET-02 est journalisé une fois"
    lue = await client.get(f"{URL_APPROBATIONS}/{demande['id']}", headers=_entetes(approbateur, org_id))
    assert lue.json()["statut"] == "approuvé"
    assert lue.json()["approbateur"] == approbateur["id"], "l'approbateur est enregistré"


async def test_be159_ca3_demandeur_ne_peut_pas_decider_sa_propre_demande(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = organization["id"]
    cle = await _definition_sensible()
    await _version_appliquee(cle, uuid.UUID(org_id), await _utilisateur_id(registered_user["email"]), "v1")
    await _accorder_au_proprietaire(PERMISSION_APPLIQUER, uuid.UUID(org_id))
    await _accorder_au_proprietaire(PERMISSION_APPROUVER, uuid.UUID(org_id))
    demande = await _demander(client, registered_user, org_id, cle, "v2", "auto-approbation")

    reponse = await client.post(
        f"{URL_APPROBATIONS}/{demande['id']}/decisions",
        json={"decision": "approuver", "motif": "auto"},
        headers=_entetes(registered_user, org_id),
    )

    assert reponse.status_code == 403, reponse.text
    assert await _valeurs(cle, uuid.UUID(org_id)) == [(1, True, "v1")], "une auto-approbation n'écrit rien"


async def test_be159_ca3_decision_sans_settings_approve_renvoie_403(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = organization["id"]
    cle = await _definition_sensible()
    await _version_appliquee(cle, uuid.UUID(org_id), await _utilisateur_id(registered_user["email"]), "v1")
    await _accorder_au_proprietaire(PERMISSION_APPLIQUER, uuid.UUID(org_id))
    demande = await _demander(client, registered_user, org_id, cle, "v2", "sans droit")
    sans_droit = await _inscrire_membre(client, uuid.UUID(org_id), [])

    reponse = await client.post(
        f"{URL_APPROBATIONS}/{demande['id']}/decisions",
        json={"decision": "approuver", "motif": "sans droit"},
        headers=_entetes(sans_droit, org_id),
    )

    assert reponse.status_code == 403, reponse.text
    assert "PERMISSION_DENIED" in reponse.text
    assert await _valeurs(cle, uuid.UUID(org_id)) == [(1, True, "v1")]


async def test_be159_ca4_seconde_decision_sur_demande_tranchee_renvoie_409(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = organization["id"]
    cle = await _definition_sensible()
    await _version_appliquee(cle, uuid.UUID(org_id), await _utilisateur_id(registered_user["email"]), "v1")
    await _accorder_au_proprietaire(PERMISSION_APPLIQUER, uuid.UUID(org_id))
    demande = await _demander(client, registered_user, org_id, cle, "v2", "double décision")
    approbateur = await _inscrire_membre(client, uuid.UUID(org_id), [PERMISSION_APPROUVER])
    premiere = await client.post(
        f"{URL_APPROBATIONS}/{demande['id']}/decisions",
        json={"decision": "approuver", "motif": "ok"},
        headers=_entetes(approbateur, org_id),
    )
    assert premiere.status_code == 200, premiere.text
    avant = await _valeurs(cle, uuid.UUID(org_id))

    seconde = await client.post(
        f"{URL_APPROBATIONS}/{demande['id']}/decisions",
        json={"decision": "rejeter", "motif": "revirement"},
        headers=_entetes(approbateur, org_id),
    )

    assert seconde.status_code == 409, seconde.text
    assert seconde.json()["error"]["code"] == "VERSION_CONFLICT"
    assert await _valeurs(cle, uuid.UUID(org_id)) == avant, "une décision tardive n'écrit rien"
    assert await _nombre_evenements_approbation(demande["id"]) == 1


async def test_be159_rejet_ne_modifie_pas_la_valeur_active(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = organization["id"]
    cle = await _definition_sensible()
    await _version_appliquee(cle, uuid.UUID(org_id), await _utilisateur_id(registered_user["email"]), "v1")
    await _accorder_au_proprietaire(PERMISSION_APPLIQUER, uuid.UUID(org_id))
    demande = await _demander(client, registered_user, org_id, cle, "v2", "à rejeter")
    approbateur = await _inscrire_membre(client, uuid.UUID(org_id), [PERMISSION_APPROUVER])

    reponse = await client.post(
        f"{URL_APPROBATIONS}/{demande['id']}/decisions",
        json={"decision": "rejeter", "motif": "non conforme"},
        headers=_entetes(approbateur, org_id),
    )

    assert reponse.status_code == 200, reponse.text
    assert await _valeurs(cle, uuid.UUID(org_id)) == [(1, True, "v1")], "un rejet ne modifie pas la valeur active"
    lue = await client.get(f"{URL_APPROBATIONS}/{demande['id']}", headers=_entetes(approbateur, org_id))
    assert lue.json()["statut"] == "rejeté"


async def test_be159_ca5_approbateur_d_un_autre_tenant_renvoie_404(client: AsyncClient, registered_user: dict, organization: dict):
    org_id = organization["id"]
    cle = await _definition_sensible()
    await _version_appliquee(cle, uuid.UUID(org_id), await _utilisateur_id(registered_user["email"]), "v1")
    await _accorder_au_proprietaire(PERMISSION_APPLIQUER, uuid.UUID(org_id))
    demande = await _demander(client, registered_user, org_id, cle, "v2", "tenant A")

    # Approbateur disposant de la permission, mais dans un autre tenant (B).
    autre = {"email": f"be159-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com", "password": MOT_DE_PASSE}
    await client.post("/api/v1/auth/register", json={**autre, "fullName": "Tenant B"})
    login = await client.post("/api/v1/auth/login", json=autre)
    jeton_b = login.json()["accessToken"]
    org_b = (
        await client.post(
            "/api/v1/organizations",
            json={"name": "Tenant B", "slug": f"be159-b-{uuid.uuid4().hex[:8]}"},
            headers={"Authorization": f"Bearer {jeton_b}"},
        )
    ).json()["id"]
    await _accorder_au_proprietaire(PERMISSION_APPROUVER, uuid.UUID(org_b))

    reponse = await client.post(
        f"{URL_APPROBATIONS}/{demande['id']}/decisions",
        json={"decision": "approuver", "motif": "intrusion"},
        headers={"Authorization": f"Bearer {jeton_b}", "X-Organization-Id": org_b},
    )

    assert reponse.status_code == 404, reponse.text
    assert await _valeurs(cle, uuid.UUID(org_id)) == [(1, True, "v1")], "aucune écriture dans le tenant A"
