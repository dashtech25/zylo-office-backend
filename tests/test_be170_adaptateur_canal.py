"""BE-170 : adaptateur de canal et résultat de livraison.

Tests écrits d'après la définition `### BE-170` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : un canal non implémenté ou indisponible lève `503` CHANNEL_UNAVAILABLE et laisse
  une ligne `livraison` `retarde` avec `prochaineTentativeAt` (nouvelle tentative) ;
- CA-2 : un rebond permanent ou une plainte arrête les envois vers ce destinataire sur
  la catégorie (refus `403` à la tentative suivante, adaptateur non appelé) ;
- CA-3 : un résultat reçu d'un canal inconnu est rejeté `422` SCHEMA_INVALID, sans ligne
  `livraison` ; un résultat hors énumération l'est aussi ;
- CA-4 : aucune adresse de destinataire n'apparaît dans les journaux ni dans le message
  remis à l'adaptateur (test de recherche d'une valeur factice) ;
- refus interne : l'adaptateur ne livre pas une notification non éligible (`403`).

Points non tranchés par la définition (signalés dans le rapport, pas présumés ici) :
- QE-PAR-04 : le canal n'est pas défini ; le test passe un nom de canal de test, sans
  fournisseur ;
- QE-PAR-01 : le mapping HTTP (`503`, `422`, `403`) est repris de la recommandation
  appliquée dans la définition ;
- le délai de nouvelle tentative n'est pas défini (backoff de BE-164) ; le test vérifie
  seulement qu'une échéance future est posée.
"""

import logging
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.notifications.canal import (
    MessageLivraison,
    ResultatLivraison,
    enregistrer_adaptateur,
    enregistrer_resultat,
    livrer_notification,
    retirer_adaptateur,
)
from app.notifications.categories import creer_categorie
from app.notifications.models import Livraison, Notification
from app.identity.models import User
from app.core.security import hash_password

AUDIENCE = "membres_organisation"
ADRESSE_FACTICE = "destinataire-be170-factice@example.invalid"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé avant
    et après lui (même remise à zéro que les autres tests de notifications)."""
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
def canaux_de_test():
    """Enregistre les canaux de test créés et les retire à la fin du test."""
    noms: list[str] = []

    def _creer(adaptateur) -> str:
        nom = f"be170-{uuid.uuid4().hex[:10]}"
        enregistrer_adaptateur(nom, adaptateur)
        noms.append(nom)
        return nom

    yield _creer
    for nom in noms:
        retirer_adaptateur(nom)


class AdaptateurFactice:
    """Adaptateur de test : renvoie un résultat fixé et compte les appels reçus."""

    def __init__(self, resultat: ResultatLivraison | None = None, erreur: AppError | None = None):
        self.resultat = resultat
        self.erreur = erreur
        self.messages: list[MessageLivraison] = []

    async def livrer(self, message: MessageLivraison) -> ResultatLivraison:
        self.messages.append(message)
        if self.erreur is not None:
            raise self.erreur
        return self.resultat


async def _notification(db, *, statut: str = "en_attente", destinataire: User | None = None, categorie: str | None = None):
    """Une notification `en_attente` (ou au statut donné) pour un destinataire de test."""
    if destinataire is None:
        destinataire = User(
            email=f"be170-{uuid.uuid4().hex[:10]}-{ADRESSE_FACTICE}",
            hashedPassword=hash_password("x"),
            fullName="Destinataire BE-170",
            status="active",
        )
        db.add(destinataire)
        await db.flush()
    if categorie is None:
        categorie = f"BE170-{uuid.uuid4().hex[:10]}"
        await creer_categorie(db, code=categorie, libelle="Catégorie BE-170", audience_regle=AUDIENCE)
        await db.commit()
    notification = Notification(
        eventId=uuid.uuid4(),
        categorieCode=categorie,
        destinataireId=destinataire.id,
        statut=statut,
        motifSuppression=None,
    )
    db.add(notification)
    await db.commit()
    return notification, destinataire, categorie


async def _livraisons(notification_id: uuid.UUID) -> list[Livraison]:
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(
            select(Livraison).where(Livraison.notificationId == notification_id).order_by(Livraison.tentativeNo)
        )
        return list(resultat.scalars().all())


async def _statut(notification_id: uuid.UUID) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(Notification.statut).where(Notification.id == notification_id))).scalar_one()


async def test_ca1_canal_non_implemente_renvoie_channel_unavailable_et_retente():
    """CA-1 : un canal non enregistré lève 503 CHANNEL_UNAVAILABLE et pose une nouvelle tentative."""
    async with AsyncSessionLocal() as db:
        notification, _, _ = await _notification(db)
        notification_id = notification.id
    canal_absent = f"be170-absent-{uuid.uuid4().hex[:10]}"

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await livrer_notification(db, notificationId=notification_id, canal=canal_absent)

    assert erreur.value.code == "CHANNEL_UNAVAILABLE"
    assert erreur.value.status_code == 503
    livraisons = await _livraisons(notification_id)
    assert len(livraisons) == 1
    assert livraisons[0].resultat == "retarde"
    assert livraisons[0].codeErreur == "CHANNEL_UNAVAILABLE"
    assert livraisons[0].prochaineTentativeAt is not None
    assert livraisons[0].prochaineTentativeAt > datetime.now(UTC)
    assert await _statut(notification_id) == "en_attente"


async def test_ca1_adaptateur_indisponible_renvoie_channel_unavailable_et_retente(canaux_de_test):
    """CA-1 : un adaptateur enregistré mais indisponible suit le même chemin de nouvelle tentative."""
    adaptateur = AdaptateurFactice(erreur=AppError("CHANNEL_UNAVAILABLE", "Canal indisponible.", status_code=503))
    canal = canaux_de_test(adaptateur)
    async with AsyncSessionLocal() as db:
        notification, _, _ = await _notification(db)
        notification_id = notification.id

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await livrer_notification(db, notificationId=notification_id, canal=canal)

    assert erreur.value.code == "CHANNEL_UNAVAILABLE"
    livraisons = await _livraisons(notification_id)
    assert [(item.resultat, item.prochaineTentativeAt is not None) for item in livraisons] == [("retarde", True)]
    assert await _statut(notification_id) == "en_attente"


@pytest.mark.parametrize("resultat_destructif", [ResultatLivraison.REBOND, ResultatLivraison.PLAINTE])
async def test_ca2_rebond_ou_plainte_arrete_les_envois_sur_la_categorie(canaux_de_test, resultat_destructif):
    """CA-2 : après un rebond ou une plainte, le même destinataire ne reçoit plus rien sur la catégorie.

    Un autre destinataire de la même catégorie reste joignable : l'arrêt porte sur le couple
    (destinataire, catégorie), pas sur la catégorie seule.
    """
    adaptateur = AdaptateurFactice(resultat=resultat_destructif)
    canal = canaux_de_test(adaptateur)
    async with AsyncSessionLocal() as db:
        premiere, destinataire, categorie = await _notification(db)
        seconde, _, _ = await _notification(db, destinataire=destinataire, categorie=categorie)
        autre_destinataire, _, _ = await _notification(db, categorie=categorie)
        premiere_id, seconde_id, autre_id = premiere.id, seconde.id, autre_destinataire.id

    async with AsyncSessionLocal() as db:
        await livrer_notification(db, notificationId=premiere_id, canal=canal)
    assert await _statut(premiere_id) == "echec"

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await livrer_notification(db, notificationId=seconde_id, canal=canal)
    assert erreur.value.code == "PERMISSION_DENIED"
    assert erreur.value.status_code == 403
    assert len(adaptateur.messages) == 1
    assert await _livraisons(seconde_id) == []

    async with AsyncSessionLocal() as db:
        await livrer_notification(db, notificationId=autre_id, canal=canal)
    assert len(adaptateur.messages) == 2
    assert adaptateur.messages[-1].destinataireId != destinataire.id


async def test_ca3_resultat_d_un_canal_inconnu_rejete_schema_invalid():
    """CA-3 : un résultat de livraison reçu d'un canal non enregistré est rejeté 422 SCHEMA_INVALID."""
    async with AsyncSessionLocal() as db:
        notification, _, _ = await _notification(db)
        notification_id = notification.id
    canal_inconnu = f"be170-inconnu-{uuid.uuid4().hex[:10]}"

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_resultat(
                db, notificationId=notification_id, canal=canal_inconnu, resultat=ResultatLivraison.LIVRE
            )

    assert erreur.value.code == "SCHEMA_INVALID"
    assert erreur.value.status_code == 422
    assert await _livraisons(notification_id) == []


async def test_ca3_resultat_hors_enumeration_rejete_schema_invalid(canaux_de_test):
    """CA-3 : une valeur de résultat hors de la liste accepte, livre, retarde, rebond, plainte, echec est rejetée."""
    canal = canaux_de_test(AdaptateurFactice(resultat=ResultatLivraison.LIVRE))
    async with AsyncSessionLocal() as db:
        notification, _, _ = await _notification(db)
        notification_id = notification.id

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await enregistrer_resultat(db, notificationId=notification_id, canal=canal, resultat="ouvert")

    assert erreur.value.code == "SCHEMA_INVALID"
    assert erreur.value.status_code == 422
    assert await _livraisons(notification_id) == []


async def test_ca4_aucune_adresse_dans_les_journaux_ni_dans_le_message(canaux_de_test, caplog):
    """CA-4 : l'adresse factice du destinataire n'apparaît ni dans les journaux ni dans le message remis au canal."""
    caplog.set_level(logging.DEBUG)
    adaptateur = AdaptateurFactice(resultat=ResultatLivraison.LIVRE)
    canal = canaux_de_test(adaptateur)
    async with AsyncSessionLocal() as db:
        notification, _, _ = await _notification(db)
        notification_id = notification.id

    async with AsyncSessionLocal() as db:
        await livrer_notification(db, notificationId=notification_id, canal=canal)

    assert len(adaptateur.messages) == 1
    assert ADRESSE_FACTICE not in repr(adaptateur.messages[0])
    assert ADRESSE_FACTICE not in caplog.text


async def test_refus_interne_adaptateur_sans_notification_eligible(canaux_de_test):
    """Refus interne : une notification déjà envoyée, ou inexistante, n'est pas remise au canal (403)."""
    adaptateur = AdaptateurFactice(resultat=ResultatLivraison.LIVRE)
    canal = canaux_de_test(adaptateur)
    async with AsyncSessionLocal() as db:
        deja_envoyee, _, _ = await _notification(db, statut="envoyee")
        deja_envoyee_id = deja_envoyee.id

    for notification_id in (deja_envoyee_id, uuid.uuid4()):
        async with AsyncSessionLocal() as db:
            with pytest.raises(AppError) as erreur:
                await livrer_notification(db, notificationId=notification_id, canal=canal)
        assert erreur.value.code == "PERMISSION_DENIED"
        assert erreur.value.status_code == 403

    assert adaptateur.messages == []


async def test_livraison_acceptee_passe_la_notification_a_envoyee(canaux_de_test):
    """Un résultat `livre` fait passer la notification de `en_attente` à `envoyee` et trace la tentative 1."""
    canal = canaux_de_test(AdaptateurFactice(resultat=ResultatLivraison.LIVRE))
    async with AsyncSessionLocal() as db:
        notification, _, _ = await _notification(db)
        notification_id = notification.id

    async with AsyncSessionLocal() as db:
        await livrer_notification(db, notificationId=notification_id, canal=canal)

    livraisons = await _livraisons(notification_id)
    assert [(item.tentativeNo, item.resultat) for item in livraisons] == [(1, "livre")]
    assert await _statut(notification_id) == "envoyee"
