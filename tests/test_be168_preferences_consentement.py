"""BE-168 : préférences et consentement par catégorie.

Tests écrits d'après la définition `### BE-168` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : `PUT /api/v1/notifications/preferences/{categorie_code}` modifie la préférence
  et écrit l'horodatage du consentement ; `GET .../preferences` le relit ;
- CA-2 : après désinscription, un envoi de la catégorie est refusé avec
  `CONSENT_SUPPRESSED` ; une réinscription rétablit l'envoi ;
- CA-3 (refus) : lecture ou modification des préférences d'un autre utilisateur = `403` ;
- CA-4 : aucune plage de silence ni heure calme n'existe (ni colonne ni champ de réponse) ;
  aucune préférence n'est inventée pour une catégorie non renseignée ;
- CA-5 (isolation tenant) : un utilisateur hors de l'organisation active ne lit pas les
  préférences de cet utilisateur : `404` TENANT_MISMATCH ;
- unicité `(utilisateurId, categorieCode)` en base.

Points non tranchés par la définition (signalés dans le rapport, pas présumés ici) :
- QE-PAR-02 : les routes n'ont pas d'identifiant utilisateur dans le chemin ; le refus
  CA-3 est donc testé au niveau du service, qui reçoit `utilisateur_id` en argument ;
- QE-PAR-04 : la colonne `canal` n'est pas créée (le canal reste NON DÉFINI).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.identity.models import OrganizationUser, User
from app.notifications import preferences
from app.notifications.categories import creer_categorie
from app.notifications.models import PreferenceNotification
from app.notifications.schemas import PreferenceNotificationResponse

PREFERENCES_URL = "/api/v1/notifications/preferences"


@pytest.fixture(autouse=True)
async def _pool_neuf():
    """Même remise à zéro que les autres tests de notifications : le moteur est un
    singleton dont les connexions poolées restent liées à la boucle précédente."""
    await engine.dispose()
    yield


def _code() -> str:
    return f"BE168-{uuid.uuid4().hex[:12]}"


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _categorie() -> str:
    code = _code()
    async with AsyncSessionLocal() as db:
        await creer_categorie(db, code=code, libelle="Catégorie BE-168", audience_regle="membres_organisation")
    return code


async def _utilisateur(organization_id: str | None = None) -> uuid.UUID:
    """Crée un utilisateur ; l'ajoute à l'organisation si `organization_id` est fourni."""
    async with AsyncSessionLocal() as db:
        utilisateur = User(email=f"be168-{uuid.uuid4().hex}@test.local", hashedPassword="x", fullName="BE168")
        db.add(utilisateur)
        await db.commit()
        if organization_id is not None:
            db.add(OrganizationUser(userId=utilisateur.id, organizationId=uuid.UUID(organization_id)))
            await db.commit()
        return utilisateur.id


async def _id_par_email(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(User.id).where(User.email == email))


async def _lignes_preference(utilisateur_id: uuid.UUID, categorie_code: str) -> int:
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(
            select(PreferenceNotification).where(
                PreferenceNotification.utilisateurId == utilisateur_id,
                PreferenceNotification.categorieCode == categorie_code,
            )
        )
        return len(resultat.scalars().all())


async def test_be168_ca1_put_modifie_la_preference_et_ecrit_l_horodatage(client, registered_user, organization):
    code = await _categorie()
    avant = datetime.now(timezone.utc)

    reponse = await client.put(
        f"{PREFERENCES_URL}/{code}", json={"consentement": False}, headers=_headers(registered_user, organization)
    )

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["categorieCode"] == code
    assert corps["consentement"] is False
    horodatage = datetime.fromisoformat(corps["horodatageConsentement"])
    assert horodatage >= avant - timedelta(seconds=1)

    lecture = await client.get(PREFERENCES_URL, headers=_headers(registered_user, organization))
    assert lecture.status_code == 200, lecture.text
    assert any(ligne["categorieCode"] == code and ligne["consentement"] is False for ligne in lecture.json())


async def test_be168_ca2_desinscription_supprime_l_envoi_puis_reinscription_le_rétablit(
    client, registered_user, organization
):
    code = await _categorie()
    utilisateur_id = await _id_par_email(registered_user["email"])
    headers = _headers(registered_user, organization)

    await client.put(f"{PREFERENCES_URL}/{code}", json={"consentement": False}, headers=headers)
    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await preferences.verifier_envoi_autorise(db, utilisateur_id=utilisateur_id, categorie_code=code)
    assert erreur.value.code == "CONSENT_SUPPRESSED"
    assert erreur.value.status_code == 403

    await client.put(f"{PREFERENCES_URL}/{code}", json={"consentement": True}, headers=headers)
    async with AsyncSessionLocal() as db:
        await preferences.verifier_envoi_autorise(db, utilisateur_id=utilisateur_id, categorie_code=code)


async def test_be168_ca3_preferences_d_un_autre_utilisateur_refusees_403(organization):
    code = await _categorie()
    acteur = await _utilisateur(organization["id"])
    cible = await _utilisateur(organization["id"])

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as lecture:
            await preferences.lire_preferences(
                db, organization_id=uuid.UUID(organization["id"]), acteur_id=acteur, utilisateur_id=cible
            )
    assert lecture.value.code == "PERMISSION_DENIED"
    assert lecture.value.status_code == 403

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as modification:
            await preferences.modifier_preference(
                db,
                organization_id=uuid.UUID(organization["id"]),
                acteur_id=acteur,
                utilisateur_id=cible,
                categorie_code=code,
                consentement=False,
            )
    assert modification.value.code == "PERMISSION_DENIED"
    assert modification.value.status_code == 403
    assert await _lignes_preference(cible, code) == 0


async def test_be168_ca4_aucune_plage_de_silence_ni_valeur_par_defaut(client, registered_user, organization):
    """CA-4 : la plage de silence et les heures calmes ne sont pas implémentées. Aucune
    colonne ni champ de réponse ne les porte, et une catégorie non renseignée ne produit
    aucune préférence inventée (QE-PAR-14)."""
    champs = set(PreferenceNotification.__table__.columns.keys()) | set(PreferenceNotificationResponse.model_fields)
    interdits = {champ for champ in champs if any(motif in champ.lower() for motif in ("silence", "calme", "quiet"))}
    assert interdits == set()

    code = await _categorie()
    lecture = await client.get(PREFERENCES_URL, headers=_headers(registered_user, organization))
    assert lecture.status_code == 200, lecture.text
    assert all(ligne["categorieCode"] != code for ligne in lecture.json())


async def test_be168_ca5_isolation_tenant_utilisateur_d_un_autre_tenant_404(organization):
    code = await _categorie()
    acteur = await _utilisateur(organization["id"])
    cible = await _utilisateur()  # tenant B : aucun rattachement à l'organisation active

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await preferences.lire_preferences(
                db, organization_id=uuid.UUID(organization["id"]), acteur_id=acteur, utilisateur_id=cible
            )
    assert erreur.value.code == "TENANT_MISMATCH"
    assert erreur.value.status_code == 404
    assert await _lignes_preference(cible, code) == 0


async def test_be168_unicite_utilisateur_categorie():
    code = await _categorie()
    utilisateur_id = await _utilisateur()
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(
            PreferenceNotification(
                utilisateurId=utilisateur_id,
                categorieCode=code,
                consentement=True,
                horodatageConsentement=maintenant,
                sourceConsentement="utilisateur",
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        db.add(
            PreferenceNotification(
                utilisateurId=utilisateur_id,
                categorieCode=code,
                consentement=False,
                horodatageConsentement=maintenant,
                sourceConsentement="utilisateur",
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
