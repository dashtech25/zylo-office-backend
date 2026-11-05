"""BE-100 : modèle Organisation, Tenant, Membership, Invitation.

Tests écrits d'après la définition `### BE-100` de
implementation-backend/tasks-portail-organisation.md, avant le code.

Périmètre : CA-1 (migration : tables `tenant` et `invitation`, contraintes sur
l'appartenance, aller-retour possible), CA-2 (deux appartenances identiques
refusées par la base), CA-3 (statut d'invitation limité aux quatre valeurs),
CA-4 (un seul tenant par organisation). Les tests de défauts et d'absence de
colonne `parentId` (QE-POR-05) complètent la liste.
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.identity.models import Invitation, Organization, OrganizationUser, Tenant, User

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Vide le pool du moteur partagé avant chaque test.

    `engine` est un singleton : ses connexions poolées restent liées à la boucle
    qui les a ouvertes. Les tests de ce fichier n'utilisent pas le fixture `client`
    (qui fait ce dispose() dans conftest.py), d'où ce nettoyage local.
    """
    from app.core.database import engine

    await engine.dispose()


def _config() -> Config:
    return Config(os.path.join(BACKEND_ROOT, "alembic.ini"))


async def _tables() -> set[str]:
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        return {ligne[0] for ligne in res.all()}


async def _colonnes(table: str) -> set[str]:
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t"),
            {"t": table},
        )
        return {ligne[0] for ligne in res.all()}


async def _ajouter(objet) -> None:
    async with AsyncSessionLocal() as db:
        db.add(objet)
        await db.commit()


async def _organisation_et_utilisateur() -> tuple[uuid.UUID, uuid.UUID]:
    """Crée une organisation et un utilisateur, et renvoie leurs identifiants."""
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="Organisation BE-100", slug=f"be100-{uuid.uuid4().hex[:10]}")
        utilisateur = User(
            email=f"be100-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com",
            hashedPassword="non-utilise-be100",
            fullName="Utilisateur BE-100",
        )
        db.add_all([organisation, utilisateur])
        await db.commit()
        return organisation.id, utilisateur.id


def _invitation(organisation_id: uuid.UUID, utilisateur_id: uuid.UUID, statut: str) -> Invitation:
    return Invitation(
        organizationId=organisation_id,
        recipientUserId=utilisateur_id,
        roleId=None,
        status=statut,
        expiresAt=datetime.now(timezone.utc) + timedelta(days=7),
        createdByUserId=utilisateur_id,
    )


async def test_be100_ca1_migration_cree_tenant_et_invitation_et_contraint_l_appartenance():
    tables = await _tables()
    assert {"tenant", "invitation", "organization_user"} <= tables
    assert "organizationUser" not in tables
    assert "status" in await _colonnes("organization_user")

    # Aller-retour : la migration se défait sans erreur, puis se refait sur la même base.
    cfg = _config()
    await asyncio.to_thread(command.downgrade, cfg, "-1")
    apres_retour = await _tables()
    assert "tenant" not in apres_retour
    assert "invitation" not in apres_retour
    assert "organizationUser" in apres_retour

    await asyncio.to_thread(command.upgrade, cfg, "head")
    assert {"tenant", "invitation", "organization_user"} <= await _tables()


async def test_be100_ca2_deux_appartenances_identiques_refusees_par_la_base():
    organisation_id, utilisateur_id = await _organisation_et_utilisateur()
    await _ajouter(OrganizationUser(organizationId=organisation_id, userId=utilisateur_id))

    with pytest.raises(IntegrityError):
        await _ajouter(OrganizationUser(organizationId=organisation_id, userId=utilisateur_id))


@pytest.mark.parametrize("statut", ["pending", "accepted", "expired", "revoked"])
async def test_be100_ca3_statut_d_invitation_parmi_les_quatre_valeurs_accepte(statut: str):
    organisation_id, utilisateur_id = await _organisation_et_utilisateur()
    await _ajouter(_invitation(organisation_id, utilisateur_id, statut))


async def test_be100_ca3_statut_d_invitation_hors_liste_refuse_par_la_base():
    organisation_id, utilisateur_id = await _organisation_et_utilisateur()

    with pytest.raises(IntegrityError):
        await _ajouter(_invitation(organisation_id, utilisateur_id, "annulee"))


async def test_be100_ca4_second_tenant_pour_une_organisation_refuse_par_la_base():
    organisation_id, _ = await _organisation_et_utilisateur()
    await _ajouter(Tenant(organizationId=organisation_id, status="active"))

    with pytest.raises(IntegrityError):
        await _ajouter(Tenant(organizationId=organisation_id, status="active"))


async def test_be100_statut_par_defaut_de_l_appartenance_et_du_tenant_vaut_active():
    organisation_id, utilisateur_id = await _organisation_et_utilisateur()
    await _ajouter(OrganizationUser(organizationId=organisation_id, userId=utilisateur_id))
    await _ajouter(Tenant(organizationId=organisation_id))

    async with AsyncSessionLocal() as db:
        statut_appartenance = (
            await db.execute(
                text('SELECT status FROM organization_user WHERE "organizationId" = :o AND "userId" = :u'),
                {"o": organisation_id, "u": utilisateur_id},
            )
        ).scalar_one()
        statut_tenant = (
            await db.execute(text('SELECT status FROM tenant WHERE "organizationId" = :o'), {"o": organisation_id})
        ).scalar_one()

    assert (statut_appartenance, statut_tenant) == ("active", "active")


async def test_be100_aucune_colonne_parent_id_sur_les_tables_d_organisation():
    for table in ("organization", "tenant", "organization_user", "invitation"):
        colonnes = await _colonnes(table)
        assert not {"parentId", "parent_id"} & colonnes, f"colonne parente interdite sur {table}"
