"""Chiffrement applicatif du mot de passe du compte Holykell (T-027).

Intention : le mot de passe ne doit jamais apparaître en clair dans la base
pour les nouvelles écritures, jamais dans une réponse API, jamais dans les
journaux. Il n'est déchiffré que dans la boucle de synchronisation. Les valeurs
en clair déjà présentes restent lisibles pendant la transition.

Les valeurs de test sont fictives et propres à ce fichier.
"""

import importlib.util
import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import field_crypto
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.integrations.holykell import client as holykell_client
from app.modules.zylo_liquid import telemetry_sync
from app.modules.zylo_liquid.models import HolykellAccount

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOT_DE_PASSE_FICTIF = "mdp-fictif-Xq7-holykell-test"
CLE_FICTIVE = "cle-fictive-chiffrement-" + "0123456789abcdef" * 2


@pytest.fixture
def cle_de_test(monkeypatch):
    monkeypatch.setattr(settings, "APP_FIELD_ENCRYPTION_KEY", CLE_FICTIVE)
    return CLE_FICTIVE


@pytest.fixture(autouse=True)
async def retire_les_comptes_chiffres():
    """Chaque test de ce module chiffre avec une clé qui lui est propre (CLE_FICTIVE, « autre-cle », ou
    aucune). Ses comptes sont retirés à la fin du test : sinon le downgrade de T-027, lancé plus tard dans
    la session (tests/test_rbac_module_roles.py, aller-retour de migration), ne peut pas déchiffrer ces
    lignes avec la clé de l'environnement de test, et échoue. Cet échec est le comportement voulu de la
    migration (elle refuse de perdre une valeur)."""
    yield
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.execute(text('DELETE FROM "zyloLiquidHolykellAccount" WHERE "holykellPasswordChiffre" IS NOT NULL'))
    finally:
        await engine.dispose()


def _charger_script_migration():
    chemin = os.path.join(BACKEND_ROOT, "scripts", "chiffrer_mots_de_passe_holykell.py")
    spec = importlib.util.spec_from_file_location("chiffrer_mots_de_passe_holykell", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- crypto pure

def test_aller_retour_et_valeur_chiffree_differente(cle_de_test):
    chiffre = field_crypto.chiffrer(MOT_DE_PASSE_FICTIF)
    assert chiffre != MOT_DE_PASSE_FICTIF
    assert MOT_DE_PASSE_FICTIF not in chiffre
    assert chiffre.startswith(field_crypto.PREFIXE_CHIFFRE)
    assert field_crypto.dechiffrer(chiffre) == MOT_DE_PASSE_FICTIF


def test_chiffrement_non_deterministe(cle_de_test):
    # Fernet inclut un sel aléatoire : deux chiffrements du même clair diffèrent.
    assert field_crypto.chiffrer(MOT_DE_PASSE_FICTIF) != field_crypto.chiffrer(MOT_DE_PASSE_FICTIF)


def test_valeur_altérée_refusee(cle_de_test):
    chiffre = field_crypto.chiffrer(MOT_DE_PASSE_FICTIF)
    altere = chiffre[:-4] + ("AAAA" if chiffre[-4:] != "AAAA" else "BBBB")
    with pytest.raises(field_crypto.ChiffrementError):
        field_crypto.dechiffrer(altere)


def test_cle_differente_refusee(monkeypatch):
    monkeypatch.setattr(settings, "APP_FIELD_ENCRYPTION_KEY", CLE_FICTIVE)
    chiffre = field_crypto.chiffrer(MOT_DE_PASSE_FICTIF)
    monkeypatch.setattr(settings, "APP_FIELD_ENCRYPTION_KEY", "autre-cle-fictive-" + "fedcba9876543210" * 2)
    with pytest.raises(field_crypto.ChiffrementError) as info:
        field_crypto.dechiffrer(chiffre)
    assert MOT_DE_PASSE_FICTIF not in str(info.value)


@pytest.mark.parametrize("cle", ["", "trop-court"])
def test_cle_absente_ou_invalide_refusee_sans_fuite(monkeypatch, cle):
    monkeypatch.setattr(settings, "APP_FIELD_ENCRYPTION_KEY", cle)
    with pytest.raises(field_crypto.ChiffrementError) as info:
        field_crypto.chiffrer(MOT_DE_PASSE_FICTIF)
    message = str(info.value)
    assert "APP_FIELD_ENCRYPTION_KEY" in message
    assert MOT_DE_PASSE_FICTIF not in message
    if cle:
        assert cle not in message


def test_dechiffrer_refuse_une_valeur_non_chiffree(cle_de_test):
    with pytest.raises(field_crypto.ChiffrementError):
        field_crypto.dechiffrer(MOT_DE_PASSE_FICTIF)


def test_lire_champ_prefere_le_chiffre_et_accepte_le_clair_legacy(cle_de_test):
    chiffre = field_crypto.chiffrer(MOT_DE_PASSE_FICTIF)
    assert field_crypto.lire_champ(chiffre, None) == MOT_DE_PASSE_FICTIF
    # Transition : ligne non migrée, seule la colonne en clair est renseignée.
    assert field_crypto.lire_champ(None, MOT_DE_PASSE_FICTIF) == MOT_DE_PASSE_FICTIF
    with pytest.raises(field_crypto.ChiffrementError):
        field_crypto.lire_champ(None, None)


# ---------------------------------------------------------- base et API

async def _creer_compte(organization_id: str, chiffre: str | None, clair: str | None) -> HolykellAccount:
    async with AsyncSessionLocal() as db:
        account = HolykellAccount(
            organizationId=uuid.UUID(organization_id),
            holykellUsername="fictif-chiffrement",
            holykellPassword=clair,
            holykellPasswordChiffre=chiffre,
            lastSyncStatus="failed",
            lastSyncError="Timeout de test",
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        return account


async def test_nouvelle_ecriture_ne_stocke_jamais_le_clair(cle_de_test, zylo_liquid_organization: dict):
    account = await _creer_compte(
        zylo_liquid_organization["id"], field_crypto.chiffrer(MOT_DE_PASSE_FICTIF), None
    )
    async with AsyncSessionLocal() as db:
        relu = (await db.execute(select(HolykellAccount).where(HolykellAccount.id == account.id))).scalar_one()
    assert relu.holykellPassword is None
    assert MOT_DE_PASSE_FICTIF not in relu.holykellPasswordChiffre


async def test_api_ne_renvoie_ni_clair_ni_chiffre(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, cle_de_test
):
    chiffre = field_crypto.chiffrer(MOT_DE_PASSE_FICTIF)
    account = await _creer_compte(zylo_liquid_organization["id"], chiffre, MOT_DE_PASSE_FICTIF)
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": zylo_liquid_organization["id"]}

    reponses = [
        await client.get(f"/api/v1/zylo-liquid/holykell-accounts/{account.id}/sync-status", headers=headers),
        await client.get("/api/v1/zylo-liquid/holykell-accounts", headers=headers),
    ]
    for res in reponses:
        assert res.status_code == 200
        assert MOT_DE_PASSE_FICTIF not in res.text
        assert chiffre not in res.text
        assert "holykellPassword" not in res.text
        assert "holykellPasswordChiffre" not in res.text


async def test_synchro_transmet_le_clair_dechiffre_au_mock(
    monkeypatch, cle_de_test, zylo_liquid_organization: dict
):
    account = await _creer_compte(zylo_liquid_organization["id"], field_crypto.chiffrer(MOT_DE_PASSE_FICTIF), None)
    recus = {}

    async def faux_login(_client, _base_url, username, password):
        recus["username"], recus["password"] = username, password
        return "jeton-fictif", "tenant-fictif"

    async def fausses_lectures(_client, _base_url, _token, _tenant):
        return []

    monkeypatch.setattr(holykell_client, "login", faux_login)
    monkeypatch.setattr(holykell_client, "fetch_sensor_readings", fausses_lectures)

    async with AsyncSessionLocal() as db, httpx.AsyncClient() as http:
        account = await db.get(HolykellAccount, account.id)
        await telemetry_sync.sync_one_account(db, http, "http://simulateur.invalide", account)

    assert recus["password"] == MOT_DE_PASSE_FICTIF
    assert account.lastSyncStatus == "success"


async def test_synchro_sans_fuite_dans_les_journaux(
    monkeypatch, caplog, cle_de_test, zylo_liquid_organization: dict
):
    account = await _creer_compte(
        zylo_liquid_organization["id"], field_crypto.chiffrer(MOT_DE_PASSE_FICTIF), None
    )

    async def login_refuse(_client, _base_url, username, _password):
        raise holykell_client.HolykellAuthError(f"Login Holykell refusé pour {username!r} : HTTP 401")

    monkeypatch.setattr(holykell_client, "login", login_refuse)
    caplog.set_level(logging.DEBUG)

    async with AsyncSessionLocal() as db, httpx.AsyncClient() as http:
        account = await db.get(HolykellAccount, account.id)
        await telemetry_sync.sync_one_account(db, http, "http://simulateur.invalide", account)

    assert account.lastSyncStatus == "failed"
    assert MOT_DE_PASSE_FICTIF not in caplog.text
    assert MOT_DE_PASSE_FICTIF not in (account.lastSyncError or "")


async def test_synchro_sans_cle_echoue_proprement(monkeypatch, zylo_liquid_organization: dict):
    # Valeur chiffrée présente mais clé absente : la synchro échoue, sans fuite.
    monkeypatch.setattr(settings, "APP_FIELD_ENCRYPTION_KEY", "")
    account = await _creer_compte(zylo_liquid_organization["id"], "enc:v1:jeton-fictif", None)

    async with AsyncSessionLocal() as db, httpx.AsyncClient() as http:
        account = await db.get(HolykellAccount, account.id)
        await telemetry_sync.sync_one_account(db, http, "http://simulateur.invalide", account)

    assert account.lastSyncStatus == "failed"
    assert MOT_DE_PASSE_FICTIF not in (account.lastSyncError or "")


# ---------------------------------------------------- migration des données

async def test_migration_dry_run_n_ecrit_rien(cle_de_test, zylo_liquid_organization: dict):
    script = _charger_script_migration()
    account = await _creer_compte(zylo_liquid_organization["id"], None, MOT_DE_PASSE_FICTIF)

    rapport = await script.migrer(AsyncSessionLocal, dry_run=True, effacer_clair=False, lot=10)

    assert rapport.chiffres >= 1
    async with AsyncSessionLocal() as db:
        relu = await db.get(HolykellAccount, account.id)
    assert relu.holykellPasswordChiffre is None
    assert relu.holykellPassword == MOT_DE_PASSE_FICTIF


async def test_migration_chiffre_les_valeurs_existantes_et_est_idempotente(
    cle_de_test, zylo_liquid_organization: dict
):
    script = _charger_script_migration()
    account = await _creer_compte(zylo_liquid_organization["id"], None, MOT_DE_PASSE_FICTIF)

    premier = await script.migrer(AsyncSessionLocal, dry_run=False, effacer_clair=False, lot=10)
    assert premier.chiffres >= 1
    async with AsyncSessionLocal() as db:
        relu = await db.get(HolykellAccount, account.id)
    assert field_crypto.dechiffrer(relu.holykellPasswordChiffre) == MOT_DE_PASSE_FICTIF
    # Sans --effacer-clair, la colonne en clair reste (retour arrière possible).
    assert relu.holykellPassword == MOT_DE_PASSE_FICTIF

    second = await script.migrer(AsyncSessionLocal, dry_run=False, effacer_clair=False, lot=10)
    assert second.chiffres == 0
    async with AsyncSessionLocal() as db:
        encore = await db.get(HolykellAccount, account.id)
    assert encore.holykellPasswordChiffre == relu.holykellPasswordChiffre


async def test_migration_effacer_clair_apres_verification(cle_de_test, zylo_liquid_organization: dict):
    script = _charger_script_migration()
    account = await _creer_compte(zylo_liquid_organization["id"], None, MOT_DE_PASSE_FICTIF)

    rapport = await script.migrer(AsyncSessionLocal, dry_run=False, effacer_clair=True, lot=10)

    assert rapport.clairs_effaces >= 1
    async with AsyncSessionLocal() as db:
        relu = await db.get(HolykellAccount, account.id)
    assert relu.holykellPassword is None
    assert field_crypto.dechiffrer(relu.holykellPasswordChiffre) == MOT_DE_PASSE_FICTIF


async def test_migration_sans_cle_ne_modifie_rien(monkeypatch, zylo_liquid_organization: dict):
    script = _charger_script_migration()
    account = await _creer_compte(zylo_liquid_organization["id"], None, MOT_DE_PASSE_FICTIF)
    monkeypatch.setattr(settings, "APP_FIELD_ENCRYPTION_KEY", "")

    with pytest.raises(field_crypto.ChiffrementError):
        await script.migrer(AsyncSessionLocal, dry_run=False, effacer_clair=False, lot=10)

    async with AsyncSessionLocal() as db:
        relu = await db.get(HolykellAccount, account.id)
    assert relu.holykellPasswordChiffre is None
    assert relu.holykellPassword == MOT_DE_PASSE_FICTIF
