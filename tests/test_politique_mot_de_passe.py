"""Politique de mot de passe centralisée (T-013, BCK-005, IAM-024).

Une seule règle, dans app/auth/politique_mot_de_passe.py, appliquée à :
inscription, activation de compte (T-021/T-049), changement de mot de passe,
et mot de passe temporaire du personnel de station.

Règles testées :
- 12 caractères minimum (comptés en caractères, pas en octets) ;
- 72 octets UTF-8 maximum (limite de bcrypt : au-delà, troncature silencieuse) ;
- liste locale de mots de passe courants, comparée sans tenir compte de la casse ;
- ni adresse e-mail ni nom de la personne (fragments significatifs seulement) ;
- aucune règle de composition (majuscules, chiffres, symboles non exigés) ;
- un mot de passe fait d'un seul caractère répété est refusé ;
- messages explicites ; l'e-mail est normalisé en minuscules ;
- mustChangePassword est appliqué côté backend : jeton d'accès restreint ;
- le changement de mot de passe révoque les refresh tokens (autres sessions) ;
- un mot de passe refusé à l'activation ne consomme pas le jeton.
"""

import re
import secrets
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.models import RefreshToken
from app.auth.politique_mot_de_passe import (
    LONGUEUR_MAXIMALE_OCTETS,
    LONGUEUR_MINIMALE,
    MOTS_DE_PASSE_COURANTS,
    PolitiqueMotDePasseErreur,
    raisons_mot_de_passe,
    verifie_mot_de_passe,
)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.identity.models import OrganizationUser, User
from app.shared.email import memory_outbox
from tests.conftest import unique_email

MOT_DE_PASSE_VALIDE = "Lune-Verte-2026"
URL_REGISTER = "/api/v1/auth/register"
URL_LOGIN = "/api/v1/auth/login"
URL_CHANGEMENT = "/api/v1/auth/change-password"
URL_ME = "/api/v1/auth/me"
URL_REFRESH = "/api/v1/auth/refresh"
URL_ACTIVATION = "/api/v1/auth/activate"
URL_ORGANISATIONS = "/api/v1/organizations"
URL_CREATION = "/api/v1/organizations/{org}/users"
REGEX_JETON = re.compile(r"#token=([A-Za-z0-9_\-]+)")


# ---------------------------------------------------------------------------
# Unitaires : le module seul, sans base
# ---------------------------------------------------------------------------


def test_longueur_minimale_est_12():
    assert LONGUEUR_MINIMALE == 12


def test_chaque_mot_courant_depasse_la_longueur_minimale():
    # Une entrée plus courte serait refusée par la longueur avant d'être comparée :
    # elle serait inutile, et signalerait une erreur de saisie dans la liste.
    assert MOTS_DE_PASSE_COURANTS
    assert all(len(mot) >= LONGUEUR_MINIMALE for mot in MOTS_DE_PASSE_COURANTS)


def test_mot_de_passe_de_11_caracteres_est_refuse_avec_message_explicite():
    with pytest.raises(PolitiqueMotDePasseErreur) as erreur:
        verifie_mot_de_passe("Lune-Verte2")  # 11 caractères
    assert any("12 caractères" in raison for raison in erreur.value.raisons)


def test_mot_de_passe_de_12_caracteres_est_accepte():
    verifie_mot_de_passe("Lune-Verte-2")  # 12 caractères, sans chiffre ni majuscule exigés
    assert raisons_mot_de_passe("Lune-Verte-2") == []


def test_aucune_regle_de_composition_pour_une_phrase_sans_chiffre_ni_symbole():
    assert raisons_mot_de_passe("une phrase de passe sans chiffre") == []
    assert raisons_mot_de_passe("abcdefghijklmnop") == []


def test_longueur_comptee_en_caracteres_et_non_en_octets():
    # 12 caractères accentués = 22 octets : accepté (NIST compte des caractères).
    assert raisons_mot_de_passe("éèàùçêâôîû12") == []


def test_limite_de_72_octets_utf8_refuse_le_depassement_explicitement():
    assert LONGUEUR_MAXIMALE_OCTETS == 72
    assert raisons_mot_de_passe(("ab-cd-ef-gh-" * 6)) == []  # 72 caractères ASCII = 72 octets
    raisons = raisons_mot_de_passe(("éàüöïçñ" * 6)[:37])  # 37 caractères accentués = 74 octets
    assert any("72 octets" in raison for raison in raisons)


@pytest.mark.parametrize("candidat", ["motdepasse1234", "MotDePasse1234", "password1234", "azerty123456"])
def test_mot_de_passe_courant_est_refuse_quelle_que_soit_la_casse(candidat):
    raisons = raisons_mot_de_passe(candidat)
    assert any("courants" in raison for raison in raisons)


def test_adresse_email_dans_le_mot_de_passe_est_refusee():
    raisons = raisons_mot_de_passe("jean.dupont@exemple.fr", email="jean.dupont@exemple.fr")
    assert raisons


def test_partie_locale_de_l_email_dans_le_mot_de_passe_est_refusee():
    raisons = raisons_mot_de_passe("mon-jean.dupont-2026", email="Jean.Dupont@exemple.fr")
    assert any("e-mail" in raison for raison in raisons)


def test_nom_de_la_personne_dans_le_mot_de_passe_est_refuse():
    raisons = raisons_mot_de_passe("mon-veronique-2026", nom_complet="Véronique Lambert")
    assert any("nom" in raison for raison in raisons)


def test_fragments_courts_ne_bloquent_pas_un_mot_de_passe_legitime():
    # « Jo » et « Ed » sont trop courts pour être des fragments significatifs.
    assert raisons_mot_de_passe("Ceci-est-un-long-mot-de-passe", email="jo@exemple.fr", nom_complet="Jo Ed") == []


def test_caractere_unique_repete_est_refuse():
    assert any("répété" in raison for raison in raisons_mot_de_passe("a" * 16))


def test_verifie_leve_une_erreur_qui_porte_toutes_les_raisons():
    with pytest.raises(PolitiqueMotDePasseErreur) as erreur:
        verifie_mot_de_passe("aaaaaaaaaaa")  # 11 caractères et répétition
    assert len(erreur.value.raisons) == 2


def test_mot_de_passe_temporaire_du_personnel_respecte_la_politique():
    # create_station_staff_member et reset_station_staff_password génèrent
    # secrets.token_urlsafe(9) : 12 caractères, donc sous la règle, jamais refusé.
    for _ in range(200):
        temporaire = secrets.token_urlsafe(9)
        assert raisons_mot_de_passe(temporaire) == [], temporaire


# ---------------------------------------------------------------------------
# Intégration : API
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _boite_de_test(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    memory_outbox().clear()
    yield
    memory_outbox().clear()


async def _inscrire(client: AsyncClient, email: str | None = None, mot_de_passe: str = MOT_DE_PASSE_VALIDE) -> dict:
    email = email or unique_email()
    res = await client.post(URL_REGISTER, json={"email": email, "password": mot_de_passe, "fullName": "Acteur Test"})
    assert res.status_code == 201, res.text
    login = await client.post(URL_LOGIN, json={"email": email, "password": mot_de_passe})
    assert login.status_code == 200, login.text
    tokens = login.json()
    return {"id": res.json()["id"], "email": email, "motDePasse": mot_de_passe, **tokens}


def _entetes(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_inscription_refuse_un_mot_de_passe_de_11_caracteres(client: AsyncClient):
    res = await client.post(URL_REGISTER, json={"email": unique_email(), "password": "Lune-Verte2", "fullName": "Acteur"})
    assert res.status_code == 422, res.text
    assert "12 caractères" in res.text


async def test_inscription_refuse_un_mot_de_passe_courant(client: AsyncClient):
    res = await client.post(URL_REGISTER, json={"email": unique_email(), "password": "MotDePasse1234", "fullName": "Acteur"})
    assert res.status_code == 422, res.text
    assert "courants" in res.text


async def test_inscription_refuse_le_nom_dans_le_mot_de_passe(client: AsyncClient):
    res = await client.post(URL_REGISTER, json={"email": unique_email(), "password": "mon-veronique-2026", "fullName": "Véronique Lambert"})
    assert res.status_code == 422, res.text
    assert "nom" in res.text


async def test_inscription_normalise_l_email_et_refuse_le_doublon_de_casse(client: AsyncClient):
    base = unique_email()
    res = await client.post(URL_REGISTER, json={"email": base.upper(), "password": MOT_DE_PASSE_VALIDE, "fullName": "Acteur"})
    assert res.status_code == 201, res.text
    assert res.json()["email"] == base.lower()

    doublon = await client.post(URL_REGISTER, json={"email": base, "password": MOT_DE_PASSE_VALIDE, "fullName": "Autre"})
    assert doublon.status_code == 409, doublon.text
    assert doublon.json()["error"]["code"] == "email_already_used"

    login = await client.post(URL_LOGIN, json={"email": base.upper(), "password": MOT_DE_PASSE_VALIDE})
    assert login.status_code == 200, login.text


async def test_activation_refuse_un_mot_de_passe_faible_sans_consommer_le_jeton(client: AsyncClient):
    proprietaire = await _inscrire(client)
    cree = await client.post(
        URL_ORGANISATIONS, json={"name": "Org T013", "slug": f"org-t013-{uuid.uuid4().hex[:10]}"}, headers=_entetes(proprietaire["accessToken"])
    )
    assert cree.status_code == 201, cree.text
    organisation = cree.json()["id"]
    email_titulaire = unique_email()
    compte = await client.post(
        URL_CREATION.format(org=organisation),
        json={"email": email_titulaire, "fullName": "Titulaire Test"},
        headers={**_entetes(proprietaire["accessToken"]), "X-Organization-Id": organisation},
    )
    assert compte.status_code == 201, compte.text

    message = [m for m in memory_outbox() if m.to == email_titulaire][-1]
    jeton = REGEX_JETON.search(message.body).group(1)

    faible = await client.post(URL_ACTIVATION, json={"token": jeton, "password": "court-1"})
    assert faible.status_code == 422, faible.text
    assert "12 caractères" in faible.text

    # Le jeton n'a pas été consommé : l'activation avec un mot de passe valide réussit.
    ok = await client.post(URL_ACTIVATION, json={"token": jeton, "password": "Lune-Verte-2026"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "active"


async def test_activation_refuse_le_nom_du_titulaire_sans_consommer_le_jeton(client: AsyncClient):
    proprietaire = await _inscrire(client)
    organisation = (
        await client.post(URL_ORGANISATIONS, json={"name": "Org T013b", "slug": f"org-t013b-{uuid.uuid4().hex[:10]}"}, headers=_entetes(proprietaire["accessToken"]))
    ).json()["id"]
    email_titulaire = unique_email()
    await client.post(
        URL_CREATION.format(org=organisation),
        json={"email": email_titulaire, "fullName": "Veronique Lambert"},
        headers={**_entetes(proprietaire["accessToken"]), "X-Organization-Id": organisation},
    )
    jeton = REGEX_JETON.search([m for m in memory_outbox() if m.to == email_titulaire][-1].body).group(1)

    refuse = await client.post(URL_ACTIVATION, json={"token": jeton, "password": "mon-veronique-2026"})
    assert refuse.status_code == 422, refuse.text
    ok = await client.post(URL_ACTIVATION, json={"token": jeton, "password": "Lune-Verte-2026"})
    assert ok.status_code == 200, ok.text


async def test_changement_refuse_un_mot_de_passe_trop_court(client: AsyncClient):
    compte = await _inscrire(client)
    res = await client.post(
        URL_CHANGEMENT,
        json={"currentPassword": compte["motDePasse"], "newPassword": "Lune-Verte2"},
        headers=_entetes(compte["accessToken"]),
    )
    assert res.status_code == 422, res.text
    assert "12 caractères" in res.text


async def test_changement_refuse_un_mot_de_passe_contenant_l_email(client: AsyncClient):
    compte = await _inscrire(client)
    fragment = compte["email"].split("@")[0]
    res = await client.post(
        URL_CHANGEMENT,
        json={"currentPassword": compte["motDePasse"], "newPassword": f"mon-{fragment}-2026"},
        headers=_entetes(compte["accessToken"]),
    )
    assert res.status_code == 422, res.text
    assert "e-mail" in res.text


async def _creer_utilisateur_a_changer(mot_de_passe: str = "Temporaire-2026-x") -> dict:
    """Compte créé comme le personnel de station : mustChangePassword vrai."""
    email = unique_email()
    async with AsyncSessionLocal() as db:
        utilisateur = User(
            email=email, fullName="Personnel Test", hashedPassword=hash_password(mot_de_passe), status="active", mustChangePassword=True
        )
        db.add(utilisateur)
        await db.commit()
        return {"id": str(utilisateur.id), "email": email, "motDePasse": mot_de_passe}


async def test_must_change_password_restreint_le_jeton_tant_que_non_change(client: AsyncClient):
    compte = await _creer_utilisateur_a_changer()
    login = await client.post(URL_LOGIN, json={"email": compte["email"], "password": compte["motDePasse"]})
    assert login.status_code == 200, login.text
    token = login.json()["accessToken"]

    # Autorisés : profil et changement de mot de passe.
    me = await client.get(URL_ME, headers=_entetes(token))
    assert me.status_code == 200, me.text
    assert me.json()["mustChangePassword"] is True

    # Refusé partout ailleurs, appliqué côté backend (pas seulement dans l'interface).
    bloque = await client.get(URL_ORGANISATIONS, headers=_entetes(token))
    assert bloque.status_code == 403, bloque.text
    assert bloque.json()["error"]["code"] == "password_change_required"


async def test_changement_leve_la_restriction_et_revoque_les_autres_sessions(client: AsyncClient):
    compte = await _creer_utilisateur_a_changer()
    session_a = (await client.post(URL_LOGIN, json={"email": compte["email"], "password": compte["motDePasse"]})).json()
    session_b = (await client.post(URL_LOGIN, json={"email": compte["email"], "password": compte["motDePasse"]})).json()

    res = await client.post(
        URL_CHANGEMENT,
        json={"currentPassword": compte["motDePasse"], "newPassword": "Lune-Verte-Neuve-42", "refreshToken": session_a["refreshToken"]},
        headers=_entetes(session_a["accessToken"]),
    )
    assert res.status_code == 200, res.text
    assert res.json()["mustChangePassword"] is False

    # La session qui a changé le mot de passe reste ouverte ; l'autre est révoquée.
    ouverte = await client.post(URL_REFRESH, json={"refreshToken": session_a["refreshToken"]})
    assert ouverte.status_code == 200, ouverte.text
    revoquee = await client.post(URL_REFRESH, json={"refreshToken": session_b["refreshToken"]})
    assert revoquee.status_code == 401, revoquee.text

    acces = await client.get(URL_ORGANISATIONS, headers=_entetes(session_a["accessToken"]))
    assert acces.status_code == 200, acces.text


async def test_changement_sans_jeton_de_session_revoque_toutes_les_sessions(client: AsyncClient):
    compte = await _creer_utilisateur_a_changer()
    session = (await client.post(URL_LOGIN, json={"email": compte["email"], "password": compte["motDePasse"]})).json()
    res = await client.post(
        URL_CHANGEMENT,
        json={"currentPassword": compte["motDePasse"], "newPassword": "Lune-Verte-Neuve-43"},
        headers=_entetes(session["accessToken"]),
    )
    assert res.status_code == 200, res.text
    refuse = await client.post(URL_REFRESH, json={"refreshToken": session["refreshToken"]})
    assert refuse.status_code == 401, refuse.text


async def test_revocation_persistee_en_base(client: AsyncClient):
    compte = await _inscrire(client)
    async with AsyncSessionLocal() as db:
        actifs = (
            await db.execute(
                select(RefreshToken).where(RefreshToken.userId == uuid.UUID(compte["id"]), RefreshToken.revokedAt.is_(None))
            )
        ).scalars().all()
    assert len(actifs) >= 1
    res = await client.post(
        URL_CHANGEMENT,
        json={"currentPassword": compte["motDePasse"], "newPassword": "Lune-Verte-Neuve-44"},
        headers=_entetes(compte["accessToken"]),
    )
    assert res.status_code == 200, res.text
    async with AsyncSessionLocal() as db:
        restants = (
            await db.execute(
                select(RefreshToken).where(RefreshToken.userId == uuid.UUID(compte["id"]), RefreshToken.revokedAt.is_(None))
            )
        ).scalars().all()
    assert restants == []
