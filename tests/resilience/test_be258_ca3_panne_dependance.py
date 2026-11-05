"""BE-258 CA-3 : une panne de dépendance produit une erreur contractuelle, pas une fuite.

Tests écrits d'après la définition `### BE-258` de implementation-backend/tasks-exploitation-architecture.md,
avant le code.

Dépendance simulée : un adaptateur de canal (BE-170, `app.notifications.canal`) qui échoue avec une
exception brute porteuse d'un détail interne (adresse et secret). Contrat attendu :
- l'exception brute ne remonte pas à l'appelant ;
- l'appelant reçoit une `AppError` du catalogue : code `CHANNEL_UNAVAILABLE`, statut 503 ;
- la tentative est tracée `retarde` avec une prochaine tentative, et la notification reste `en_attente` ;
- ni le message, ni la représentation de l'erreur, ni le journal ne reprennent le détail interne.

Données : chaque test crée son utilisateur, sa catégorie et sa notification ; le canal est retiré à la fin.
"""

import logging
import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.core.security import hash_password
from app.identity.models import User
from app.notifications.canal import (
    MessageLivraison,
    enregistrer_adaptateur,
    livrer_notification,
    retirer_adaptateur,
)
from app.notifications.categories import creer_categorie
from app.notifications.models import Livraison, Notification

AUDIENCE = "membres_organisation"
DETAIL_INTERNE = "connexion refusée à 10.0.4.7:5432 password=hunter2-be258"
FRAGMENTS_INTERNES = ("10.0.4.7", "hunter2")


class DependanceEnPanne:
    """Adaptateur simulant une dépendance indisponible : lève une erreur brute porteuse d'un détail interne."""

    async def livrer(self, message: MessageLivraison):
        raise ConnectionError(DETAIL_INTERNE)


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Le pool asyncpg est vidé avant et après chaque test (chaque test a sa boucle asyncio)."""
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
def canal_en_panne():
    """Enregistre un canal dont la dépendance est en panne, et le retire à la fin du test."""
    nom = f"be258-{uuid.uuid4().hex[:10]}"
    enregistrer_adaptateur(nom, DependanceEnPanne())
    yield nom
    retirer_adaptateur(nom)


async def _notification_en_attente() -> uuid.UUID:
    """Crée une notification `en_attente` pour un destinataire de test ; renvoie son identifiant."""
    async with AsyncSessionLocal() as db:
        destinataire = User(
            email=f"be258-{uuid.uuid4().hex[:10]}@example.invalid",
            hashedPassword=hash_password("x"),
            fullName="Destinataire BE-258",
            status="active",
        )
        db.add(destinataire)
        await db.flush()
        categorie = f"BE258-{uuid.uuid4().hex[:10]}"
        await creer_categorie(db, code=categorie, libelle="Catégorie BE-258", audience_regle=AUDIENCE)
        await db.commit()
        notification = Notification(
            eventId=uuid.uuid4(),
            categorieCode=categorie,
            destinataireId=destinataire.id,
            statut="en_attente",
            motifSuppression=None,
        )
        db.add(notification)
        await db.commit()
        return notification.id


async def _livraisons(notification_id: uuid.UUID) -> list[Livraison]:
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(
            select(Livraison).where(Livraison.notificationId == notification_id).order_by(Livraison.tentativeNo)
        )
        return list(resultat.scalars().all())


async def test_be258_ca3_panne_de_dependance_renvoie_erreur_contractuelle(canal_en_panne):
    """CA-3 : la panne de l'adaptateur devient `CHANNEL_UNAVAILABLE` (503), jamais l'exception brute."""
    notification_id = await _notification_en_attente()

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await livrer_notification(db, notificationId=notification_id, canal=canal_en_panne)

    assert erreur.value.code == "CHANNEL_UNAVAILABLE"
    assert erreur.value.status_code == 503


async def test_be258_ca3_panne_de_dependance_trace_la_tentative_sans_fuite(canal_en_panne, caplog):
    """CA-3 : la tentative est tracée `retarde`, et le détail interne n'apparaît ni dans l'erreur ni dans le journal."""
    notification_id = await _notification_en_attente()
    caplog.set_level(logging.DEBUG)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as erreur:
            await livrer_notification(db, notificationId=notification_id, canal=canal_en_panne)

    livraisons = await _livraisons(notification_id)
    assert [(item.resultat, item.prochaineTentativeAt is not None) for item in livraisons] == [("retarde", True)]
    assert livraisons[0].codeErreur == "CHANNEL_UNAVAILABLE"

    for fragment in FRAGMENTS_INTERNES:
        assert fragment not in erreur.value.message
        assert fragment not in str(erreur.value)
        assert fragment not in repr(erreur.value)
        assert fragment not in caplog.text
    assert not getattr(erreur.value, "details", None)
