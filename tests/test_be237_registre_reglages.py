"""BE-237 : registre des réglages et historique des modifications.

Tests écrits d'après la définition `### BE-237` de
implementation-backend/tasks-exploitation-architecture.md, avant le code.

Couverture :
- CA-1 : un réglage sans propriétaire ou sans portée fermée est refusé au démarrage
  (déclaration Python et contrainte de la table `settings_registry`) ;
- CA-2 : chaque modification crée une entrée d'historique avec acteur et motif ;
- CA-3 : un réglage tenant ne modifie jamais un réglage plateforme (isolation) ;
- CA-4 : la lecture d'un secret renvoie une valeur masquée, et l'historique ne
  conserve jamais la valeur en clair ;
- CA-5 : écriture sans droit donne 403, sans aucune ligne d'historique.

Hypothèses (points NON DÉFINI, à confirmer en QE) :
- nom de la permission d'écriture : `settings.setting.update`, unique pour toutes
  les portées (la définition ne donne pas de noms) ;
- valeur de repli, lecture courante : dernière entrée d'historique de la portée,
  sinon `defaut` de la déclaration ;
- écriture de portée plateforme depuis un tenant : refusée en 404 (TENANT_MISMATCH).
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import User
from app.rbac.models import Role, RolePermission
from app.rbac.service import get_or_create_permission
from app.settings.models import SettingsHistory, SettingsRegistry
from app.settings.registry import ReglageDeclare, synchroniser_registre
from app.settings.service import MASQUE_SECRET, lire_reglage, modifier_reglage

PERMISSION_MODIFIER = "settings.setting.update"


def _cle() -> str:
    return f"be237.{uuid.uuid4().hex[:12]}"


async def _acteur(registered_user: dict, organization: dict) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        return user.id, uuid.UUID(organization["id"])


async def _accorder_modification(user_id: uuid.UUID, org_id: uuid.UUID) -> None:
    """Accorde la permission de réglage au rôle propriétaire (helper local de test)."""
    async with AsyncSessionLocal() as db:
        role = (await db.execute(select(Role).where(Role.organizationId == org_id, Role.code == "owner"))).scalar_one()
        permission = await get_or_create_permission(db, PERMISSION_MODIFIER, "settings", "Modifier un réglage (BE-237).")
        db.add(RolePermission(roleId=role.id, permissionId=permission.id))
        await db.commit()


async def _declarer(cle: str, portee: str = "tenant", secret: bool = False, defaut: object = "defaut") -> None:
    async with AsyncSessionLocal() as db:
        await synchroniser_registre(
            db,
            [ReglageDeclare(key=cle, owner="test", scope=portee, secret=secret, effect="immediat", defaut=defaut)],
        )


async def _historique(cle: str) -> list[SettingsHistory]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SettingsHistory).where(SettingsHistory.settingKey == cle))
        return list(result.scalars().all())


# CA-1 : refus au démarrage

def test_declaration_sans_proprietaire_refusee():
    with pytest.raises(ValueError):
        ReglageDeclare(key="be237.sans.proprietaire", owner="  ", scope="tenant", secret=False, effect="immediat")


def test_declaration_sans_portee_fermee_refusee():
    with pytest.raises(ValueError):
        ReglageDeclare(key="be237.portee.ouverte", owner="test", scope="global", secret=False, effect="immediat")


def test_declaration_sans_effet_refusee():
    with pytest.raises(ValueError):
        ReglageDeclare(key="be237.sans.effet", owner="test", scope="tenant", secret=False, effect="")


async def test_registre_refuse_un_reglage_sans_proprietaire_en_base(client):
    # `client` réinitialise le pool du moteur pour la boucle courante (voir conftest).
    """La contrainte de table refuse une ligne sans propriétaire, même hors du code Python."""
    async with AsyncSessionLocal() as db:
        db.add(
            SettingsRegistry(key=_cle(), owner="", scopeKind="tenant", secret=False, effect="immediat")
        )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def test_registre_refuse_une_portee_hors_ensemble_en_base(client):
    # `client` réinitialise le pool du moteur pour la boucle courante (voir conftest).
    async with AsyncSessionLocal() as db:
        db.add(SettingsRegistry(key=_cle(), owner="test", scopeKind="global", secret=False, effect="immediat"))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


# CA-2 : historique avec acteur et motif

async def test_chaque_modification_cree_une_entree_historique(registered_user, organization):
    acteur, org_id = await _acteur(registered_user, organization)
    await _accorder_modification(acteur, org_id)
    cle = _cle()
    await _declarer(cle, portee="tenant")

    async with AsyncSessionLocal() as db:
        await modifier_reglage(
            db, acteur_id=acteur, organisation_id=org_id, cle=cle, portee="tenant", scope_id=org_id,
            valeur="premiere", motif="initialisation",
        )
    async with AsyncSessionLocal() as db:
        await modifier_reglage(
            db, acteur_id=acteur, organisation_id=org_id, cle=cle, portee="tenant", scope_id=org_id,
            valeur="seconde", motif="ajustement",
        )

    entrees = sorted(await _historique(cle), key=lambda e: e.createdAt)
    assert len(entrees) == 2
    assert all(e.actorId == acteur for e in entrees)
    assert [e.reason for e in entrees] == ["initialisation", "ajustement"]
    assert entrees[0].oldValue == "defaut" and entrees[0].newValue == "premiere"
    assert entrees[1].oldValue == "premiere" and entrees[1].newValue == "seconde"


async def test_motif_vide_refuse_sans_ecriture(registered_user, organization):
    acteur, org_id = await _acteur(registered_user, organization)
    await _accorder_modification(acteur, org_id)
    cle = _cle()
    await _declarer(cle, portee="tenant")

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as exc:
            await modifier_reglage(
                db, acteur_id=acteur, organisation_id=org_id, cle=cle, portee="tenant", scope_id=org_id,
                valeur="x", motif="   ",
            )
    assert exc.value.status_code == 422
    assert await _historique(cle) == []


async def test_reglage_inconnu_refuse(registered_user, organization):
    acteur, org_id = await _acteur(registered_user, organization)
    await _accorder_modification(acteur, org_id)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as exc:
            await modifier_reglage(
                db, acteur_id=acteur, organisation_id=org_id, cle=_cle(), portee="tenant", scope_id=org_id,
                valeur="x", motif="inconnu",
            )
    assert exc.value.status_code == 422


# CA-3 : isolation tenant et plateforme

async def test_tenant_ne_modifie_jamais_un_reglage_plateforme(registered_user, organization):
    acteur, org_id = await _acteur(registered_user, organization)
    await _accorder_modification(acteur, org_id)
    cle = _cle()
    await _declarer(cle, portee="platform", defaut="plateforme")

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as exc:
            await modifier_reglage(
                db, acteur_id=acteur, organisation_id=org_id, cle=cle, portee="platform", scope_id=None,
                valeur="tenant", motif="tentative",
            )
    assert exc.value.status_code == 404
    assert await _historique(cle) == []
    async with AsyncSessionLocal() as db:
        assert await lire_reglage(db, cle=cle, portee="platform", scope_id=None) == "plateforme"


async def test_tenant_ne_lit_ni_n_ecrit_le_reglage_d_un_autre_tenant(registered_user, organization):
    acteur, org_id = await _acteur(registered_user, organization)
    await _accorder_modification(acteur, org_id)
    cle = _cle()
    await _declarer(cle, portee="tenant")
    autre_org = uuid.uuid4()

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as exc:
            await modifier_reglage(
                db, acteur_id=acteur, organisation_id=org_id, cle=cle, portee="tenant", scope_id=autre_org,
                valeur="intrus", motif="tentative",
            )
    assert exc.value.status_code == 404
    assert await _historique(cle) == []

    async with AsyncSessionLocal() as db:
        await modifier_reglage(
            db, acteur_id=acteur, organisation_id=org_id, cle=cle, portee="tenant", scope_id=org_id,
            valeur="local", motif="ok",
        )
    async with AsyncSessionLocal() as db:
        assert await lire_reglage(db, cle=cle, portee="tenant", scope_id=autre_org) == "defaut"


# CA-4 : secrets masqués

async def test_lecture_secret_renvoie_valeur_masquee(registered_user, organization):
    acteur, org_id = await _acteur(registered_user, organization)
    await _accorder_modification(acteur, org_id)
    cle = _cle()
    await _declarer(cle, portee="tenant", secret=True, defaut=None)
    secret = "valeur-secrete-" + uuid.uuid4().hex

    async with AsyncSessionLocal() as db:
        await modifier_reglage(
            db, acteur_id=acteur, organisation_id=org_id, cle=cle, portee="tenant", scope_id=org_id,
            valeur=secret, motif="rotation",
        )
    async with AsyncSessionLocal() as db:
        lue = await lire_reglage(db, cle=cle, portee="tenant", scope_id=org_id)
    assert lue == MASQUE_SECRET
    assert secret not in str(lue)

    entrees = await _historique(cle)
    assert len(entrees) == 1
    assert secret not in str(entrees[0].newValue)
    assert secret not in str(entrees[0].oldValue)
    async with AsyncSessionLocal() as db:
        brut = (await db.execute(text("SELECT CAST(\"newValue\" AS TEXT) FROM settings_history WHERE \"settingKey\" = :k"), {"k": cle})).scalars().all()
    assert all(secret not in ligne for ligne in brut)


# CA-5 : refus sans droit

async def test_ecriture_sans_droit_donne_403_sans_historique(registered_user, organization):
    acteur, org_id = await _acteur(registered_user, organization)
    cle = _cle()
    await _declarer(cle, portee="tenant")

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as exc:
            await modifier_reglage(
                db, acteur_id=acteur, organisation_id=org_id, cle=cle, portee="tenant", scope_id=org_id,
                valeur="refuse", motif="sans droit",
            )
    assert exc.value.status_code == 403
    assert await _historique(cle) == []


async def test_ecriture_avec_droit_reussit(registered_user, organization):
    """Contrôle positif : la même écriture réussit une fois la permission accordée."""
    acteur, org_id = await _acteur(registered_user, organization)
    await _accorder_modification(acteur, org_id)
    cle = _cle()
    await _declarer(cle, portee="tenant")

    async with AsyncSessionLocal() as db:
        await modifier_reglage(
            db, acteur_id=acteur, organisation_id=org_id, cle=cle, portee="tenant", scope_id=org_id,
            valeur="accepte", motif="avec droit",
        )
    assert len(await _historique(cle)) == 1
