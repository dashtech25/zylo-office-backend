"""BE-042 : enregistrement et publication des versions de module.

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-modules-droits.md,
section BE-042) avant le code.

Décisions de test (voir la docstring de `app.modules_registry.catalogue_publication`) :
- les droits plateforme (`platform.module.write`, `platform.module.publish`) sont accordés par
  allowlists d'environnement (`PLATFORM_MODULE_WRITE_USER_IDS`, `PLATFORM_MODULE_PUBLISH_USER_IDS`) ;
  les tests les posent avec `monkeypatch`, sans valeur réelle ;
- la révision précédente de la migration BE-042 est `f668520e8d62` (tête de BE-041/BE-071/BE-037).
"""

import logging
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.identity.models import User
from app.modules_registry.models import Module, ModuleStateTransition, ModuleVersion

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REVISION_PRECEDENTE_BE042 = "f668520e8d62"
URL_MODULES = "/api/v1/admin/modules"
LOGGER_PUBLICATION = "app.modules_registry.catalogue_publication"


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    from app.core.database import engine

    await engine.dispose()
    yield


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


def _entetes(registered_user: dict, correlation: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    if correlation is not None:
        entetes["X-Correlation-Id"] = correlation
    return entetes


async def _donner_droits(monkeypatch, registered_user: dict, *, write: bool, publish: bool) -> uuid.UUID:
    """Accorde (ou refuse) les droits plateforme au compte de test, via les allowlists d'environnement."""
    user_id = await _id_utilisateur(registered_user["email"])
    monkeypatch.setenv("PLATFORM_MODULE_WRITE_USER_IDS", str(user_id) if write else "")
    monkeypatch.setenv("PLATFORM_MODULE_PUBLISH_USER_IDS", str(user_id) if publish else "")
    return user_id


async def _creer_module(client: AsyncClient, registered_user: dict) -> dict:
    code = f"mod-be042-{uuid.uuid4().hex[:10]}"
    res = await client.post(
        URL_MODULES,
        json={"code": code, "name": "Module BE-042", "description": "Test de publication"},
        headers=_entetes(registered_user),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _creer_version(
    client: AsyncClient, registered_user: dict, module_id: str, *, digest=None, provenance=None
) -> dict:
    res = await client.post(
        f"{URL_MODULES}/{module_id}/versions",
        json={"version": "1.0.0", "digest": digest, "provenance": provenance, "licence": "proprietary"},
        headers=_entetes(registered_user),
    )
    assert res.status_code == 201, res.text
    return res.json()


def _version_complete_body(state_version: int, cle: str | None = None) -> dict:
    corps = {"stateVersion": state_version}
    if cle is not None:
        corps["idempotencyKey"] = cle
    return corps


async def _etat_version_en_base(version_id: str) -> tuple[str, object]:
    async with AsyncSessionLocal() as db:
        ligne = (
            await db.execute(select(ModuleVersion).where(ModuleVersion.id == uuid.UUID(version_id)))
        ).scalar_one()
        return ligne.publicationState, ligne.publishedAt


async def _journal_de_version(version_id: str) -> list[ModuleStateTransition]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(ModuleStateTransition)
                    .where(
                        ModuleStateTransition.subjectType == "module_version",
                        ModuleStateTransition.subjectId == uuid.UUID(version_id),
                    )
                    .order_by(ModuleStateTransition.stateVersionAfter)
                )
            ).scalars()
        )


async def _forcer_etat_review(version_id: str) -> None:
    """Prépare une version « en revue » directement en base (la route de revue n'existe pas en BE-042)."""
    async with AsyncSessionLocal() as db:
        ligne = (
            await db.execute(select(ModuleVersion).where(ModuleVersion.id == uuid.UUID(version_id)))
        ).scalar_one()
        ligne.publicationState = "review"
        await db.commit()


def test_migration_be042_ajoute_publication_state_et_reste_reversible():
    """CA transverse : la colonne d'état de version existe, et l'aller-retour de migration fonctionne."""
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def colonnes_version() -> set[str]:
        engine = create_async_engine(os.environ["DATABASE_URL"])
        try:
            async with engine.connect() as conn:
                return set(
                    (
                        await conn.execute(
                            text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_name='module_version' AND table_schema='public'"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
        finally:
            await engine.dispose()

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    assert "publicationState" in asyncio.run(colonnes_version())
    command.downgrade(cfg, REVISION_PRECEDENTE_BE042)
    try:
        assert "publicationState" not in asyncio.run(colonnes_version())
    finally:
        command.upgrade(cfg, "head")
    assert "publicationState" in asyncio.run(colonnes_version())


async def test_creation_module_et_version_en_draft(client: AsyncClient, registered_user: dict, monkeypatch):
    await _donner_droits(monkeypatch, registered_user, write=True, publish=False)
    module = await _creer_module(client, registered_user)
    assert module["publicationState"] == "draft"

    version = await _creer_version(client, registered_user, module["id"], digest="sha256:abc", provenance="depot/b1")
    assert version["publicationState"] == "draft"
    assert version["publishedAt"] is None

    lecture = await client.get(f"{URL_MODULES}/{module['id']}", headers=_entetes(registered_user))
    assert lecture.status_code == 200, lecture.text
    assert lecture.json()["publicationState"] == "draft"


async def test_creation_sans_droit_d_ecriture_renvoie_403(client: AsyncClient, registered_user: dict, monkeypatch):
    await _donner_droits(monkeypatch, registered_user, write=False, publish=False)
    res = await client.post(
        URL_MODULES, json={"code": f"mod-{uuid.uuid4().hex[:8]}", "name": "X"}, headers=_entetes(registered_user)
    )
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_sans_authentification_renvoie_401(client: AsyncClient):
    res = await client.post(URL_MODULES, json={"code": "mod-anonyme", "name": "X"})
    assert res.status_code == 401, res.text


async def test_ca1_sans_droit_de_publication_403_et_version_reste_review(
    client: AsyncClient, registered_user: dict, monkeypatch
):
    await _donner_droits(monkeypatch, registered_user, write=True, publish=False)
    module = await _creer_module(client, registered_user)
    version = await _creer_version(client, registered_user, module["id"], digest="sha256:abc", provenance="depot/b1")
    await _forcer_etat_review(version["id"])

    res = await client.post(
        f"{URL_MODULES}/{module['id']}/versions/{version['id']}/publish",
        json=_version_complete_body(state_version=version["stateVersion"], cle=str(uuid.uuid4())),
        headers=_entetes(registered_user),
    )
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"
    etat, publie_le = await _etat_version_en_base(version["id"])
    assert etat == "review"
    assert publie_le is None


async def test_ca2_version_sans_digest_ou_sans_provenance_renvoie_422(
    client: AsyncClient, registered_user: dict, monkeypatch
):
    await _donner_droits(monkeypatch, registered_user, write=True, publish=True)
    module = await _creer_module(client, registered_user)
    sans_digest = await _creer_version(client, registered_user, module["id"], provenance="depot/b1")
    res = await client.post(
        f"{URL_MODULES}/{module['id']}/versions/{sans_digest['id']}/publish",
        json=_version_complete_body(state_version=sans_digest["stateVersion"], cle=str(uuid.uuid4())),
        headers=_entetes(registered_user),
    )
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "MODULE_VERSION_INCOMPLETE"
    assert (await _etat_version_en_base(sans_digest["id"]))[0] == "draft"

    version = await _creer_version(client, registered_user, module["id"], digest="sha256:abc")
    res = await client.post(
        f"{URL_MODULES}/{module['id']}/versions/{version['id']}/publish",
        json=_version_complete_body(state_version=version["stateVersion"], cle=str(uuid.uuid4())),
        headers=_entetes(registered_user),
    )
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "MODULE_VERSION_INCOMPLETE"


async def test_publication_complete_passe_par_review_puis_published(
    client: AsyncClient, registered_user: dict, monkeypatch
):
    await _donner_droits(monkeypatch, registered_user, write=True, publish=True)
    module = await _creer_module(client, registered_user)
    version = await _creer_version(client, registered_user, module["id"], digest="sha256:abc", provenance="depot/b1")

    res = await client.post(
        f"{URL_MODULES}/{module['id']}/versions/{version['id']}/publish",
        json=_version_complete_body(state_version=version["stateVersion"], cle=str(uuid.uuid4())),
        headers=_entetes(registered_user),
    )
    assert res.status_code == 200, res.text
    assert res.json()["publicationState"] == "published"
    assert res.json()["publishedAt"] is not None

    journal = await _journal_de_version(version["id"])
    assert [(ligne.fromState, ligne.toState) for ligne in journal] == [("draft", "review"), ("review", "published")]


async def test_ca3_republication_meme_cle_rend_le_meme_resultat_autre_cle_409(
    client: AsyncClient, registered_user: dict, monkeypatch
):
    await _donner_droits(monkeypatch, registered_user, write=True, publish=True)
    module = await _creer_module(client, registered_user)
    version = await _creer_version(client, registered_user, module["id"], digest="sha256:abc", provenance="depot/b1")
    cle = str(uuid.uuid4())
    url = f"{URL_MODULES}/{module['id']}/versions/{version['id']}/publish"

    premiere = await client.post(
        url, json=_version_complete_body(state_version=1, cle=cle), headers=_entetes(registered_user)
    )
    assert premiere.status_code == 200, premiere.text

    rejeu = await client.post(
        url, json=_version_complete_body(state_version=1, cle=cle), headers=_entetes(registered_user)
    )
    assert rejeu.status_code == 200, rejeu.text
    assert rejeu.json()["publishedAt"] == premiere.json()["publishedAt"]

    autre = await client.post(
        url, json=_version_complete_body(state_version=3, cle=str(uuid.uuid4())), headers=_entetes(registered_user)
    )
    assert autre.status_code == 409, autre.text
    assert autre.json()["error"]["code"] == "MODULE_VERSION_ALREADY_PUBLISHED"
    assert len(await _journal_de_version(version["id"])) == 2


async def test_ca4_publication_journalise_acteur_et_emet_evenement_avec_correlation(
    client: AsyncClient, registered_user: dict, monkeypatch, caplog
):
    user_id = await _donner_droits(monkeypatch, registered_user, write=True, publish=True)
    module = await _creer_module(client, registered_user)
    version = await _creer_version(client, registered_user, module["id"], digest="sha256:abc", provenance="depot/b1")
    correlation = str(uuid.uuid4())

    caplog.set_level(logging.INFO, logger=LOGGER_PUBLICATION)
    res = await client.post(
        f"{URL_MODULES}/{module['id']}/versions/{version['id']}/publish",
        json=_version_complete_body(state_version=1, cle=str(uuid.uuid4())),
        headers=_entetes(registered_user, correlation=correlation),
    )
    assert res.status_code == 200, res.text

    journal = await _journal_de_version(version["id"])
    assert journal and all(ligne.actorId == user_id for ligne in journal)
    assert all(ligne.origin == "platform" for ligne in journal)

    evenements = [r for r in caplog.records if r.getMessage() == "ModuleVersionPublished"]
    assert len(evenements) == 1
    assert getattr(evenements[0], "correlation_id", None) == correlation
    assert getattr(evenements[0], "actor_id", None) == str(user_id)


async def test_ca5_rejet_repasse_en_draft_et_conserve_le_motif(monkeypatch, registered_user: dict, client: AsyncClient):
    from app.modules_registry.catalogue_publication import rejeter_version

    await _donner_droits(monkeypatch, registered_user, write=True, publish=True)
    module = await _creer_module(client, registered_user)
    version = await _creer_version(client, registered_user, module["id"], digest="sha256:abc", provenance="depot/b1")
    await _forcer_etat_review(version["id"])
    acteur = await _id_utilisateur(registered_user["email"])

    async with AsyncSessionLocal() as db:
        ligne = (
            await db.execute(select(ModuleVersion).where(ModuleVersion.id == uuid.UUID(version["id"])))
        ).scalar_one()
        await rejeter_version(db, ligne, acteur_id=acteur, motif="Licence non renseignée")
        await db.commit()

    etat, _ = await _etat_version_en_base(version["id"])
    assert etat == "draft"
    journal = await _journal_de_version(version["id"])
    assert journal[-1].fromState == "review"
    assert journal[-1].toState == "draft"
    assert journal[-1].reason == "Licence non renseignée"
