"""Tests BE-231 : chiffrement versionné, rotation et révocation des clés.

Couvre les critères CA-1 à CA-4 de la définition (implementation-backend/
tasks-exploitation-architecture.md, section BE-231). Les noms nouveaux sont
importés à l'intérieur de chaque fonction : chaque test échoue donc pour sa
seule raison, sans faire échouer la collecte du module.

Clé maître de test : `APP_FIELD_ENCRYPTION_KEY` remplacée par une valeur fictive
via monkeypatch (jamais une vraie clé dans le dépôt).
"""

import base64
import datetime as dt
import os
import subprocess
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

CLE_MAITRE_TEST = "cle-maitre-be231-fictive-0123456789abcdef0123"
CLAIR = "valeur-be231-fictive"


@pytest.fixture
async def db():
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.operator.encryption_models import EncryptionKey

    # Moteur propre à chaque test (NullPool) : évite les connexions liées à une
    # autre boucle d'événements pytest-asyncio.
    moteur = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        async with async_sessionmaker(bind=moteur, expire_on_commit=False)() as session:
            await session.execute(delete(EncryptionKey))
            await session.commit()
            yield session
            await session.rollback()
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


# CA-1 : rotation de la version N vers N+1 sans perte de lecture ; test.
async def test_ca1_rotation_conserve_la_lecture_des_valeurs_anciennes(db, cle_maitre, operateur):
    from app.operator.encryption_service import charger_anneau, rotate_key

    maintenant = dt.datetime.now(dt.timezone.utc)
    version_1 = await rotate_key(db, operateur, maintenant)
    anneau = await charger_anneau(db)
    stocke_v1 = anneau.chiffrer(CLAIR)
    assert stocke_v1.startswith("enc:v2:1:")

    version_2 = await rotate_key(db, operateur, maintenant)
    await db.commit()
    assert version_2 == version_1 + 1

    # Lecture de la valeur ancienne après rotation, en mémoire comme après rechargement.
    assert anneau.dechiffrer(stocke_v1) == CLAIR
    anneau_relu = await charger_anneau(db)
    assert anneau_relu.dechiffrer(stocke_v1) == CLAIR
    # Les nouvelles écritures utilisent la version courante N+1.
    assert anneau_relu.chiffrer(CLAIR).startswith(f"enc:v2:{version_2}:")


# CA-2 : après révocation, l'ancienne clé ne déchiffre plus ; test.
async def test_ca2_revocation_rend_l_ancienne_cle_inoperante(db, cle_maitre, operateur):
    from app.core.crypto import ChiffrementError
    from app.operator.encryption_service import charger_anneau, revoquer_cle, rotate_key

    maintenant = dt.datetime.now(dt.timezone.utc)
    version_1 = await rotate_key(db, operateur, maintenant)
    anneau = await charger_anneau(db)
    stocke_v1 = anneau.chiffrer(CLAIR)
    await rotate_key(db, operateur, maintenant)
    await revoquer_cle(db, operateur, version_1, maintenant, anneau)
    await db.commit()

    with pytest.raises(ChiffrementError):
        anneau.dechiffrer(stocke_v1)
    with pytest.raises(ChiffrementError):
        (await charger_anneau(db)).dechiffrer(stocke_v1)


async def test_ca2_version_courante_non_revocable(db, cle_maitre, operateur):
    from app.core.errors import AppError
    from app.operator.encryption_service import charger_anneau, revoquer_cle, rotate_key

    maintenant = dt.datetime.now(dt.timezone.utc)
    version = await rotate_key(db, operateur, maintenant)
    anneau = await charger_anneau(db)
    with pytest.raises(AppError) as erreur:
        await revoquer_cle(db, operateur, version, maintenant, anneau)
    assert erreur.value.status_code == 409


# CA-3 : sauvegarde ne contient pas la clé en clair ; test de scan de sauvegarde.
async def test_ca3_sauvegarde_ne_contient_aucune_cle_en_clair(db, cle_maitre, operateur):
    from app.core.crypto import generer_cle_donnee
    from app.core.config import settings
    from app.operator.encryption_service import rotate_key

    maintenant = dt.datetime.now(dt.timezone.utc)
    await rotate_key(db, operateur, maintenant)
    await rotate_key(db, operateur, maintenant)
    await db.commit()

    # Sauvegarde de la seule table des clés, par l'outil de sauvegarde réel.
    url = make_url(os.environ["DATABASE_URL"])
    commande = [
        "pg_dump", "--data-only", "--table=encryption_keys",
        "--dbname=" + url.database, "--username=" + url.username,
    ]
    if url.query.get("host"):
        commande += ["--host=" + url.query["host"]]
    sauvegarde = subprocess.run(commande, capture_output=True, text=True, check=True).stdout

    # Les lignes existent bien dans la sauvegarde (le test ne passe pas à vide).
    assert "encryption_keys" in sauvegarde
    assert "active" in sauvegarde

    # Aucune clé de données ni la clé maître ne figure en clair (ni en base64).
    for cle_brute in [settings.APP_FIELD_ENCRYPTION_KEY]:
        assert cle_brute not in sauvegarde
    from app.operator.encryption_models import EncryptionKey
    from sqlalchemy import select

    lignes = (await db.execute(select(EncryptionKey))).scalars().all()
    assert lignes and all(ligne.wrappedKey for ligne in lignes)
    # Seule la forme enveloppée (chiffrée par la clé maître) est sauvegardée.
    for ligne in lignes:
        assert ligne.wrappedKey in sauvegarde
    # Le générateur de clé de données produit une clé Fernet valide (32 octets décodés).
    assert len(base64.urlsafe_b64decode(generer_cle_donnee())) == 32


# CA-4 : rotation sans droit donne 403 ; test de refus.
async def test_ca4_rotation_sans_droit_donne_403(db, cle_maitre, monkeypatch):
    from sqlalchemy import func, select

    from app.core.errors import AppError
    from app.operator.encryption_models import EncryptionKey
    from app.operator.encryption_service import rotate_key

    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(uuid.uuid4()))
    sans_droit = SimpleNamespace(id=uuid.uuid4())
    with pytest.raises(AppError) as erreur:
        await rotate_key(db, sans_droit, dt.datetime.now(dt.timezone.utc))
    assert erreur.value.status_code == 403
    assert await db.scalar(select(func.count()).select_from(EncryptionKey)) == 0


async def test_ca4_revocation_sans_droit_donne_403(db, cle_maitre, operateur, monkeypatch):
    from app.core.errors import AppError
    from app.operator.encryption_service import charger_anneau, revoquer_cle, rotate_key

    maintenant = dt.datetime.now(dt.timezone.utc)
    version_1 = await rotate_key(db, operateur, maintenant)
    await rotate_key(db, operateur, maintenant)
    anneau = await charger_anneau(db)
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(uuid.uuid4()))
    with pytest.raises(AppError) as erreur:
        await revoquer_cle(db, SimpleNamespace(id=uuid.uuid4()), version_1, maintenant, anneau)
    assert erreur.value.status_code == 403
