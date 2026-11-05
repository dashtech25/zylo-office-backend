"""BE-167 : catégories et audiences de notification.

Tests écrits d'après la définition `### BE-167` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : une catégorie a toujours une audience et un statut actif ; une catégorie
  sans audience est refusée (rien n'est persisté) ;
- CA-2 : une règle référence un type d'événement du catalogue ; une référence
  inconnue est refusée `422` SCHEMA_INVALID ;
- CA-3 (refus) : la modification d'une règle par un administrateur de tenant
  (sans autorité plateforme) renvoie `403` PERMISSION_DENIED ;
- CA-4 : aucun canal n'est présumé ; un canal absent se lit « NON DÉFINI ».

Le catalogue d'événements (BE-176) n'existe pas encore : le test de CA-2 injecte
le catalogue via `TYPES_EVENEMENT_CONNUS`, ce qui décrit le contrat sans le figer.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import User
from app.notifications import categories
from app.notifications.categories import (
    NON_DEFINI,
    canal_defaut_categorie,
    creer_categorie,
    creer_regle,
    modifier_regle_audience,
)
from app.notifications.models import CategorieNotification, RegleNotification
from app.rbac.role_assignments import PORTEE_PLATEFORME, AdminRoleAssignment


@pytest.fixture(autouse=True)
async def _pool_neuf():
    """Chaque test a sa propre boucle d'événements ; le moteur est un singleton dont
    les connexions poolées restent liées à la boucle précédente. Même remise à zéro
    que la fixture `client` de conftest.py."""
    from app.core.database import engine

    await engine.dispose()
    yield


def _code() -> str:
    return f"BE167-{uuid.uuid4().hex[:12]}"


async def _creer_utilisateur() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        utilisateur = User(email=f"be167-{uuid.uuid4().hex}@test.local", hashedPassword="x", fullName="BE167")
        db.add(utilisateur)
        await db.commit()
        return utilisateur.id


async def _donner_autorite_plateforme(user_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            AdminRoleAssignment(
                actorId=user_id,
                roleCode="operateur_plateforme",
                scope=PORTEE_PLATEFORME,
                grantedBy=user_id,
                grantedAt=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def _nombre_categories(code: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(func.count()).select_from(CategorieNotification).where(CategorieNotification.code == code))
        ).scalar_one()


async def test_be167_ca1_categorie_sans_audience_refusee(monkeypatch):
    code = _code()
    with pytest.raises(AppError) as erreur:
        async with AsyncSessionLocal() as db:
            await creer_categorie(db, code=code, libelle="Sans audience", audience_regle="")
    assert erreur.value.status_code == 422
    assert await _nombre_categories(code) == 0


async def test_be167_ca1_categorie_valide_active_par_defaut():
    code = _code()
    async with AsyncSessionLocal() as db:
        categorie = await creer_categorie(db, code=code, libelle="Sécurité", audience_regle="membres_organisation")
    assert categorie.audienceRegle == "membres_organisation"
    assert categorie.actif is True
    assert await _nombre_categories(code) == 1


async def test_be167_ca2_regle_sur_type_inconnu_refusee(monkeypatch):
    admin = await _creer_utilisateur()
    await _donner_autorite_plateforme(admin)
    code = _code()
    async with AsyncSessionLocal() as db:
        await creer_categorie(db, code=code, libelle="Alerte", audience_regle="membres_organisation")
    monkeypatch.setattr(categories, "TYPES_EVENEMENT_CONNUS", frozenset({"Test.BE167.connu"}))

    with pytest.raises(AppError) as erreur:
        async with AsyncSessionLocal() as db:
            await creer_regle(
                db,
                acteur_id=admin,
                evenement_type="Test.BE167.inconnu",
                categorie_code=code,
                audience="membres_organisation",
            )
    assert erreur.value.status_code == 422
    assert erreur.value.code == "SCHEMA_INVALID"


async def test_be167_ca2_regle_sur_type_du_catalogue_acceptee(monkeypatch):
    admin = await _creer_utilisateur()
    await _donner_autorite_plateforme(admin)
    code = _code()
    evenement = f"Test.BE167.{uuid.uuid4().hex}"
    async with AsyncSessionLocal() as db:
        await creer_categorie(db, code=code, libelle="Alerte", audience_regle="membres_organisation")
    monkeypatch.setattr(categories, "TYPES_EVENEMENT_CONNUS", frozenset({evenement}))

    async with AsyncSessionLocal() as db:
        regle = await creer_regle(db, acteur_id=admin, evenement_type=evenement, categorie_code=code, audience="membres_organisation")
    assert regle.evenementType == evenement
    assert regle.categorieCode == code


async def test_be167_ca3_modification_par_admin_tenant_refusee(monkeypatch):
    plateforme = await _creer_utilisateur()
    await _donner_autorite_plateforme(plateforme)
    tenant_admin = await _creer_utilisateur()
    code = _code()
    evenement = f"Test.BE167.{uuid.uuid4().hex}"
    monkeypatch.setattr(categories, "TYPES_EVENEMENT_CONNUS", frozenset({evenement}))
    async with AsyncSessionLocal() as db:
        await creer_categorie(db, code=code, libelle="Alerte", audience_regle="membres_organisation")
    async with AsyncSessionLocal() as db:
        regle = await creer_regle(db, acteur_id=plateforme, evenement_type=evenement, categorie_code=code, audience="membres_organisation")

    with pytest.raises(AppError) as erreur:
        async with AsyncSessionLocal() as db:
            await modifier_regle_audience(db, acteur_id=tenant_admin, regle_id=regle.id, audience="administrateurs")
    assert erreur.value.status_code == 403
    assert erreur.value.code == "PERMISSION_DENIED"

    async with AsyncSessionLocal() as db:
        relue = await db.get(RegleNotification, regle.id)
    assert relue.audience == "membres_organisation"


async def test_be167_ca4_canal_absent_renvoie_non_defini():
    code = _code()
    async with AsyncSessionLocal() as db:
        await creer_categorie(db, code=code, libelle="Sans canal", audience_regle="membres_organisation")
    async with AsyncSessionLocal() as db:
        categorie = await db.get(CategorieNotification, code)
        assert categorie.canalDefaut is None
        assert await canal_defaut_categorie(db, code) == NON_DEFINI == "NON DÉFINI"


async def test_be167_ca4_aucun_canal_presume_a_la_creation():
    code = _code()
    async with AsyncSessionLocal() as db:
        categorie = await creer_categorie(db, code=code, libelle="Aucun canal", audience_regle="membres_organisation")
    assert categorie.canalDefaut is None
