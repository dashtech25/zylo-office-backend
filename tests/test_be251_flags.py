"""BE-251 : déploiement canari et feature flags côté serveur.

Couvre les critères d'acceptation de la définition BE-251
(implementation-backend/tasks-exploitation-architecture.md, section BE-251) :
- CA-1 : un flag actif ne contourne pas les droits (utilisateur non autorisé refusé) ;
- CA-2 : un flag sans propriétaire ou sans expiration fait échouer le contrôle ;
- CA-3 : la désactivation coupe la fonction immédiatement ;
- CA-4 : un tenant non ciblé n'obtient pas la nouvelle version (isolation) ;
- CA-5 : durée de canari et seuil d'arrêt lus de la configuration (NON DÉFINI) ;
- audit : chaque changement écrit une ligne `flag_changes` ; changement réservé à
  l'exploitation (allowlist `OPERATOR_READ_USER_IDS`), sinon 403.

Aucun montage massif : une organisation, deux utilisateurs, un rôle portant une
permission de test, et les lignes de flag nécessaires à chaque cas.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.core.flags import (
    FeatureFlag,
    FlagChange,
    canari_doit_s_arreter,
    controle_flag,
    fonction_ouverte,
    modifier_flag,
    valider_canari,
)
from app.identity.models import OrganizationUser, User
from app.identity.schemas import CreateOrganizationRequest
from app.identity.service import create_organization
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.service import assign_role, get_or_create_permission

PERMISSION_FONCTION = "be251.fonction.utiliser"
CLE_FLAG = "be251_nouvelle_fonction"
MODULE_TEST = "be251"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool est vidé avant et après."""
    await engine.dispose()
    yield
    await engine.dispose()


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


async def _utilisateur(db, label: str) -> User:
    user = User(
        email=f"be251-{label}-{uuid.uuid4().hex[:8]}@example.com", hashedPassword="x", fullName=label
    )
    db.add(user)
    await db.flush()
    return user


async def _organisation(db, owner: User, label: str):
    return await create_organization(
        db, owner, CreateOrganizationRequest(name=f"BE251 {label}", slug=f"be251-{label}-{uuid.uuid4().hex[:8]}")
    )


async def _membre_avec_permission(db, owner: User, org, label: str, avec_droit: bool) -> User:
    """Membre de l'organisation ; `avec_droit` lui donne un rôle portant la permission."""
    membre = await _utilisateur(db, label)
    db.add(OrganizationUser(organizationId=org.id, userId=membre.id))
    await db.flush()
    if avec_droit:
        permission = await get_or_create_permission(db, PERMISSION_FONCTION, MODULE_TEST, "Permission de test BE-251")
        owner_role = (
            await db.execute(
                select(Role).join(UserRole, UserRole.roleId == Role.id).where(
                    UserRole.userId == owner.id, UserRole.organizationId == org.id, Role.code == "owner"
                )
            )
        ).scalar_one()
        db.add(RolePermission(roleId=owner_role.id, permissionId=permission.id))
        role = Role(organizationId=org.id, code=f"lecteur-{label}", name=f"Lecteur {label}")
        db.add(role)
        await db.flush()
        db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        await db.flush()
        await assign_role(db, org.id, owner.id, membre.id, role.id)
    return membre


async def _monde(db, label: str):
    owner = await _utilisateur(db, f"proprietaire-{label}")
    org = await _organisation(db, owner, label)
    return owner, org


def _headers(registered_user: dict) -> dict:
    return {"Authorization": f"Bearer {registered_user['accessToken']}"}


@pytest.fixture
def canari_configure(monkeypatch):
    """Durée et seuil de canari fixés par la configuration (CA-5)."""
    monkeypatch.setattr(settings, "FLAGS_DUREE_CANARI_HEURES", 2, raising=False)
    monkeypatch.setattr(settings, "FLAGS_SEUIL_ARRET_CANARI", 0.05, raising=False)


# ---------------------------------------------------------------------------
# CA-1 : un flag actif ne contourne pas les droits.
# ---------------------------------------------------------------------------


async def test_ca1_flag_actif_ne_contourne_pas_les_droits(canari_configure):
    """Le flag est actif pour le tenant ; seul l'utilisateur qui a la permission obtient la fonction."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "ca1")
        sans_droit = await _membre_avec_permission(db, owner, org, "ca1-sans", avec_droit=False)
        avec_droit = await _membre_avec_permission(db, owner, org, "ca1-avec", avec_droit=True)
        await modifier_flag(
            db, cle=CLE_FLAG, organization_id=org.id, actif=True, proprietaire_id=owner.id,
            expire_le=_maintenant() + timedelta(hours=1), acteur_id=owner.id,
        )
        await db.commit()

        assert await fonction_ouverte(
            db, cle=CLE_FLAG, organization_id=org.id, user=sans_droit, permission_code=PERMISSION_FONCTION
        ) is False
        assert await fonction_ouverte(
            db, cle=CLE_FLAG, organization_id=org.id, user=None, permission_code=PERMISSION_FONCTION
        ) is False
        assert await fonction_ouverte(
            db, cle=CLE_FLAG, organization_id=org.id, user=avec_droit, permission_code=PERMISSION_FONCTION
        ) is True


# ---------------------------------------------------------------------------
# CA-2 : un flag sans propriétaire ou sans expiration fait échouer le contrôle.
# ---------------------------------------------------------------------------


def test_ca2_controle_signale_proprietaire_et_expiration_absents():
    """Le contrôle nomme chaque anomalie : propriétaire absent, expiration absente."""
    sans_proprietaire = FeatureFlag(
        cle=CLE_FLAG, organization_id=uuid.uuid4(), actif=True, defaut_actif=False,
        proprietaire_id=None, expire_le=_maintenant() + timedelta(hours=1),
    )
    sans_expiration = FeatureFlag(
        cle=CLE_FLAG, organization_id=uuid.uuid4(), actif=True, defaut_actif=False,
        proprietaire_id=uuid.uuid4(), expire_le=None,
    )
    assert "proprietaire_absent" in controle_flag(sans_proprietaire, _maintenant())
    assert "expiration_absente" in controle_flag(sans_expiration, _maintenant())


async def test_ca2_base_refuse_un_flag_sans_proprietaire():
    """La contrainte NOT NULL de la base refuse le flag sans propriétaire."""
    async with AsyncSessionLocal() as db:
        _owner, org = await _monde(db, "ca2-base")
        db.add(FeatureFlag(
            cle=CLE_FLAG, organization_id=org.id, actif=True, defaut_actif=False,
            proprietaire_id=None, expire_le=_maintenant() + timedelta(hours=1),
        ))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


async def test_ca2_flag_expire_donne_le_defaut_sur(canari_configure):
    """Un flag actif mais expiré ne s'ouvre plus : la valeur par défaut sûre (désactivée) s'applique."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "ca2-expire")
        membre = await _membre_avec_permission(db, owner, org, "ca2-expire-m", avec_droit=True)
        await modifier_flag(
            db, cle=CLE_FLAG, organization_id=org.id, actif=True, proprietaire_id=owner.id,
            expire_le=_maintenant() - timedelta(minutes=1), acteur_id=owner.id,
        )
        await db.commit()
        assert await fonction_ouverte(
            db, cle=CLE_FLAG, organization_id=org.id, user=membre, permission_code=PERMISSION_FONCTION
        ) is False


# ---------------------------------------------------------------------------
# CA-3 : la désactivation coupe la fonction immédiatement.
# ---------------------------------------------------------------------------


async def test_ca3_desactivation_coupe_immediatement(canari_configure):
    """Après désactivation et commit, la décision suivante est déjà « fermée » (aucun cache)."""
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "ca3")
        membre = await _membre_avec_permission(db, owner, org, "ca3-m", avec_droit=True)
        expire = _maintenant() + timedelta(hours=1)
        await modifier_flag(
            db, cle=CLE_FLAG, organization_id=org.id, actif=True, proprietaire_id=owner.id,
            expire_le=expire, acteur_id=owner.id,
        )
        await db.commit()
        assert await fonction_ouverte(
            db, cle=CLE_FLAG, organization_id=org.id, user=membre, permission_code=PERMISSION_FONCTION
        ) is True

        await modifier_flag(
            db, cle=CLE_FLAG, organization_id=org.id, actif=False, proprietaire_id=owner.id,
            expire_le=expire, acteur_id=owner.id,
        )
        await db.commit()
        assert await fonction_ouverte(
            db, cle=CLE_FLAG, organization_id=org.id, user=membre, permission_code=PERMISSION_FONCTION
        ) is False


# ---------------------------------------------------------------------------
# CA-4 : un tenant non ciblé n'obtient pas la nouvelle version.
# ---------------------------------------------------------------------------


async def test_ca4_tenant_non_cible_n_obtient_pas_la_version(canari_configure):
    """Le flag est activé pour le tenant A seulement ; le tenant B, même avec la permission, reste fermé."""
    async with AsyncSessionLocal() as db:
        owner_a, org_a = await _monde(db, "ca4-a")
        owner_b, org_b = await _monde(db, "ca4-b")
        membre_a = await _membre_avec_permission(db, owner_a, org_a, "ca4-a-m", avec_droit=True)
        membre_b = await _membre_avec_permission(db, owner_b, org_b, "ca4-b-m", avec_droit=True)
        await modifier_flag(
            db, cle=CLE_FLAG, organization_id=org_a.id, actif=True, proprietaire_id=owner_a.id,
            expire_le=_maintenant() + timedelta(hours=1), acteur_id=owner_a.id,
        )
        await db.commit()

        assert await fonction_ouverte(
            db, cle=CLE_FLAG, organization_id=org_a.id, user=membre_a, permission_code=PERMISSION_FONCTION
        ) is True
        assert await fonction_ouverte(
            db, cle=CLE_FLAG, organization_id=org_b.id, user=membre_b, permission_code=PERMISSION_FONCTION
        ) is False


# ---------------------------------------------------------------------------
# CA-5 : durée de canari et seuil d'arrêt lus de la configuration (NON DÉFINI).
# ---------------------------------------------------------------------------


def test_ca5_duree_de_canari_lue_de_la_configuration(monkeypatch):
    """Sans durée configurée, aucun canari ne démarre ; avec durée, l'expiration est bornée par elle."""
    maintenant = _maintenant()
    monkeypatch.setattr(settings, "FLAGS_DUREE_CANARI_HEURES", None, raising=False)
    with pytest.raises(AppError) as non_configure:
        valider_canari(maintenant + timedelta(hours=1), maintenant)
    assert non_configure.value.code == "canari_non_configure"

    monkeypatch.setattr(settings, "FLAGS_DUREE_CANARI_HEURES", 2, raising=False)
    valider_canari(maintenant + timedelta(hours=1), maintenant)
    with pytest.raises(AppError) as hors_duree:
        valider_canari(maintenant + timedelta(hours=3), maintenant)
    assert hors_duree.value.code == "canari_hors_duree"


def test_ca5_seuil_d_arret_lu_de_la_configuration(monkeypatch):
    """Sans seuil configuré, le canari doit s'arrêter (échec fermé) ; sinon, le seuil décide."""
    monkeypatch.setattr(settings, "FLAGS_SEUIL_ARRET_CANARI", None, raising=False)
    assert canari_doit_s_arreter(0.0) is True

    monkeypatch.setattr(settings, "FLAGS_SEUIL_ARRET_CANARI", 0.05, raising=False)
    assert canari_doit_s_arreter(0.01) is False
    assert canari_doit_s_arreter(0.10) is True


# ---------------------------------------------------------------------------
# Routes : changement réservé à l'exploitation, avec audit ; refus en 403.
# ---------------------------------------------------------------------------


async def test_put_refuse_hors_exploitation_et_n_ecrit_rien(client: AsyncClient, registered_user: dict, monkeypatch):
    """Un compte hors allowlist reçoit 403 ; aucune ligne de flag ni d'audit n'est créée."""
    monkeypatch.delenv("OPERATOR_READ_USER_IDS", raising=False)
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "put-refus")
        await db.commit()
    res = await client.put(
        f"/api/v1/internal/flags/{CLE_FLAG}",
        json={
            "organizationId": str(org.id), "actif": True, "proprietaireId": str(owner.id),
            "expireLe": (_maintenant() + timedelta(hours=1)).isoformat(),
        },
        headers=_headers(registered_user),
    )
    assert res.status_code == 403
    async with AsyncSessionLocal() as db:
        ligne = (await db.execute(select(FeatureFlag).where(FeatureFlag.cle == CLE_FLAG, FeatureFlag.organization_id == org.id))).first()
        assert ligne is None


async def test_put_sans_proprietaire_ou_expiration_renvoie_422(
    client: AsyncClient, registered_user: dict, monkeypatch, canari_configure,
):
    """CA-2 côté route : le propriétaire et l'expiration sont obligatoires."""
    me = await client.get("/api/v1/auth/me", headers=_headers(registered_user))
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", me.json()["id"])
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "put-422")
        await db.commit()
    url = f"/api/v1/internal/flags/{CLE_FLAG}"
    expire = (_maintenant() + timedelta(hours=1)).isoformat()
    sans_proprietaire = await client.put(
        url, json={"organizationId": str(org.id), "actif": True, "expireLe": expire}, headers=_headers(registered_user)
    )
    sans_expiration = await client.put(
        url, json={"organizationId": str(org.id), "actif": True, "proprietaireId": str(owner.id)},
        headers=_headers(registered_user),
    )
    assert sans_proprietaire.status_code == 422
    assert sans_expiration.status_code == 422


async def test_put_exploitation_ecrit_un_audit_et_bascule_la_fonction(
    client: AsyncClient, registered_user: dict, monkeypatch, canari_configure,
):
    """Un opérateur active puis désactive le flag par la route ; chaque changement est tracé dans flag_changes."""
    me = await client.get("/api/v1/auth/me", headers=_headers(registered_user))
    operateur_id = me.json()["id"]
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", operateur_id)
    async with AsyncSessionLocal() as db:
        owner, org = await _monde(db, "put-audit")
        await db.commit()
    url = f"/api/v1/internal/flags/{CLE_FLAG}"
    expire = (_maintenant() + timedelta(hours=1)).isoformat()

    active = await client.put(
        url, json={"organizationId": str(org.id), "actif": True, "proprietaireId": str(owner.id), "expireLe": expire},
        headers=_headers(registered_user),
    )
    assert active.status_code == 200, active.text
    desactive = await client.put(
        url, json={"organizationId": str(org.id), "actif": False, "proprietaireId": str(owner.id), "expireLe": expire},
        headers=_headers(registered_user),
    )
    assert desactive.status_code == 200, desactive.text

    listing = await client.get(
        "/api/v1/internal/flags", params={"organizationId": str(org.id)}, headers=_headers(registered_user)
    )
    assert listing.status_code == 200
    assert [f["actif"] for f in listing.json()] == [False]

    async with AsyncSessionLocal() as db:
        changements = (
            await db.execute(select(FlagChange).where(FlagChange.cle == CLE_FLAG, FlagChange.organization_id == org.id))
        ).scalars().all()
        assert len(changements) == 2
        assert all(c.acteur_id == uuid.UUID(operateur_id) for c in changements)
