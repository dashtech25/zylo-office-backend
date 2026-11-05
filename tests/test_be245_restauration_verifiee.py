"""Tests BE-245 : restauration vérifiée et ordre de restauration.

Couvre les critères CA-1 à CA-5 et le refus 403 de la définition (implementation-backend/
tasks-exploitation-architecture.md, section BE-245). Écrits d'après la définition, avant le code.
Les noms nouveaux sont importés à l'intérieur de chaque test : chaque test échoue pour sa seule
raison, sans faire échouer la collecte du module.

Réutilisation : la sauvegarde et la restauration de base passent par `sauvegarder_base` et
`restaurer_sauvegarde` (BE-175). La preuve de génération vient de `BackupRun` (BE-244).

Garde de sécurité : la restauration vise toujours une base jetable distincte de la base source
(`zylo_t245_restauration_test`), créée et supprimée par ce module.

Points non couverts, voir QE-EXP (remontés dans le rapport) : restauration sélective d'un seul
tenant (le test CA-3 vérifie l'isolement du tenant contrôlé sur une restauration complète).
"""

import hashlib
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.errors import AppError
from app.identity.models import User
from app.operator.restauration import sauvegarder_base

# Base jetable de l'exercice. Hors motif zylo_t<NNN>_test (garde de conftest) : base éphémère.
NOM_BASE_EXERCICE = "zylo_t245_restauration_test"


def _url_base_source():
    """URL de la base de test de la tâche (TEST_DATABASE_URL, posée par l'environnement)."""
    return make_url(os.environ["TEST_DATABASE_URL"])


@pytest.fixture
async def base_jetable():
    """Crée une base vide pour l'exercice, la supprime à la fin du test."""
    admin = create_async_engine(
        _url_base_source().set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin.connect() as connexion:
        await connexion.execute(text(f'DROP DATABASE IF EXISTS "{NOM_BASE_EXERCICE}" WITH (FORCE)'))
        await connexion.execute(text(f'CREATE DATABASE "{NOM_BASE_EXERCICE}"'))
    yield NOM_BASE_EXERCICE
    async with admin.connect() as connexion:
        await connexion.execute(text(f'DROP DATABASE IF EXISTS "{NOM_BASE_EXERCICE}" WITH (FORCE)'))
    await admin.dispose()


@pytest.fixture
async def db():
    from app.operator.backup_models import BackupRun
    from app.operator.restore_drill_models import RestoreDrill

    moteur = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        async with async_sessionmaker(bind=moteur, expire_on_commit=False)() as session:
            await session.execute(delete(RestoreDrill))
            await session.execute(delete(BackupRun))
            await session.commit()
            yield session
            await session.rollback()
            await session.execute(delete(RestoreDrill))
            await session.execute(delete(BackupRun))
            await session.commit()
    finally:
        await moteur.dispose()


@pytest.fixture
def operateur(monkeypatch):
    identifiant = uuid.uuid4()
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(identifiant))
    return SimpleNamespace(id=identifiant)


async def _sauvegarde_enregistree(db, dossier: Path):
    """Produit un dump (BE-175) et sa ligne `backup_runs` (BE-244) avec l'empreinte du fichier."""
    import datetime as dt

    from app.operator.backup_models import BackupRun

    fichier = sauvegarder_base(dossier)
    octets = fichier.read_bytes()
    ligne = BackupRun(
        horodatage=dt.datetime.now(dt.timezone.utc),
        perimetre="plateforme",
        volume=len(octets),
        resultat="reussie",
        empreinte=hashlib.sha256(octets).hexdigest(),
        emplacement="exploitation-local",
        chiffrement=False,
    )
    db.add(ligne)
    await db.commit()
    return ligne, fichier


def _etapes_sans_effet() -> dict:
    """Étapes hors base (fichiers, secrets, files, identités) sans effet, pour l'exercice de la base."""
    return {nom: (lambda: None) for nom in ("fichiers", "secrets", "files", "identites")}


async def _moteur(nom: str):
    return create_async_engine(_url_base_source().set(database=nom), poolclass=NullPool)


async def _tables_public(moteur) -> set[str]:
    async with moteur.connect() as connexion:
        resultat = await connexion.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        return {ligne[0] for ligne in resultat.all()}


# CA-1 : restauration isolée réussit et les invariants passent ; test d'exercice sur base jetable.
async def test_be245_ca1_restauration_isolee_reussit_et_invariants_passent(
    db, operateur, base_jetable: str, tmp_path: Path
):
    from app.operator.restore_drill_models import RestoreDrill
    from app.operator.restauration_verifiee import exercer_restauration

    sauvegarde, fichier = await _sauvegarde_enregistree(db, tmp_path)

    exercice = await exercer_restauration(
        db, operateur.id, sauvegarde, fichier, base_jetable, etapes=_etapes_sans_effet()
    )
    await db.commit()

    assert exercice.resultat == "reussie"
    assert exercice.invariants, "l'exercice doit enregistrer les invariants vérifiés"
    assert all(exercice.invariants.values()), exercice.invariants
    assert "tables_presentes" in exercice.invariants
    assert exercice.environnement == base_jetable
    assert {etape["etape"] for etape in exercice.durees} == {"base", "fichiers", "secrets", "files", "identites"}
    assert all(etape["duree_ms"] >= 0 for etape in exercice.durees)

    moteur_source = await _moteur(_url_base_source().database)
    moteur_cible = await _moteur(base_jetable)
    try:
        assert await _tables_public(moteur_cible) == await _tables_public(moteur_source)
    finally:
        await moteur_source.dispose()
        await moteur_cible.dispose()

    persistee = await db.scalar(select(RestoreDrill).where(RestoreDrill.id == exercice.id))
    assert persistee is not None and persistee.resultat == "reussie"


# CA-2 : l'ordre (base, fichiers, secrets, files, identités) est respecté ; test de séquence.
async def test_be245_ca2_ordre_base_fichiers_secrets_files_identites(db, operateur, base_jetable: str, tmp_path: Path):
    from app.operator.restauration_verifiee import ORDRE_RESTAURATION, exercer_restauration

    assert ORDRE_RESTAURATION == ("base", "fichiers", "secrets", "files", "identites")

    sauvegarde, fichier = await _sauvegarde_enregistree(db, tmp_path)
    sequence: list[str] = []
    # Dictionnaire volontairement dans le désordre : l'ordre doit venir de la définition, pas de l'appelant.
    etapes = {
        "identites": lambda: sequence.append("identites"),
        "files": lambda: sequence.append("files"),
        "secrets": lambda: sequence.append("secrets"),
        "fichiers": lambda: sequence.append("fichiers"),
    }

    exercice = await exercer_restauration(db, operateur.id, sauvegarde, fichier, base_jetable, etapes=etapes)

    assert sequence == ["fichiers", "secrets", "files", "identites"]
    assert [etape["etape"] for etape in exercice.durees] == list(ORDRE_RESTAURATION)


async def test_be245_ca2_etape_absente_donne_echec(db, operateur, base_jetable: str, tmp_path: Path):
    from app.operator.restauration_verifiee import exercer_restauration

    sauvegarde, fichier = await _sauvegarde_enregistree(db, tmp_path)
    etapes = _etapes_sans_effet()
    del etapes["identites"]

    exercice = await exercer_restauration(db, operateur.id, sauvegarde, fichier, base_jetable, etapes=etapes)

    assert exercice.resultat == "echec"


# CA-3 : restauration tenant par tenant ne mélange pas les données ; test d'isolation.
async def test_be245_ca3_restauration_tenant_ne_melange_pas_les_donnees(
    client: AsyncClient, registered_user: dict, organization: dict, db, operateur, base_jetable: str,
    tmp_path: Path, monkeypatch
):
    import datetime as dt  # noqa: F401  (import local au test, comme dans BE-244)

    from app.operator.restauration_verifiee import exercer_restauration
    from app.parametres.models import SettingDefinition
    from app.parametres.service import ecrire_version
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        user_id = user.id
    org_a = uuid.UUID(organization["id"])
    reponse = await client.post(
        "/api/v1/organizations",
        json={"name": "Autre Org BE245", "slug": f"autre-be245-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    org_b = uuid.UUID(reponse.json()["id"])

    cle = f"test.be245.{uuid.uuid4().hex[:10]}"
    async with AsyncSessionLocal() as session:
        session.add(SettingDefinition(key=cle, scopeKind="organisation", owner="test-be245", valueType="texte", sensitive=False))
        await session.commit()
    async with AsyncSessionLocal() as session:
        await ecrire_version(session, cle, "organisation", org_a, 1, {"v": "A"}, user_id, "tenant A")
    async with AsyncSessionLocal() as session:
        await ecrire_version(session, cle, "organisation", org_b, 1, {"v": "B"}, user_id, "tenant B")

    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(operateur.id))
    sauvegarde, fichier = await _sauvegarde_enregistree(db, tmp_path)

    exercice = await exercer_restauration(
        db, operateur.id, sauvegarde, fichier, base_jetable, etapes=_etapes_sans_effet(), tenant_id=org_a
    )
    await db.commit()

    assert exercice.resultat == "reussie"
    assert exercice.invariants.get("isolement_tenant") is True

    requete_par_tenant = text('SELECT count(*) FROM setting_value WHERE "scopeId" = :org')
    moteur_source = await _moteur(_url_base_source().database)
    moteur_cible = await _moteur(base_jetable)
    try:
        for org in (org_a, org_b):
            async with moteur_source.connect() as c1, moteur_cible.connect() as c2:
                attendu = await c1.scalar(requete_par_tenant, {"org": org})
                obtenu = await c2.scalar(requete_par_tenant, {"org": org})
            assert obtenu == attendu and attendu > 0
        # Aucune ligne du tenant B n'a été rattachée au tenant A dans la base restaurée.
        async with moteur_cible.connect() as connexion:
            fuite = await connexion.scalar(
                text('SELECT count(*) FROM setting_value WHERE "scopeId" = :a AND "createdBy" IS NULL'), {"a": org_a}
            )
        assert fuite == 0
    finally:
        await moteur_source.dispose()
        await moteur_cible.dispose()


# CA-4 : restauration sans droit donne 403 ; test de refus.
async def test_be245_ca4_exercice_sans_droit_operateur_donne_403(db, base_jetable: str, tmp_path: Path, monkeypatch):
    from app.operator.restore_drill_models import RestoreDrill
    from app.operator.restauration_verifiee import exercer_restauration

    sauvegarde, fichier = await _sauvegarde_enregistree(db, tmp_path)
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(uuid.uuid4()))

    with pytest.raises(AppError) as erreur:
        await exercer_restauration(db, uuid.uuid4(), sauvegarde, fichier, base_jetable, etapes=_etapes_sans_effet())
    assert erreur.value.status_code == 403

    assert await db.scalar(select(func.count()).select_from(RestoreDrill)) == 0
    moteur_cible = await _moteur(base_jetable)
    try:
        async with moteur_cible.connect() as connexion:
            assert await connexion.scalar(text("SELECT to_regclass('setting_value')")) is None
    finally:
        await moteur_cible.dispose()


# CA-5 : une donnée purgée avant sauvegarde n'est pas ressuscitée après restauration ; test de suppression.
async def test_be245_ca5_donnee_purgee_avant_sauvegarde_non_ressuscitee(
    db, operateur, base_jetable: str, tmp_path: Path
):
    from app.core.database import AsyncSessionLocal
    from app.operator.restauration_verifiee import exercer_restauration
    from app.parametres.models import SettingDefinition

    table = SettingDefinition.__table__
    cle = f"test.be245.purge.{uuid.uuid4().hex[:10]}"
    async with AsyncSessionLocal() as session:
        session.add(SettingDefinition(key=cle, scopeKind="organisation", owner="test-be245", valueType="texte", sensitive=False))
        await session.commit()
    async with AsyncSessionLocal() as session:
        await session.execute(delete(SettingDefinition).where(table.c.key == cle))
        await session.commit()

    sauvegarde, fichier = await _sauvegarde_enregistree(db, tmp_path)
    exercice = await exercer_restauration(db, operateur.id, sauvegarde, fichier, base_jetable, etapes=_etapes_sans_effet())
    assert exercice.resultat == "reussie"

    moteur_cible = await _moteur(base_jetable)
    try:
        async with moteur_cible.connect() as connexion:
            presentes = await connexion.scalar(select(func.count()).select_from(table).where(table.c.key == cle))
        assert presentes == 0, "une donnée purgée avant la sauvegarde ne doit pas revenir"
    finally:
        await moteur_cible.dispose()


async def test_be245_refuse_base_non_isolee(db, operateur, tmp_path: Path):
    from app.operator.restauration_verifiee import exercer_restauration

    sauvegarde, fichier = await _sauvegarde_enregistree(db, tmp_path)

    with pytest.raises(AppError) as erreur:
        await exercer_restauration(
            db, operateur.id, sauvegarde, fichier, _url_base_source().database, etapes=_etapes_sans_effet()
        )
    assert erreur.value.status_code == 422


async def test_be245_empreinte_alteree_donne_echec_sans_restauration(db, operateur, base_jetable: str, tmp_path: Path):
    from app.operator.restauration_verifiee import exercer_restauration

    sauvegarde, fichier = await _sauvegarde_enregistree(db, tmp_path)
    fichier.write_bytes(fichier.read_bytes() + b"\n-- altere\n")

    exercice = await exercer_restauration(db, operateur.id, sauvegarde, fichier, base_jetable, etapes=_etapes_sans_effet())

    assert exercice.resultat == "echec"
    assert exercice.invariants.get("empreinte_intacte") is False
    moteur_cible = await _moteur(base_jetable)
    try:
        async with moteur_cible.connect() as connexion:
            assert await connexion.scalar(text("SELECT to_regclass('setting_value')")) is None
    finally:
        await moteur_cible.dispose()
