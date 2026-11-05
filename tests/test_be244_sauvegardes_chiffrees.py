"""Tests BE-244 : sauvegardes chiffrées, isolées et preuve de génération.

Couvre les critères CA-1 à CA-5 et le refus 403 de la définition (implementation-backend/
tasks-exploitation-architecture.md, section BE-244). Écrits d'après la définition, avant le code.
Les noms nouveaux sont importés à l'intérieur de chaque test : chaque test échoue pour sa seule
raison, sans faire échouer la collecte du module.

Clé maître et politique de test : valeurs fictives posées par monkeypatch (jamais de vraie clé,
jamais de valeur codée dans le code). Les valeurs de politique ci-dessous ne sont que des entrées
de test ; la définition laisse RPO, fréquence et rétention NON DÉFINI (voir QE-EXP-04).
"""

import ast
import gzip
import hashlib
import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

CLE_MAITRE_TEST = "cle-maitre-be244-fictive-0123456789abcdef0123"


@pytest.fixture
async def db():
    from app.operator.backup_models import BackupRun
    from app.operator.encryption_models import EncryptionKey

    # Moteur propre à chaque test (NullPool), comme dans test_chiffrement_be231.py.
    moteur = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        async with async_sessionmaker(bind=moteur, expire_on_commit=False)() as session:
            await session.execute(delete(BackupRun))
            await session.execute(delete(EncryptionKey))
            await session.commit()
            yield session
            await session.rollback()
            await session.execute(delete(BackupRun))
            await session.execute(delete(EncryptionKey))
            await session.commit()
    finally:
        await moteur.dispose()


@pytest.fixture
def cle_maitre(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_FIELD_ENCRYPTION_KEY", CLE_MAITRE_TEST)
    return CLE_MAITRE_TEST


@pytest.fixture
def operateur(monkeypatch):
    identifiant = uuid.uuid4()
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(identifiant))
    return SimpleNamespace(id=identifiant)


@pytest.fixture
def politique(monkeypatch):
    """Politique de test complète (valeurs fictives, injectées dans la configuration)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "BACKUP_FREQUENCE", "0 3 * * 1")
    monkeypatch.setattr(settings, "BACKUP_RPO_HEURES", 6)
    monkeypatch.setattr(settings, "BACKUP_RETENTION_JOURS", 45)


def _fichiers_sauvegarde(dossier: Path) -> list[Path]:
    return sorted(p for p in dossier.iterdir() if p.is_file())


# CA-1 : chaque sauvegarde produit une entrée avec résultat et empreinte ; test.
async def test_ca1_sauvegarde_reussie_produit_une_entree_avec_resultat_et_empreinte(
    db, cle_maitre, operateur, politique, tmp_path
):
    from app.operator.backup_models import BackupRun
    from app.operator.sauvegarde_chiffree import sauvegarder_chiffree

    await db.commit()
    await sauvegarder_chiffree(db, operateur.id, tmp_path)
    await db.commit()

    lignes = (await db.execute(select(BackupRun))).scalars().all()
    assert len(lignes) == 1
    ligne = lignes[0]
    assert ligne.resultat == "reussie"
    assert ligne.horodatage is not None
    assert ligne.perimetre == "plateforme"
    assert ligne.chiffrement is True

    fichiers = _fichiers_sauvegarde(tmp_path)
    assert len(fichiers) == 1
    contenu = fichiers[0].read_bytes()
    assert ligne.volume == len(contenu)
    assert ligne.empreinte == hashlib.sha256(contenu).hexdigest()


async def test_ca1_sauvegarde_en_echec_produit_aussi_une_entree(
    db, cle_maitre, operateur, politique, tmp_path, monkeypatch
):
    from app.operator import sauvegarde_chiffree as module
    from app.operator.backup_models import BackupRun

    def _pg_dump_en_echec(dossier: Path) -> Path:
        raise RuntimeError("pg_dump en échec (simulé)")

    monkeypatch.setattr(module, "sauvegarder_base", _pg_dump_en_echec)
    await db.commit()
    run = await module.sauvegarder_chiffree(db, operateur.id, tmp_path)
    await db.commit()

    assert run.resultat == "echec"
    lignes = (await db.execute(select(BackupRun))).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].resultat == "echec"
    assert lignes[0].empreinte is None
    assert _fichiers_sauvegarde(tmp_path) == []


# CA-2 : une sauvegarde est chiffrée (contrôle de présence du chiffrement) ; test.
async def test_ca2_sauvegarde_chiffree_sans_dump_en_clair(db, cle_maitre, operateur, politique, tmp_path):
    from app.core.field_crypto import fernet_maitre
    from app.operator.sauvegarde_chiffree import sauvegarder_chiffree

    await db.commit()
    await sauvegarder_chiffree(db, operateur.id, tmp_path)
    await db.commit()

    fichiers = _fichiers_sauvegarde(tmp_path)
    # Aucun dump en clair ne doit subsister à côté de l'artefact chiffré.
    assert len(fichiers) == 1
    contenu = fichiers[0].read_bytes()
    assert not contenu.startswith(b"\x1f\x8b")
    assert b"CREATE TABLE" not in contenu
    # Le déchiffrement par la clé maître rend bien un dump gzip complet.
    dump = gzip.decompress(fernet_maitre().decrypt(contenu))
    assert b"CREATE TABLE" in dump


async def test_ca2_controle_refuse_un_fichier_non_chiffre(tmp_path):
    from app.operator.sauvegarde_chiffree import SauvegardeError, verifier_chiffrement

    en_clair = tmp_path / "zylo_office_clair.sql.gz"
    en_clair.write_bytes(gzip.compress(b"CREATE TABLE public.users (id uuid);\n"))
    with pytest.raises(SauvegardeError):
        verifier_chiffrement(en_clair)


# CA-3 : une sauvegarde partielle est signalée en échec ; test.
async def test_ca3_sauvegarde_partielle_est_signalee_en_echec(
    db, cle_maitre, operateur, politique, tmp_path, monkeypatch
):
    from app.operator import sauvegarde_chiffree as module
    from app.operator.backup_models import BackupRun

    def _dump_partiel(dossier: Path) -> Path:
        # Un seul table sur l'ensemble de la base : dump tronqué.
        dossier.mkdir(parents=True, exist_ok=True)
        fichier = dossier / "zylo_office_partiel.sql.gz"
        fichier.write_bytes(gzip.compress(b'CREATE TABLE public."users" (id uuid);\n'))
        return fichier

    monkeypatch.setattr(module, "sauvegarder_base", _dump_partiel)
    await db.commit()
    run = await module.sauvegarder_chiffree(db, operateur.id, tmp_path)
    await db.commit()

    assert run.resultat == "echec"
    lignes = (await db.execute(select(BackupRun))).scalars().all()
    assert [ligne.resultat for ligne in lignes] == ["echec"]
    assert _fichiers_sauvegarde(tmp_path) == []


# CA-4 : la sauvegarde ne contient aucune clé en clair ; test de scan.
async def test_ca4_la_sauvegarde_ne_contient_aucune_cle_en_clair(db, cle_maitre, operateur, politique, tmp_path):
    from app.core.crypto import desenvelopper_cle
    from app.core.field_crypto import fernet_maitre
    from app.operator.encryption_models import EncryptionKey
    from app.operator.encryption_service import rotate_key
    from app.operator.sauvegarde_chiffree import sauvegarder_chiffree
    import datetime as dt

    await rotate_key(db, operateur, dt.datetime.now(dt.timezone.utc))
    await db.commit()
    ligne = (await db.execute(select(EncryptionKey))).scalars().one()
    cle_en_clair = desenvelopper_cle(ligne.wrappedKey)

    await sauvegarder_chiffree(db, operateur.id, tmp_path)
    await db.commit()

    dump = gzip.decompress(fernet_maitre().decrypt(_fichiers_sauvegarde(tmp_path)[0].read_bytes()))
    # Le dump contient la table des clés (enveloppe présente), mais jamais la clé en clair ni la clé maître.
    assert ligne.wrappedKey.encode("ascii") in dump
    assert cle_en_clair not in dump
    assert CLE_MAITRE_TEST.encode("ascii") not in dump


# CA-5 : fréquence, RPO et rétention lus de la configuration, valeurs NON DÉFINI ; test d'absence de constante codée.
def test_ca5_politique_lue_de_la_configuration(monkeypatch):
    from app.core.config import settings
    from app.operator.sauvegarde_chiffree import lire_politique_sauvegarde

    monkeypatch.setattr(settings, "BACKUP_FREQUENCE", "0 4 * * *")
    monkeypatch.setattr(settings, "BACKUP_RPO_HEURES", 12)
    monkeypatch.setattr(settings, "BACKUP_RETENTION_JOURS", 90)

    politique = lire_politique_sauvegarde()
    assert politique.frequence == "0 4 * * *"
    assert politique.rpo_heures == 12
    assert politique.retention_jours == 90


async def test_ca5_valeurs_non_definies_refusent_la_sauvegarde(db, cle_maitre, operateur, monkeypatch, tmp_path):
    from app.core.config import settings
    from app.core.errors import AppError
    from app.operator.backup_models import BackupRun
    from app.operator.sauvegarde_chiffree import sauvegarder_chiffree

    monkeypatch.setattr(settings, "BACKUP_FREQUENCE", "")
    monkeypatch.setattr(settings, "BACKUP_RPO_HEURES", None)
    monkeypatch.setattr(settings, "BACKUP_RETENTION_JOURS", None)

    with pytest.raises(AppError):
        await sauvegarder_chiffree(db, operateur.id, tmp_path)
    await db.commit()
    assert (await db.execute(select(BackupRun))).scalars().all() == []
    assert _fichiers_sauvegarde(tmp_path) == []


def test_ca5_aucune_constante_codee_pour_frequence_rpo_retention():
    import app.operator.sauvegarde_chiffree as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(source)
    motif = re.compile(r"FREQUENCE|RPO|RETENTION", re.IGNORECASE)
    for noeud in ast.walk(arbre):
        cibles = []
        if isinstance(noeud, ast.Assign):
            cibles = noeud.targets
            valeur = noeud.value
        elif isinstance(noeud, ast.AnnAssign) and noeud.value is not None:
            cibles = [noeud.target]
            valeur = noeud.value
        else:
            continue
        for cible in cibles:
            nom = cible.id if isinstance(cible, ast.Name) else getattr(cible, "attr", "")
            if motif.search(nom or ""):
                assert not isinstance(valeur, ast.Constant), f"valeur codée pour {nom} : interdit (BE-244 CA-5)"


# Droits : exécution réservée à l'exploitation ; hors allowlist, 403 et aucune sauvegarde.
async def test_refus_403_hors_exploitation(db, cle_maitre, politique, monkeypatch, tmp_path):
    from app.core.errors import AppError
    from app.operator.backup_models import BackupRun
    from app.operator.sauvegarde_chiffree import sauvegarder_chiffree

    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(uuid.uuid4()))
    await db.commit()
    with pytest.raises(AppError) as erreur:
        await sauvegarder_chiffree(db, uuid.uuid4(), tmp_path)
    assert erreur.value.status_code == 403
    await db.commit()
    assert (await db.execute(select(BackupRun))).scalars().all() == []
    assert _fichiers_sauvegarde(tmp_path) == []
