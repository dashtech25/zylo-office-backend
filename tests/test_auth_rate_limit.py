"""Limitation de débit et verrouillage progressif de l'authentification (T-012).

Intention : chaque test vérifie une exigence de docs/plans/taches/T-012 ou de
REV-S-07 (verrou par compte utilisable comme déni de service). Chaque test
utilise une IP propre (en-tête X-Forwarded-For, proxy de confiance simulé) pour
ne pas partager de compteur avec les autres tests de la base de test.
"""

import ipaddress
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.auth import ratelimit
from app.core.config import settings
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
MAUVAIS_MOT_DE_PASSE = "mauvais-mot-de-passe"
SEUIL_COUPLE = 10  # valeur par défaut de AUTH_RATE_LIMIT_MAX_FAILURES_PER_ACCOUNT


def ip_unique() -> str:
    return str(ipaddress.IPv4Address(0x0A000000 | (uuid.uuid4().int & 0xFFFFFF)))


def entetes(ip: str) -> dict:
    return {"X-Forwarded-For": ip}


class Horloge:
    """Horloge contrôlable pour simuler un délai sans attendre."""

    def __init__(self) -> None:
        self.instant = datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        return self.instant

    def avance(self, secondes: int) -> None:
        self.instant += timedelta(seconds=secondes)


@pytest.fixture(autouse=True)
def proxy_de_confiance(monkeypatch):
    # Le client de test arrive depuis 127.0.0.1 : ce proxy est donc de confiance,
    # et X-Forwarded-For désigne le client réel.
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_TRUSTED_PROXIES", ["127.0.0.1"])


@pytest.fixture
def horloge(monkeypatch) -> Horloge:
    h = Horloge()
    monkeypatch.setattr(ratelimit, "maintenant", h)
    return h


async def inscrire(client: AsyncClient, email: str) -> None:
    res = await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Test"})
    assert res.status_code == 201, res.text


async def connecter(client: AsyncClient, email: str, mot_de_passe: str, ip: str):
    return await client.post(
        "/api/v1/auth/login", json={"email": email, "password": mot_de_passe}, headers=entetes(ip)
    )


async def echouer(client: AsyncClient, email: str, ip: str, fois: int) -> None:
    for _ in range(fois):
        res = await connecter(client, email, MAUVAIS_MOT_DE_PASSE, ip)
        assert res.status_code == 401, res.text


# --- Brute force : verrou par couple (IP, compte) ---------------------------------


async def test_brute_force_bloque_le_couple_ip_compte(client: AsyncClient):
    email, ip = unique_email(), ip_unique()
    await inscrire(client, email)

    await echouer(client, email, ip, SEUIL_COUPLE)

    bloque = await connecter(client, email, MAUVAIS_MOT_DE_PASSE, ip)
    assert bloque.status_code == 429
    assert bloque.json()["error"]["code"] == "rate_limited"
    assert int(bloque.headers["Retry-After"]) >= 1

    # Même le bon mot de passe est refusé pendant le verrou : sinon le verrou ne sert à rien.
    assert (await connecter(client, email, MOT_DE_PASSE, ip)).status_code == 429


# --- Compte inconnu : même comportement qu'un compte existant ---------------------


async def test_compte_inconnu_et_mauvais_mot_de_passe_repondent_pareil(client: AsyncClient):
    existant, inconnu, ip = unique_email(), unique_email(), ip_unique()
    await inscrire(client, existant)

    inexistant = await connecter(client, inconnu, MAUVAIS_MOT_DE_PASSE, ip)
    mauvais = await connecter(client, existant, MAUVAIS_MOT_DE_PASSE, ip)

    assert inexistant.status_code == mauvais.status_code == 401
    assert inexistant.json() == mauvais.json()


async def test_verrou_du_compte_inconnu_identique_au_verrou_du_compte_existant(client: AsyncClient):
    # Le verrou se déclenche aussi pour un email inconnu : le 429 ne révèle pas l'existence du compte.
    existant, inconnu, ip = unique_email(), unique_email(), ip_unique()
    await inscrire(client, existant)
    await echouer(client, existant, ip, SEUIL_COUPLE)
    await echouer(client, inconnu, ip, SEUIL_COUPLE)

    verrou_existant = await connecter(client, existant, MAUVAIS_MOT_DE_PASSE, ip)
    verrou_inconnu = await connecter(client, inconnu, MAUVAIS_MOT_DE_PASSE, ip)

    assert verrou_existant.status_code == verrou_inconnu.status_code == 429
    assert verrou_existant.json() == verrou_inconnu.json()


# --- Réinitialisation après délai, backoff ----------------------------------------


async def test_verrou_levé_apres_le_delai_puis_compteur_remis_a_zero(client: AsyncClient, horloge: Horloge):
    email, ip = unique_email(), ip_unique()
    await inscrire(client, email)
    await echouer(client, email, ip, SEUIL_COUPLE)
    assert (await connecter(client, email, MOT_DE_PASSE, ip)).status_code == 429

    horloge.avance(settings.AUTH_RATE_LIMIT_LOCK_BASE_SECONDS + 1)

    assert (await connecter(client, email, MOT_DE_PASSE, ip)).status_code == 200
    # Le succès a remis le compteur à zéro : un nouvel échec ne reproduit pas le verrou.
    assert (await connecter(client, email, MAUVAIS_MOT_DE_PASSE, ip)).status_code == 401


async def test_backoff_double_la_duree_du_verrou(client: AsyncClient, horloge: Horloge):
    email, ip = unique_email(), ip_unique()
    base = settings.AUTH_RATE_LIMIT_LOCK_BASE_SECONDS
    await inscrire(client, email)
    await echouer(client, email, ip, SEUIL_COUPLE)

    horloge.avance(base + 1)
    # 11e échec : le verrou suivant dure deux fois plus longtemps.
    assert (await connecter(client, email, MAUVAIS_MOT_DE_PASSE, ip)).status_code == 401
    horloge.avance(base + 1)
    assert (await connecter(client, email, MOT_DE_PASSE, ip)).status_code == 429
    horloge.avance(base)
    assert (await connecter(client, email, MOT_DE_PASSE, ip)).status_code == 200


# --- Isolation entre IP : un verrou ne touche pas une autre IP (REV-S-07) ---------


async def test_attaque_depuis_ip_a_ne_verrouille_pas_le_compte_pour_ip_b(client: AsyncClient):
    email, ip_a, ip_b = unique_email(), ip_unique(), ip_unique()
    await inscrire(client, email)
    await echouer(client, email, ip_a, SEUIL_COUPLE)
    assert (await connecter(client, email, MOT_DE_PASSE, ip_a)).status_code == 429

    legitime = await connecter(client, email, MOT_DE_PASSE, ip_b)
    assert legitime.status_code == 200


async def test_ip_qui_depasse_la_limite_globale_recoit_429_les_autres_non(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_MAX_FAILURES_PER_IP", 5)
    email, ip_a, ip_b = unique_email(), ip_unique(), ip_unique()
    await inscrire(client, email)
    for _ in range(5):
        await connecter(client, unique_email(), MAUVAIS_MOT_DE_PASSE, ip_a)

    # IP A est bloquée pour tous les comptes, y compris le sien avec le bon mot de passe.
    assert (await connecter(client, email, MOT_DE_PASSE, ip_a)).status_code == 429
    # IP B n'est pas touchée.
    assert (await connecter(client, email, MOT_DE_PASSE, ip_b)).status_code == 200


# --- IP déjà connue du titulaire : pas de verrou par couple -----------------------


async def test_ip_deja_connue_du_titulaire_ne_subit_pas_le_verrou_par_couple(client: AsyncClient):
    email, ip = unique_email(), ip_unique()
    await inscrire(client, email)
    assert (await connecter(client, email, MOT_DE_PASSE, ip)).status_code == 200

    await echouer(client, email, ip, SEUIL_COUPLE + 2)

    # Le titulaire, depuis son IP habituelle, n'est pas verrouillé.
    assert (await connecter(client, email, MOT_DE_PASSE, ip)).status_code == 200


# --- Refresh : limite par IP -------------------------------------------------------


async def test_refresh_limite_par_ip_sans_toucher_au_login(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_MAX_FAILURES_PER_IP", 3)
    email, ip = unique_email(), ip_unique()
    await inscrire(client, email)
    for _ in range(3):
        res = await client.post("/api/v1/auth/refresh", json={"refreshToken": "jeton-invalide"}, headers=entetes(ip))
        assert res.status_code == 401

    bloque = await client.post("/api/v1/auth/refresh", json={"refreshToken": "jeton-invalide"}, headers=entetes(ip))
    assert bloque.status_code == 429
    # La limite de refresh est indépendante de celle du login.
    assert (await connecter(client, email, MOT_DE_PASSE, ip)).status_code == 200


# --- Register : les doublons comptent comme échecs --------------------------------


async def test_inscriptions_repetees_sur_un_email_existant_sont_limitees(client: AsyncClient):
    email, ip = unique_email(), ip_unique()
    payload = {"email": email, "password": MOT_DE_PASSE, "fullName": "Doublon"}
    await client.post("/api/v1/auth/register", json=payload, headers=entetes(ip))
    for _ in range(SEUIL_COUPLE):
        res = await client.post("/api/v1/auth/register", json=payload, headers=entetes(ip))
        assert res.status_code == 409

    assert (await client.post("/api/v1/auth/register", json=payload, headers=entetes(ip))).status_code == 429


# --- IP spoofée : X-Forwarded-For ignoré hors proxy de confiance ------------------


async def test_x_forwarded_for_ignore_si_le_pair_n_est_pas_de_confiance(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_TRUSTED_PROXIES", [])
    email = unique_email()
    await inscrire(client, email)
    for _ in range(SEUIL_COUPLE):
        # Chaque tentative prétend venir d'une autre IP : le pair réel (127.0.0.1) reste le même.
        res = await connecter(client, email, MAUVAIS_MOT_DE_PASSE, ip_unique())
        assert res.status_code == 401

    assert (await connecter(client, email, MOT_DE_PASSE, ip_unique())).status_code == 429


# --- Désactivation par configuration (retour arrière) -----------------------------


async def test_limite_desactivee_par_configuration(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_ENABLED", False)
    email, ip = unique_email(), ip_unique()
    await inscrire(client, email)
    for _ in range(SEUIL_COUPLE + 2):
        assert (await connecter(client, email, MAUVAIS_MOT_DE_PASSE, ip)).status_code == 401


# --- Journal de sécurité : événements sans mot de passe ---------------------------


async def test_journal_securite_trace_echecs_et_verrou_sans_mot_de_passe(client: AsyncClient, caplog):
    email, ip = unique_email(), ip_unique()
    await inscrire(client, email)
    caplog.set_level(logging.WARNING, logger="zylo_office.security")

    await echouer(client, email, ip, SEUIL_COUPLE)
    assert (await connecter(client, email, MAUVAIS_MOT_DE_PASSE, ip)).status_code == 429

    messages = [r.getMessage() for r in caplog.records if r.name == "zylo_office.security"]
    assert "auth_failure" in messages
    assert "auth_rate_limited" in messages
    texte = " ".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    assert MAUVAIS_MOT_DE_PASSE not in texte
    assert email not in texte
