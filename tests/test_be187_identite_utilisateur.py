"""BE-187 : identité utilisateur (cycle de vie, verrouillage, suppression).

Tests écrits d'après la définition `### BE-187` de
implementation-backend/tasks-donnees-api-contrats.md, avant le code.

Aucune route publique (BE-187) : les transitions sont appelées par le service
`app/identity/cycle_de_vie_utilisateur.py`, la connexion passe par `/api/v1/auth/login`.
"""

import logging
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.core.security import hash_password
from app.identity.cycle_de_vie_utilisateur import transitionner_utilisateur
from app.identity.models import User

MOT_DE_PASSE = "TestPassword123!"


async def _creer_utilisateur(status: str = "active", **champs) -> User:
    """Crée un utilisateur directement en base, avec un identifiant unique."""
    base = f"be187-{uuid.uuid4().hex[:10]}"
    valeurs = {
        "email": f"{base}@zylo-office-test.example.com",
        "hashedPassword": hash_password(MOT_DE_PASSE),
        "fullName": "Personne Test",
        "status": status,
    }
    valeurs.update(champs)
    async with AsyncSessionLocal() as db:
        utilisateur = User(**valeurs)
        db.add(utilisateur)
        await db.commit()
        await db.refresh(utilisateur)
        return utilisateur


async def _relire(user_id: uuid.UUID) -> User:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User).where(User.id == user_id))).scalar_one()


async def test_be187_ca1_hachage_absent_des_reponses_et_des_journaux(client: AsyncClient, caplog):
    caplog.set_level(logging.DEBUG)
    utilisateur = await _creer_utilisateur()
    hachage = utilisateur.hashedPassword

    reussite = await client.post("/api/v1/auth/login", json={"email": utilisateur.email, "password": MOT_DE_PASSE})
    echec = await client.post("/api/v1/auth/login", json={"email": utilisateur.email, "password": "Mauvais-Mot-2024!"})

    for reponse in (reussite, echec):
        assert hachage not in reponse.text
        assert MOT_DE_PASSE not in reponse.text
    assert hachage not in caplog.text
    assert MOT_DE_PASSE not in caplog.text


async def test_be187_ca2_courriel_en_double_casse_refuse(client: AsyncClient):
    base = f"be187-{uuid.uuid4().hex[:10]}"
    async with AsyncSessionLocal() as db:
        db.add(User(email=f"{base}@Zylo-Test.example.com", hashedPassword="x", fullName="Premier"))
        await db.commit()

    async with AsyncSessionLocal() as db:
        db.add(User(email=f"{base.upper()}@zylo-test.EXAMPLE.com", hashedPassword="x", fullName="Second"))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_be187_ca3_transition_hors_graphe_renvoie_422(client: AsyncClient):
    utilisateur = await _creer_utilisateur(status="pending")

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await transitionner_utilisateur(db, utilisateur.id, "verrouiller")
    assert erreur.value.status_code == 422
    assert erreur.value.code == "user_transition_invalide"
    assert (await _relire(utilisateur.id)).status == "pending"


async def test_be187_ca3_sortie_d_un_etat_supprime_renvoie_422(client: AsyncClient):
    utilisateur = await _creer_utilisateur(status="active")
    async with AsyncSessionLocal() as db:
        await transitionner_utilisateur(db, utilisateur.id, "supprimer")

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await transitionner_utilisateur(db, utilisateur.id, "activer")
    assert erreur.value.status_code == 422
    assert erreur.value.code == "user_transition_invalide"


async def test_be187_graphe_chemins_valides_et_version(client: AsyncClient):
    utilisateur = await _creer_utilisateur(status="pending")
    async with AsyncSessionLocal() as db:
        await transitionner_utilisateur(db, utilisateur.id, "activer")
    async with AsyncSessionLocal() as db:
        await transitionner_utilisateur(db, utilisateur.id, "verrouiller")
    async with AsyncSessionLocal() as db:
        await transitionner_utilisateur(db, utilisateur.id, "deverrouiller")
    async with AsyncSessionLocal() as db:
        await transitionner_utilisateur(db, utilisateur.id, "desactiver")
    async with AsyncSessionLocal() as db:
        await transitionner_utilisateur(db, utilisateur.id, "reactiver")

    relu = await _relire(utilisateur.id)
    assert relu.status == "active"
    assert relu.version == 6  # 1 à la création, +1 par transition réussie


async def test_be187_ca4_utilisateur_verrouille_ne_peut_ouvrir_de_session(client: AsyncClient):
    utilisateur = await _creer_utilisateur(status="active")
    async with AsyncSessionLocal() as db:
        await transitionner_utilisateur(db, utilisateur.id, "verrouiller")

    reponse = await client.post("/api/v1/auth/login", json={"email": utilisateur.email, "password": MOT_DE_PASSE})

    assert reponse.status_code == 401
    corps = reponse.json()
    assert "accessToken" not in corps
    assert "refreshToken" not in corps


async def test_be187_ca5_utilisateur_supprime_ne_renvoie_plus_de_donnees_personnelles(client: AsyncClient):
    utilisateur = await _creer_utilisateur(
        status="active",
        fullName="Nom Complet Réel",
        firstName="Prenom",
        lastName="Nomfamille",
        phone="0600000000",
        photoStorageReference="photos/reference-reelle",
    )
    courriel_initial = utilisateur.email

    async with AsyncSessionLocal() as db:
        await transitionner_utilisateur(db, utilisateur.id, "supprimer")

    relu = await _relire(utilisateur.id)
    assert relu.status == "deleted"
    assert relu.deletedAt is not None
    assert relu.email != courriel_initial
    assert "Nom Complet Réel" not in relu.fullName
    assert relu.firstName is None
    assert relu.lastName is None
    assert relu.phone is None
    assert relu.photoStorageReference is None
    assert courriel_initial not in (relu.email, relu.fullName)

    reponse = await client.post("/api/v1/auth/login", json={"email": courriel_initial, "password": MOT_DE_PASSE})
    assert reponse.status_code == 401
