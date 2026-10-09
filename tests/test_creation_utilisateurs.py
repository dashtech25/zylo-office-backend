"""Création d'utilisateurs par une organisation, activation à usage unique (T-021, T-049, T-048).

Intention : un utilisateur autorisé (permission `identity.user.manage`) crée un
compte dans son organisation SANS connaître le secret du titulaire. Le compte
est `pending`, sans mot de passe utilisable ; le titulaire active son compte
par un jeton à usage unique, à durée limitée, stocké haché, transmis hors API.

Règles testées :
- aucun secret (mot de passe, jeton) dans une réponse de l'API ni en base en clair ;
- le créateur ne peut ouvrir aucune session sur le compte créé (REV-S-06) ;
- isolation : une organisation étrangère répond 404 uniforme (T-010) ;
- sans permission, 403 ; aucune écriture en cas de refus ;
- jeton : usage unique, expiration, révocation à la réémission ;
- désactivation réversible avec révocation des sessions, garde-fou dernier propriétaire ;
- création désactivée tant que l'envoi d'e-mail n'est pas configuré ;
- journal d'audit de chaque action ; contraintes en base (unicité, FK, un jeton ouvert par compte).
"""

import hashlib
import importlib.util
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.audit.models import AuditLog
from app.auth.models import RefreshToken
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User, UserInvitation
from app.rbac.models import Role, UserRole
from app.shared.email import memory_outbox
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
MOT_DE_PASSE_NOUVEAU = "NouveauMotDePasse-42"
URL_CREATION = "/api/v1/organizations/{org}/users"
URL_REEMISSION = "/api/v1/organizations/{org}/users/{user}/invitation"
URL_STATUT = "/api/v1/organizations/{org}/users/{user}"
URL_ACTIVATION = "/api/v1/auth/activate"
REGEX_JETON = re.compile(r"#token=([A-Za-z0-9_\-]+)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entetes(utilisateur: dict, organisation_id: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['token']}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _inscrire(client: AsyncClient, mot_de_passe: str = MOT_DE_PASSE) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": mot_de_passe, "fullName": "Acteur test"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": mot_de_passe})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "email": email, "token": token, "motDePasse": mot_de_passe}


async def _proprietaire(client: AsyncClient) -> dict:
    """Utilisateur ayant créé une organisation : il en est donc propriétaire."""
    acteur = await _inscrire(client)
    res = await client.post(
        "/api/v1/organizations",
        json={"name": f"Org {uuid.uuid4().hex[:6]}", "slug": f"org-{uuid.uuid4().hex[:10]}"},
        headers=_entetes(acteur),
    )
    assert res.status_code == 201, res.text
    acteur["organisation"] = res.json()["id"]
    return acteur


async def _ajouter_membre_sans_role(organisation_id: str, utilisateur_id: str) -> None:
    """Pas d'API d'ajout de membre dans le socle : insertion directe, comme les fixtures existantes."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(utilisateur_id)))
        await db.commit()


async def _creer_compte(client: AsyncClient, createur: dict, email: str | None = None) -> dict:
    res = await client.post(
        URL_CREATION.format(org=createur["organisation"]),
        json={"email": email or unique_email(), "fullName": "Titulaire Test"},
        headers=_entetes(createur, createur["organisation"]),
    )
    assert res.status_code == 201, res.text
    return res.json()


def _jeton_de_la_derniere_invitation(email: str) -> str:
    message = [m for m in memory_outbox() if m.to == email][-1]
    correspondance = REGEX_JETON.search(message.body)
    assert correspondance is not None, "le message doit contenir le lien d'activation"
    return correspondance.group(1)


async def _ligne_utilisateur(utilisateur_id: str) -> User:
    async with AsyncSessionLocal() as db:
        return await db.get(User, uuid.UUID(utilisateur_id))


async def _invitations(utilisateur_id: str) -> list[UserInvitation]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(UserInvitation).where(UserInvitation.userId == uuid.UUID(utilisateur_id)))
        return list(result.scalars().all())


async def _activer(client: AsyncClient, jeton: str, mot_de_passe: str = MOT_DE_PASSE_NOUVEAU):
    return await client.post(URL_ACTIVATION, json={"token": jeton, "password": mot_de_passe})


@pytest.fixture(autouse=True)
def _boite_de_test(monkeypatch):
    """Envoi en boîte mémoire pour ce module seulement. Réglé sur l'objet `settings`
    (et non dans l'environnement), pour ne pas fausser les tests de configuration."""
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    memory_outbox().clear()
    yield
    memory_outbox().clear()


# ---------------------------------------------------------------------------
# Création
# ---------------------------------------------------------------------------


async def test_proprietaire_cree_un_compte_pending_sans_secret_dans_la_reponse(client: AsyncClient):
    createur = await _proprietaire(client)
    email = unique_email()

    res = await client.post(
        URL_CREATION.format(org=createur["organisation"]),
        json={"email": email, "fullName": "  Nouvelle Personne  "},
        headers=_entetes(createur, createur["organisation"]),
    )

    assert res.status_code == 201, res.text
    corps = res.json()
    assert corps["status"] == "pending"
    assert corps["email"] == email
    assert corps["fullName"] == "Nouvelle Personne"
    assert corps["organizationId"] == createur["organisation"]
    assert "invitationExpiresAt" in corps
    # Aucun secret : ni mot de passe, ni hash, ni jeton d'activation.
    texte = res.text.lower()
    for interdit in ("password", "hashedpassword", "token", "motdepasse"):
        assert interdit not in texte


async def test_creation_envoie_un_lien_a_usage_unique_hors_de_la_reponse(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)

    messages = [m for m in memory_outbox() if m.to == compte["email"]]
    assert len(messages) == 1
    jeton = _jeton_de_la_derniere_invitation(compte["email"])
    assert jeton not in str(compte)

    # Seul le haché est stocké : le jeton en clair n'apparaît dans aucune colonne.
    invitations = await _invitations(compte["id"])
    assert len(invitations) == 1
    assert invitations[0].tokenHash == hashlib.sha256(jeton.encode()).hexdigest()
    assert invitations[0].tokenHash != jeton
    assert invitations[0].usedAt is None and invitations[0].revokedAt is None


async def test_le_compte_cree_est_un_membre_de_l_organisation(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)

    async with AsyncSessionLocal() as db:
        appartenance = await db.scalar(
            select(OrganizationUser.id).where(
                OrganizationUser.organizationId == uuid.UUID(createur["organisation"]),
                OrganizationUser.userId == uuid.UUID(compte["id"]),
            )
        )
    assert appartenance is not None


async def test_le_createur_ne_peut_pas_ouvrir_de_session_sur_le_compte_cree(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)

    # Le créateur connaît son propre mot de passe : il ne doit pas ouvrir la session du titulaire.
    for essai in (createur["motDePasse"], MOT_DE_PASSE, "motdepasse-devine-1", ""):
        login = await client.post("/api/v1/auth/login", json={"email": compte["email"], "password": essai})
        assert login.status_code == 401, login.text

    async with AsyncSessionLocal() as db:
        jetons = await db.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.userId == uuid.UUID(compte["id"])))
    assert jetons == 0


async def test_un_compte_pending_ne_peut_pas_appeler_l_api(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)
    # Même avec un jeton d'accès forgé pour lui, get_current_user refuse un compte non actif.
    from app.core.security import create_access_token

    jeton_forge = create_access_token(uuid.UUID(compte["id"]))
    res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton_forge}"})
    assert res.status_code == 401


async def test_membre_sans_permission_recoit_403_et_rien_n_est_ecrit(client: AsyncClient):
    createur = await _proprietaire(client)
    membre = await _inscrire(client)
    await _ajouter_membre_sans_role(createur["organisation"], membre["id"])
    email = unique_email()

    res = await client.post(
        URL_CREATION.format(org=createur["organisation"]),
        json={"email": email, "fullName": "Intrus"},
        headers=_entetes(membre, createur["organisation"]),
    )

    assert res.status_code == 403
    assert res.json()["error"]["code"] == "permission_denied"
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(User.id).where(User.email == email)) is None


async def test_non_membre_recoit_404_uniforme(client: AsyncClient):
    createur = await _proprietaire(client)
    etranger = await _inscrire(client)
    email = unique_email()

    res = await client.post(
        URL_CREATION.format(org=createur["organisation"]),
        json={"email": email, "fullName": "Intrus"},
        headers=_entetes(etranger, createur["organisation"]),
    )

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "organization_not_found"


async def test_proprietaire_d_une_autre_organisation_ne_cree_rien_chez_autrui(client: AsyncClient):
    proprietaire_a = await _proprietaire(client)
    proprietaire_b = await _proprietaire(client)
    email = unique_email()

    # Chemin = B, en-tête = B, acteur = propriétaire de A : refus 404, aucune écriture.
    res = await client.post(
        URL_CREATION.format(org=proprietaire_b["organisation"]),
        json={"email": email, "fullName": "Intrus"},
        headers=_entetes(proprietaire_a, proprietaire_b["organisation"]),
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "organization_not_found"

    # Chemin = B, en-tête = A : incohérence refusée en 404 uniforme.
    res = await client.post(
        URL_CREATION.format(org=proprietaire_b["organisation"]),
        json={"email": email, "fullName": "Intrus"},
        headers=_entetes(proprietaire_a, proprietaire_a["organisation"]),
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "organization_not_found"

    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(User.id).where(User.email == email)) is None
    assert [m for m in memory_outbox() if m.to == email] == []


async def test_email_deja_utilise_refuse_sans_nouvelle_ecriture(client: AsyncClient):
    createur = await _proprietaire(client)
    existant = await _inscrire(client)

    res = await client.post(
        URL_CREATION.format(org=createur["organisation"]),
        json={"email": existant["email"], "fullName": "Doublon"},
        headers=_entetes(createur, createur["organisation"]),
    )

    assert res.status_code == 409
    assert res.json()["error"]["code"] == "email_already_used"
    assert [m for m in memory_outbox() if m.to == existant["email"]] == []


@pytest.mark.parametrize(
    "charge",
    [
        {"email": "pas-un-email", "fullName": "Nom"},
        {"email": "", "fullName": "Nom"},
        {"fullName": "Nom"},
        {"email": "ok@example.com", "fullName": "   "},
        {"email": "ok@example.com", "fullName": "x" * 256},
    ],
)
async def test_validations_de_la_creation(client: AsyncClient, charge: dict):
    createur = await _proprietaire(client)
    res = await client.post(
        URL_CREATION.format(org=createur["organisation"]),
        json=charge,
        headers=_entetes(createur, createur["organisation"]),
    )
    assert res.status_code == 422, res.text


async def test_creation_desactivee_tant_que_l_envoi_n_est_pas_configure(client: AsyncClient, monkeypatch):
    createur = await _proprietaire(client)
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "none")
    email = unique_email()

    res = await client.post(
        URL_CREATION.format(org=createur["organisation"]),
        json={"email": email, "fullName": "Personne"},
        headers=_entetes(createur, createur["organisation"]),
    )

    assert res.status_code == 503
    assert res.json()["error"]["code"] == "user_creation_disabled"
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(User.id).where(User.email == email)) is None


async def test_audit_de_la_creation(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)

    async with AsyncSessionLocal() as db:
        entrees = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.organizationId == uuid.UUID(createur["organisation"]),
                    AuditLog.action == "identity.user.create",
                    AuditLog.entityId == uuid.UUID(compte["id"]),
                )
            )
        ).scalars().all()
    assert len(entrees) == 1
    assert entrees[0].actorUserId == uuid.UUID(createur["id"])
    # Le journal ne contient jamais le jeton ni un secret.
    assert "#token" not in (entrees[0].summary or "")
    assert not any("token" in str(v).lower() for v in (entrees[0].changes or {}).values())


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------


async def test_activation_a_usage_unique_puis_connexion_possible(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)
    jeton = _jeton_de_la_derniere_invitation(compte["email"])

    res = await _activer(client, jeton)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "active"
    assert jeton not in res.text

    login = await client.post("/api/v1/auth/login", json={"email": compte["email"], "password": MOT_DE_PASSE_NOUVEAU})
    assert login.status_code == 200, login.text
    user = await _ligne_utilisateur(compte["id"])
    assert user.status == "active"


async def test_jeton_refuse_au_second_usage(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)
    jeton = _jeton_de_la_derniere_invitation(compte["email"])

    assert (await _activer(client, jeton)).status_code == 200
    second = await _activer(client, jeton, "Autre-Mot-De-Passe-99")

    assert second.status_code == 400
    assert second.json()["error"]["code"] == "invitation_invalid"
    login = await client.post("/api/v1/auth/login", json={"email": compte["email"], "password": "Autre-Mot-De-Passe-99"})
    assert login.status_code == 401


async def test_jeton_expire_refuse(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)
    jeton = _jeton_de_la_derniere_invitation(compte["email"])
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(UserInvitation)
            .where(UserInvitation.userId == uuid.UUID(compte["id"]))
            .values(expiresAt=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        await db.commit()

    res = await _activer(client, jeton)

    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invitation_invalid"
    assert (await _ligne_utilisateur(compte["id"])).status == "pending"


async def test_jeton_inconnu_ou_malforme_refuse_uniformement(client: AsyncClient):
    for jeton in ("jeton-inconnu-" + "a" * 40, "x", "a" * 500):
        res = await _activer(client, jeton)
        assert res.status_code in (400, 422)
        if res.status_code == 400:
            assert res.json()["error"]["code"] == "invitation_invalid"


async def test_jeton_d_un_compte_ne_peut_pas_activer_un_autre_compte(client: AsyncClient):
    createur = await _proprietaire(client)
    compte_a = await _creer_compte(client, createur)
    compte_b = await _creer_compte(client, createur)
    jeton_a = _jeton_de_la_derniere_invitation(compte_a["email"])

    assert (await _activer(client, jeton_a)).status_code == 200

    assert (await _ligne_utilisateur(compte_a["id"])).status == "active"
    assert (await _ligne_utilisateur(compte_b["id"])).status == "pending"


async def test_createur_ne_peut_pas_utiliser_le_jeton_qu_il_n_a_jamais_vu(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)

    # La réémission ne renvoie aucun jeton ; l'API ne donne jamais le jeton au créateur.
    reemission = await client.post(
        URL_REEMISSION.format(org=createur["organisation"], user=compte["id"]),
        headers=_entetes(createur, createur["organisation"]),
    )
    assert reemission.status_code == 201, reemission.text
    assert "token" not in reemission.text.lower()

    # Le créateur n'a que le jeton reçu par le canal d'envoi (ici la boîte de test) :
    # un jeton inventé par le créateur n'active rien.
    res = await _activer(client, "devine-" + uuid.uuid4().hex)
    assert res.status_code == 400
    assert (await _ligne_utilisateur(compte["id"])).status == "pending"


async def test_reemission_revoque_le_jeton_precedent(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)
    ancien = _jeton_de_la_derniere_invitation(compte["email"])

    reemission = await client.post(
        URL_REEMISSION.format(org=createur["organisation"], user=compte["id"]),
        headers=_entetes(createur, createur["organisation"]),
    )
    assert reemission.status_code == 201, reemission.text
    nouveau = _jeton_de_la_derniere_invitation(compte["email"])
    assert nouveau != ancien

    assert (await _activer(client, ancien)).status_code == 400
    assert (await _activer(client, nouveau)).status_code == 200


async def test_reemission_refusee_pour_un_compte_deja_active(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)
    assert (await _activer(client, _jeton_de_la_derniere_invitation(compte["email"]))).status_code == 200

    res = await client.post(
        URL_REEMISSION.format(org=createur["organisation"], user=compte["id"]),
        headers=_entetes(createur, createur["organisation"]),
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "user_not_pending"


# ---------------------------------------------------------------------------
# Désactivation et réactivation (cycle de vie minimal, T-048)
# ---------------------------------------------------------------------------


async def _membre_actif(client: AsyncClient, createur: dict) -> dict:
    compte = await _creer_compte(client, createur)
    assert (await _activer(client, _jeton_de_la_derniere_invitation(compte["email"]))).status_code == 200
    login = await client.post("/api/v1/auth/login", json={"email": compte["email"], "password": MOT_DE_PASSE_NOUVEAU})
    compte["token"] = login.json()["accessToken"]
    compte["refresh"] = login.json()["refreshToken"]
    return compte


async def test_suspension_revoque_les_sessions_et_reactivation_restaure_l_acces(client: AsyncClient):
    createur = await _proprietaire(client)
    membre = await _membre_actif(client, createur)
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {membre['token']}"})).status_code == 200

    res = await client.patch(
        URL_STATUT.format(org=createur["organisation"], user=membre["id"]),
        json={"status": "suspended"},
        headers=_entetes(createur, createur["organisation"]),
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "suspended"

    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {membre['token']}"})).status_code == 401
    assert (await client.post("/api/v1/auth/refresh", json={"refreshToken": membre["refresh"]})).status_code == 401
    login = await client.post("/api/v1/auth/login", json={"email": membre["email"], "password": MOT_DE_PASSE_NOUVEAU})
    assert login.status_code == 403

    res = await client.patch(
        URL_STATUT.format(org=createur["organisation"], user=membre["id"]),
        json={"status": "active"},
        headers=_entetes(createur, createur["organisation"]),
    )
    assert res.status_code == 200, res.text
    assert (await client.post("/api/v1/auth/login", json={"email": membre["email"], "password": MOT_DE_PASSE_NOUVEAU})).status_code == 200


async def test_statut_pending_ne_se_change_pas_par_patch(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)

    res = await client.patch(
        URL_STATUT.format(org=createur["organisation"], user=compte["id"]),
        json={"status": "active"},
        headers=_entetes(createur, createur["organisation"]),
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "user_not_activated"
    assert (await _ligne_utilisateur(compte["id"])).status == "pending"


async def test_on_ne_se_suspend_pas_soi_meme(client: AsyncClient):
    createur = await _proprietaire(client)
    res = await client.patch(
        URL_STATUT.format(org=createur["organisation"], user=createur["id"]),
        json={"status": "suspended"},
        headers=_entetes(createur, createur["organisation"]),
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "self_status_change_forbidden"


async def test_dernier_proprietaire_actif_ne_peut_pas_etre_suspendu(client: AsyncClient):
    createur = await _proprietaire(client)
    # Un gestionnaire sans rôle propriétaire, disposant de identity.user.manage par un rôle dédié.
    gestionnaire = await _membre_actif(client, createur)
    await _accorder_gestion_utilisateurs(createur["organisation"], gestionnaire["id"])

    res = await client.patch(
        URL_STATUT.format(org=createur["organisation"], user=createur["id"]),
        json={"status": "suspended"},
        headers=_entetes(gestionnaire, createur["organisation"]),
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "last_owner"


async def _accorder_gestion_utilisateurs(organisation_id: str, utilisateur_id: str) -> None:
    from app.identity.permissions import USER_MANAGE
    from app.rbac.models import Permission, RolePermission

    async with AsyncSessionLocal() as db:
        permission = await db.scalar(select(Permission).where(Permission.code == USER_MANAGE))
        if permission is None:
            permission = Permission(code=USER_MANAGE, moduleCode="identity", description="test")
            db.add(permission)
            await db.flush()
        role = Role(organizationId=uuid.UUID(organisation_id), code=f"gestion-{uuid.uuid4().hex[:6]}", name="Gestion test")
        db.add(role)
        await db.flush()
        db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        db.add(UserRole(userId=uuid.UUID(utilisateur_id), organizationId=uuid.UUID(organisation_id), roleId=role.id))
        await db.commit()


async def test_patch_statut_cross_tenant_et_sans_permission(client: AsyncClient):
    proprietaire_a = await _proprietaire(client)
    proprietaire_b = await _proprietaire(client)
    compte_b = await _creer_compte(client, proprietaire_b)

    res = await client.patch(
        URL_STATUT.format(org=proprietaire_a["organisation"], user=compte_b["id"]),
        json={"status": "suspended"},
        headers=_entetes(proprietaire_a, proprietaire_a["organisation"]),
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "user_not_found"

    membre = await _membre_actif(client, proprietaire_a)
    res = await client.patch(
        URL_STATUT.format(org=proprietaire_a["organisation"], user=membre["id"]),
        json={"status": "suspended"},
        headers=_entetes(membre, proprietaire_a["organisation"]),
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Audit et contraintes en base
# ---------------------------------------------------------------------------


async def test_audit_de_l_activation_et_de_la_suspension(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)
    assert (await _activer(client, _jeton_de_la_derniere_invitation(compte["email"]))).status_code == 200
    await client.patch(
        URL_STATUT.format(org=createur["organisation"], user=compte["id"]),
        json={"status": "suspended"},
        headers=_entetes(createur, createur["organisation"]),
    )

    async with AsyncSessionLocal() as db:
        actions = set(
            (
                await db.execute(
                    select(AuditLog.action).where(
                        AuditLog.organizationId == uuid.UUID(createur["organisation"]),
                        AuditLog.entityId == uuid.UUID(compte["id"]),
                    )
                )
            ).scalars().all()
        )
    assert {"identity.user.create", "identity.user.activate", "identity.user.suspend"} <= actions


async def test_contrainte_unicite_email_en_base(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)
    async with AsyncSessionLocal() as db:
        db.add(User(email=compte["email"], hashedPassword="x", fullName="Doublon", status="pending"))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_contrainte_fk_et_un_seul_jeton_ouvert_par_compte(client: AsyncClient):
    createur = await _proprietaire(client)
    compte = await _creer_compte(client, createur)

    async with AsyncSessionLocal() as db:
        db.add(
            UserInvitation(
                organizationId=uuid.UUID(createur["organisation"]),
                userId=uuid.uuid4(),
                createdByUserId=uuid.UUID(createur["id"]),
                tokenHash="f" * 64,
                expiresAt=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()

    async with AsyncSessionLocal() as db:
        db.add(
            UserInvitation(
                organizationId=uuid.UUID(createur["organisation"]),
                userId=uuid.UUID(compte["id"]),
                createdByUserId=uuid.UUID(createur["id"]),
                tokenHash="e" * 64,
                expiresAt=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


# ---------------------------------------------------------------------------
# Migration explicite des propriétaires (idempotente)
# ---------------------------------------------------------------------------


def _charger_migration():
    chemin = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    fichiers = sorted(chemin.glob("e7f8a9b0c1d2_*.py"))
    assert len(fichiers) == 1, "la migration T-021 doit exister"
    spec = importlib.util.spec_from_file_location("migration_t021", fichiers[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_migration_accorde_identity_user_manage_aux_proprietaires_rejouable(client: AsyncClient):
    from app.identity.permissions import USER_MANAGE
    from app.rbac.models import Permission, RolePermission

    createur = await _proprietaire(client)
    migration = _charger_migration()

    async with AsyncSessionLocal() as db:
        # Simule un propriétaire antérieur à la permission : on retire le droit puis on rejoue la migration.
        permission = await db.scalar(select(Permission).where(Permission.code == USER_MANAGE))
        owner = await db.scalar(
            select(Role).where(Role.organizationId == uuid.UUID(createur["organisation"]), Role.code == "owner")
        )
        await db.execute(
            RolePermission.__table__.delete().where(
                RolePermission.roleId == owner.id, RolePermission.permissionId == permission.id
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        await db.run_sync(lambda sync_session: migration.accorde_permission_aux_proprietaires(sync_session.connection()))
        await db.commit()
        premiere = await db.scalar(
            select(func.count()).select_from(RolePermission).where(RolePermission.roleId == owner.id, RolePermission.permissionId == permission.id)
        )
    async with AsyncSessionLocal() as db:
        await db.run_sync(lambda sync_session: migration.accorde_permission_aux_proprietaires(sync_session.connection()))
        await db.commit()
        seconde = await db.scalar(
            select(func.count()).select_from(RolePermission).where(RolePermission.roleId == owner.id, RolePermission.permissionId == permission.id)
        )
    assert premiere == 1
    assert seconde == 1


# ---------------------------------------------------------------------------
# Configuration de l'envoi
# ---------------------------------------------------------------------------


def test_console_refuse_hors_developpement():
    from app.core.config import ConfigurationSecretError, Settings

    with pytest.raises(ConfigurationSecretError):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            EMAIL_BACKEND="console",
            JWT_SECRET=os.environ["JWT_SECRET"],
            STORAGE_SIGNED_URL_SECRET=os.environ["STORAGE_SIGNED_URL_SECRET"],
            APP_FIELD_ENCRYPTION_KEY="k" * 40,
        )


def test_backend_inconnu_refuse():
    from app.core.config import ConfigurationSecretError, Settings

    with pytest.raises(ConfigurationSecretError):
        Settings(_env_file=None, ENVIRONMENT="development", EMAIL_BACKEND="smtp-inconnu")


async def test_organisation_creee_donne_au_proprietaire_la_permission(client: AsyncClient):
    from app.identity.permissions import USER_MANAGE
    from app.rbac.service import user_has_permission

    createur = await _proprietaire(client)
    async with AsyncSessionLocal() as db:
        autorise = await user_has_permission(
            db, uuid.UUID(createur["id"]), uuid.UUID(createur["organisation"]), USER_MANAGE
        )
    assert autorise is True
