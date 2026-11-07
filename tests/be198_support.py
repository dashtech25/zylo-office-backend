"""Aides communes aux tests BE-198 (migration de module : expand, migrate, verify, contract, dry-run).

Source : implementation-backend/tasks-donnees-api-contrats.md, section BE-198.

Ce module n'est pas collecté par pytest (pas de préfixe `test_`) : il regroupe les fixtures
et les fonctions partagées par `tests/test_be198_*.py`.

Hypothèses de contrat, à confirmer par l'implémentation de BE-198 (la spec ne les fixe pas) :
- routes `POST /api/v1/admin/migrations/{migration_id}/{dry-run|run|resume|rollback}` ; le corps
  porte `{"tenantId": "<uuid>"}` (le cadre opère sur un tenant) ;
- réponses de run : champs `state` et `checkpoint` ;
- table `migration_run` (`migrationId`, `state`, `checkpoint`, `lockOwner`, `leaseExpiresAt`,
  `startedAt`, `report`) lue directement en SQL pour l'état persistant ;
- droit `platform.maintenance.run` attribué par allowlist d'environnement
  `PLATFORM_MAINTENANCE_RUN_USER_IDS`, même principe que BE-042 et BE-185 ;
- enregistrement d'une migration de test : `app.migrations_module.cadre.enregistre_migration(id, etapes)`,
  où `etapes` associe `expand`, `migrate`, `verify`, `contract` à des coroutines `(db, element)` ;
  l'étape `migrate` reçoit chaque élément de 1 à `nombre` dans sa propre transaction ;
- rollback refusé (409) lorsqu'un run a déjà produit un effet externe (correction en avant).
"""

import uuid
from dataclasses import dataclass, field

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.core.database import AsyncSessionLocal
from app.identity.models import Organization
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
ROUTE_MIGRATIONS = "/api/v1/admin/migrations"
VARIABLE_ALLOWLIST_MAINTENANCE = "PLATFORM_MAINTENANCE_RUN_USER_IDS"

CRASH_SIMULE = "crash simulé BE-198"
ECHEC_APRES_EFFET_EXTERNE = "échec simulé après effet externe BE-198"


def entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['token']}"}


async def cree_utilisateur(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-198"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "token": token}


@pytest.fixture
async def exploitant_maintenance(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Compte porteur du droit `platform.maintenance.run` (allowlist d'environnement)."""
    utilisateur = await cree_utilisateur(client)
    monkeypatch.setenv(VARIABLE_ALLOWLIST_MAINTENANCE, utilisateur["id"])
    return utilisateur


@pytest.fixture
async def exploitant_sans_droit(client: AsyncClient) -> dict:
    """Compte authentifié sans `platform.maintenance.run` : son identifiant n'entre dans aucune allowlist."""
    return await cree_utilisateur(client)


@dataclass
class MigrationDeTest:
    """Migration de test : écrit une ligne `Organization` par élément, dans le tenant du run.

    `traites` liste les éléments effectivement migrés ; `effets_externes` les appels à un
    adaptateur externe simulé. Les attributs de panne peuvent être modifiés en cours de test.
    """

    id: uuid.UUID
    nombre: int = 5
    crash_avant: int | None = None
    vole_verrou_apres: int | None = None
    echec_apres_effet_externe: int | None = None
    traites: list[int] = field(default_factory=list)
    effets_externes: list[int] = field(default_factory=list)

    async def _expand(self, db, element):
        return None

    async def _migrate(self, db, element):
        if element is None:
            return
        if self.crash_avant == element:
            raise RuntimeError(CRASH_SIMULE)
        if self.echec_apres_effet_externe == element:
            self.effets_externes.append(element)
            raise RuntimeError(ECHEC_APRES_EFFET_EXTERNE)
        db.add(Organization(
            id=uuid.uuid4(),
            name=f"BE-198 {element}",
            slug=f"be198-{self.id.hex[:12]}-{element}",
            status="active",
        ))
        await db.flush()
        self.traites.append(element)
        if self.vole_verrou_apres == element:
            await vole_le_verrou(self.id)

    async def _verify(self, db, element):
        return None

    async def _contract(self, db, element):
        return None

    def etapes(self) -> dict:
        return {
            "expand": self._expand,
            "migrate": self._migrate,
            "verify": self._verify,
            "contract": self._contract,
        }


async def enregistre_migration_de_test(**options) -> MigrationDeTest:
    """Crée et enregistre une migration de test dans le cadre BE-198."""
    from app.migrations_module.cadre import enregistre_migration

    migration = MigrationDeTest(id=uuid.uuid4(), **options)
    enregistre_migration(migration.id, migration.etapes())
    return migration


async def vole_le_verrou(migration_id: uuid.UUID) -> None:
    """Simule un autre processus qui prend le verrou du run (bail renouvelé à un autre propriétaire)."""
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET LOCAL lock_timeout = '3s'"))
        await db.execute(
            text(
                'UPDATE migration_run SET "lockOwner" = :proprietaire, '
                '"leaseExpiresAt" = now() + interval \'1 hour\' WHERE "migrationId" = :id'
            ),
            {"proprietaire": "autre-processus-be198", "id": migration_id},
        )
        await db.commit()


async def lit_run(migration_id: uuid.UUID) -> dict | None:
    """État persistant du run, lu directement dans `migration_run`."""
    async with AsyncSessionLocal() as db:
        ligne = (await db.execute(
            text('SELECT "state", "checkpoint", "lockOwner" FROM migration_run WHERE "migrationId" = :id'),
            {"id": migration_id},
        )).mappings().first()
        return dict(ligne) if ligne else None


async def compte_lignes_metier(migration: MigrationDeTest) -> int:
    """Nombre de lignes métier écrites par cette migration de test (filtre sur le slug propre)."""
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(func.count()).select_from(Organization).where(
                Organization.slug.like(f"be198-{migration.id.hex[:12]}-%")
            )
        )).scalar_one()


async def fixe_statut_tenant(organization_id: str, statut: str) -> None:
    """Place le tenant dans un état donné (`active`, `suspended`, `closed`)."""
    async with AsyncSessionLocal() as db:
        organisation = await db.get(Organization, uuid.UUID(organization_id))
        organisation.status = statut
        await db.commit()


async def lance_en_simulant_interruption(client: AsyncClient, chemin: str, corps: dict, entetes_: dict, message: str):
    """Appelle la route ; une panne simulée (`message`) n'interrompt pas le test."""
    try:
        return await client.post(chemin, json=corps, headers=entetes_)
    except RuntimeError as exc:
        if message not in str(exc):
            raise
        return None
