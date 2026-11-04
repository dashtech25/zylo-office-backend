"""BE-037 : réconciliation ORM et migrations (password_reset_token, notification_inbox_item).

Intention : prouver par des tests que
- chaque table de la tâche a une classe ORM dans les métadonnées SQLAlchemy,
  et le nom physique migré correspond au nom ORM (CA-1) ;
- la comparaison entre les métadonnées ORM et la base migrée (autogénération
  Alembic, `compare_metadata`) ne produit aucune différence (CA-2) ;
- toute table laissée hors ORM figure dans le registre d'exceptions de ce
  fichier, avec une raison et une référence de question (CA-3).

La base de test est celle de tests/conftest.py (zylo_t<NNN>_test), migrée à la
tête au début de la session. Aucune base de développement n'est lue.
"""

import importlib
import pkgutil

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

import app
from app.auth.models import PasswordResetToken
from app.core.database import AsyncSessionLocal, Base, engine
from app.notifications.models import NotificationInboxItem

TABLES_BE037 = {"password_reset_token", "notification_inbox_item"}

# Registre des tables laissées hors ORM (CA-3). Vide : aucune exception n'est
# admise à ce jour. Toute entrée future doit donner une raison et la question
# QE-<CODE>-nn qui la tranche ; sinon le test ci-dessous échoue.
EXCEPTIONS_HORS_ORM: dict[str, str] = {}


@pytest.fixture
async def pool_de_boucle_courante():
    """Repart d'un pool neuf lié à la boucle d'événements du test.

    Même précaution que la fixture `client` de conftest.py : l'engine est un
    singleton dont les connexions restent liées à la boucle qui les a ouvertes.
    """
    await engine.dispose()
    yield


def _importer_tous_les_modeles() -> None:
    """Charge chaque module `models` du paquet `app` pour remplir Base.metadata."""
    for info in pkgutil.walk_packages(app.__path__, "app."):
        if info.name.rsplit(".", 1)[-1] == "models":
            importlib.import_module(info.name)


def _resume(diff) -> str:
    """Résumé lisible d'un élément de compare_metadata (tuple ou liste imbriquée)."""
    while isinstance(diff, list):
        diff = diff[0]
    return f"{diff[0]} {getattr(diff[-1], 'name', diff[-1])}" if isinstance(diff, tuple) else repr(diff)


def _tables_touchees(diff) -> set[str]:
    """Noms de tables (chaînes ou objets nommés) présents dans un élément de compare_metadata."""
    noms: set[str] = set()

    def parcourir(x) -> None:
        if isinstance(x, list):
            for i in x:
                parcourir(i)
        elif isinstance(x, tuple):
            for e in x:
                if isinstance(e, str):
                    noms.add(e)
                elif isinstance(getattr(e, "name", None), str):
                    noms.add(e.name)
                elif isinstance(e, (list, tuple)):
                    parcourir(e)

    parcourir(diff)
    return noms


async def _differences_orm_et_base() -> list:
    async with engine.connect() as connexion:
        return await connexion.run_sync(
            lambda sync_conn: compare_metadata(MigrationContext.configure(sync_conn), Base.metadata)
        )


def test_tables_be037_ont_une_classe_orm_dans_les_metadonnees():
    """CA-1 : chaque table de la tâche est une Table des métadonnées SQLAlchemy."""
    _importer_tous_les_modeles()
    assert TABLES_BE037 <= set(Base.metadata.tables), TABLES_BE037 - set(Base.metadata.tables)


def test_classes_orm_portent_le_nom_snake_case_decide():
    """CA-1 : les classes ORM pointent sur les noms snake_case décidés par le propriétaire."""
    assert PasswordResetToken.__tablename__ == "password_reset_token"
    assert NotificationInboxItem.__tablename__ == "notification_inbox_item"


async def test_tables_be037_existent_sous_le_nom_snake_case_en_base(pool_de_boucle_courante):
    """CA-1 (base migrée) : les deux tables existent sous le nom décidé, l'ancien nom n'existe plus."""
    async with AsyncSessionLocal() as db:
        resultats = {}
        for nom in ("password_reset_token", "notification_inbox_item", "passwordResetToken", "notificationInboxItem"):
            resultats[nom] = await db.scalar(text("SELECT to_regclass(:n)"), {"n": f'public."{nom}"'})
    assert resultats["password_reset_token"] is not None
    assert resultats["notification_inbox_item"] is not None
    assert resultats["passwordResetToken"] is None
    assert resultats["notificationInboxItem"] is None


async def test_comparaison_orm_et_base_sans_difference(pool_de_boucle_courante):
    """CA-2 : l'autogénération Alembic ne trouve aucune différence sur les tables de BE-037.

    Périmètre restreint (décision d'intégration, lot be-037 fusionné dans develop) :
    la comparaison porte sur `password_reset_token` et `notification_inbox_item`.
    Les écarts restants, hors périmètre, relèvent de tables de la branche zyloLiquid
    et de tables du registre des modules (`zyloLiquid*`, `subscription_entitlement`,
    `capability`, `module`), qui ne font pas partie de BE-037. Ces écarts ne sont
    ni supprimés ni tolérés en général : ils restent à traiter dans leur tâche.
    Les tables fusionnées hors registre (`billing_payer`, `secret_registry`,
    `userInvitation`, `organizationInvitation`, `idempotencyKeys`) présentent des
    écarts de commentaires seulement ; elles sont signalées dans SUIVI.md et non
    incluses ici.
    Aucune exception n'est déclarée : EXCEPTIONS_HORS_ORM reste vide.
    """
    _importer_tous_les_modeles()
    differences = await _differences_orm_et_base()
    tables_exceptees = set(EXCEPTIONS_HORS_ORM)
    restantes = [
        d for d in differences
        if _tables_touchees(d) & TABLES_BE037 and not _tables_touchees(d) & tables_exceptees
    ]
    assert restantes == [], [_resume(d) for d in restantes]


def test_exceptions_hors_orm_sont_motivees():
    """CA-3 : chaque exception du registre a une raison et une référence de question QE-."""
    for table, motif in EXCEPTIONS_HORS_ORM.items():
        assert isinstance(motif, str) and "QE-" in motif, f"exception sans motif documenté : {table}"
