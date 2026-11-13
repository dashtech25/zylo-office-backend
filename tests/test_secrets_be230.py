"""Tests BE-230 : inventaire des secrets, injection, rotation et révocation.

Couvre les critères CA-1 à CA-4 de la définition (implementation-backend/
tasks-exploitation-architecture.md, section BE-230). Les noms nouveaux sont
importés à l'intérieur de chaque fonction : chaque test échoue donc pour sa
seule raison, sans faire échouer la collecte du module.
"""

import datetime as dt
import logging
import os
import re
import subprocess
import uuid
from types import SimpleNamespace

import pytest

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VALEUR_V1 = "rotation-valeur-v1-0123456789abcdef0123"
VALEUR_V2 = "rotation-valeur-v2-fedcba9876543210fedcba"
MESSAGE = b"credential-be230"

# Motifs de secrets réels interdits dans le dépôt versionné.
MOTIFS_SECRETS = [
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(JWT_SECRET|SECRET_KEY|PASSWORD|ENCRYPTION_KEY|SIGNED_URL_SECRET)[ \t]*[=:][ \t]*[\"']?([A-Za-z0-9+/=\-]{24,})"),
]
# Valeurs publiques de repli documentées (core/config.py) : admises par design,
# jamais utilisables hors développement (refus au démarrage, BE-221).
VALEURS_PUBLIQUES_DOCUMENTEES = {"changeme-generate-a-real-random-secret", "changeme"}


@pytest.fixture
async def db():
    from sqlalchemy import delete

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.operator.secrets_models import SecretRegistry

    # Moteur propre à chaque test (NullPool) : le moteur partagé de l'application
    # garde des connexions liées à une autre boucle d'événements pytest-asyncio.
    moteur = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        async with async_sessionmaker(bind=moteur, expire_on_commit=False)() as session:
            # Registre vidé : le contrôle de démarrage lit toutes les lignes obligatoires.
            await session.execute(delete(SecretRegistry))
            await session.commit()
            yield session
            await session.rollback()
            await session.execute(delete(SecretRegistry))
            await session.commit()
    finally:
        await moteur.dispose()


async def _inserer_secret(db, nom: str, *, obligatoire: bool, expire_le=None):
    from app.operator.secrets_models import SecretRegistry

    ligne = SecretRegistry(
        name=nom,
        owner="exploitation",
        scope="environment",
        expiresAt=expire_le,
        lastRotatedAt=None,
        consumer="tests.be230",
        required=obligatoire,
    )
    db.add(ligne)
    await db.commit()
    return ligne


# CA-1 : aucune valeur de secret dans le dépôt ni dans les journaux ; test de scan.
def test_ca1_registre_ne_contient_aucune_colonne_de_valeur():
    from app.operator.secrets_models import SecretRegistry

    colonnes = set(SecretRegistry.__table__.columns.keys())
    assert "secret_registry" == SecretRegistry.__tablename__
    assert not colonnes & {"value", "valeur", "secret", "secret_value", "password"}


def test_ca1_aucun_secret_versionne_dans_le_depot():
    fichiers = subprocess.run(
        ["git", "ls-files"], cwd=BACKEND_ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    trouvailles = []
    for chemin in fichiers:
        if chemin.endswith((".png", ".jpg", ".pdf", ".xlsx", ".docx", ".zip", ".woff2")):
            continue
        try:
            with open(os.path.join(BACKEND_ROOT, chemin), encoding="utf-8") as fichier:
                contenu = fichier.read()
        except (UnicodeDecodeError, OSError):
            continue
        for motif in MOTIFS_SECRETS:
            for correspondance in motif.finditer(contenu):
                valeur = correspondance.group(correspondance.lastindex or 0)
                if valeur in VALEURS_PUBLIQUES_DOCUMENTEES or "changeme" in valeur or "test-only" in valeur:
                    continue
                trouvailles.append(f"{chemin}: {correspondance.group(0)[:40]}")
    assert trouvailles == [], f"valeurs de secret trouvées dans le dépôt : {trouvailles}"


async def test_ca1_rotation_ne_journalise_pas_la_valeur(db, caplog):
    from app.core.secrets import SecretStore
    from app.operator.secrets_service import enregistrer_rotation

    await _inserer_secret(db, "BE230_JOURNAL", obligatoire=True)
    store = SecretStore({"BE230_JOURNAL": VALEUR_V1})
    with caplog.at_level(logging.DEBUG):
        await enregistrer_rotation(db, store, "BE230_JOURNAL", VALEUR_V2, dt.datetime.now(dt.timezone.utc))
    assert VALEUR_V1 not in caplog.text
    assert VALEUR_V2 not in caplog.text


# CA-2 : une rotation rend l'ancien credential inopérant et le nouveau opérant ; test de rotation.
async def test_ca2_rotation_invalide_l_ancien_credential_et_valide_le_nouveau(db):
    from app.core.secrets import SecretStore
    from app.operator.secrets_service import enregistrer_rotation

    await _inserer_secret(db, "BE230_ROTATION", obligatoire=True)
    store = SecretStore({"BE230_ROTATION": VALEUR_V1})
    ancien = store.signe("BE230_ROTATION", MESSAGE)
    assert store.signature_valide("BE230_ROTATION", MESSAGE, ancien)

    maintenant = dt.datetime.now(dt.timezone.utc)
    await enregistrer_rotation(db, store, "BE230_ROTATION", VALEUR_V2, maintenant)
    await db.commit()

    assert not store.signature_valide("BE230_ROTATION", MESSAGE, ancien)
    nouveau = store.signe("BE230_ROTATION", MESSAGE)
    assert store.signature_valide("BE230_ROTATION", MESSAGE, nouveau)

    from app.operator.secrets_models import SecretRegistry
    from sqlalchemy import select

    ligne = (await db.execute(select(SecretRegistry).where(SecretRegistry.name == "BE230_ROTATION"))).scalar_one()
    assert ligne.lastRotatedAt is not None


# CA-3 : un secret obligatoire expiré fait échouer le démarrage (échec fermé) ; test.
async def test_ca3_secret_obligatoire_expire_fait_echouer_le_demarrage(db):
    from app.core.config import ConfigurationSecretError
    from app.core.secrets import SecretStore
    from app.operator.secrets_service import controle_secrets_au_demarrage

    maintenant = dt.datetime.now(dt.timezone.utc)
    await _inserer_secret(
        db, "BE230_EXPIRE", obligatoire=True, expire_le=maintenant - dt.timedelta(days=1)
    )
    store = SecretStore({"BE230_EXPIRE": VALEUR_V1})
    with pytest.raises(ConfigurationSecretError) as erreur:
        await controle_secrets_au_demarrage(db, store, maintenant)
    assert "BE230_EXPIRE" in str(erreur.value)
    assert VALEUR_V1 not in str(erreur.value)


async def test_ca3_secret_obligatoire_valide_laisse_demarrer(db):
    from app.core.secrets import SecretStore
    from app.operator.secrets_service import controle_secrets_au_demarrage

    maintenant = dt.datetime.now(dt.timezone.utc)
    await _inserer_secret(
        db, "BE230_VALIDE", obligatoire=True, expire_le=maintenant + dt.timedelta(days=30)
    )
    store = SecretStore({"BE230_VALIDE": VALEUR_V1})
    await controle_secrets_au_demarrage(db, store, maintenant)


# CA-4 : un accès au registre sans droit donne 403 ; test de refus.
async def test_ca4_acces_registre_sans_droit_donne_403(db, monkeypatch):
    from app.core.errors import AppError
    from app.operator.secrets_service import lire_registre

    await _inserer_secret(db, "BE230_REFUS", obligatoire=False)
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(uuid.uuid4()))
    utilisateur_sans_droit = SimpleNamespace(id=uuid.uuid4())
    with pytest.raises(AppError) as erreur:
        await lire_registre(db, utilisateur_sans_droit)
    assert erreur.value.status_code == 403


async def test_ca4_acces_registre_exploitation_autorise(db, monkeypatch):
    from app.operator.secrets_service import lire_registre

    await _inserer_secret(db, "BE230_LECTURE", obligatoire=False)
    operateur = uuid.uuid4()
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", str(operateur))
    lignes = await lire_registre(db, SimpleNamespace(id=operateur))
    assert [ligne.name for ligne in lignes] == ["BE230_LECTURE"]
