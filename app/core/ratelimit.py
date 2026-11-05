"""Limites d'usage et détection d'abus (BE-253).

Périmètre : socle partagé. Ce module ne possède aucune route. Les routes
d'authentification et d'API l'appliquent par `Depends(exiger_limite(...))`.

Algorithme : fenêtre fixe alignée sur l'horloge UNIX. Le compteur d'une clé
vit dans la table `rate_limit_events` (une ligne par clé et par fenêtre) et
s'incrémente en une seule instruction `INSERT ... ON CONFLICT DO UPDATE`, donc
exacte entre plusieurs workers, contrairement au compteur mémoire de
`app/shared/quotas.py` (BE-191), qui n'est pas partagé.

Clé de comptage : empreinte SHA-256 de (portée, tenant, identité). Le tenant
est dans la clé, donc deux tenants ne se partagent jamais un compteur (CA-2).
L'identité (IP, identifiant utilisateur...) n'est jamais stockée en clair.

Seuil : lu dans `Settings` (`RATE_LIMIT_MAX_REQUETES`, `RATE_LIMIT_FENETRE_SECONDES`).
Les valeurs par défaut sont provisoires : le seuil produit n'est pas encore
décidé (QE-EXP-07, voir docs/questions/securite/).

Dépassement : la requête refusée est comptée (le compteur monte au-delà du
seuil). Ce choix garde la trace des tentatives d'abus ; il prolonge le blocage
tant que le client continue, ce qui est voulu pour un abus. La réponse est
AppError 429, code `rate_limited`, avec l'en-tête `Retry-After` en secondes
restant avant la fin de la fenêtre.

Détection d'abus (CA-3) : à la première requête refusée d'une fenêtre (le
compteur atteint seuil + 1), un `EvenementAbus` est remis à chaque destinataire
de `destinataires_abus`. Le destinataire par défaut écrit dans le journal de
sécurité ; une routage vers le module d'alertes reste à décider (voir la
documentation de la tâche). Un seul événement par fenêtre et par clé évite le
spam quand un client continue d'insister.

Interdit : aucun score de réputation de tenant n'est calculé ni stocké (CA-4,
contrôlé par un test d'inventaire).
"""

import hashlib
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.errors import AppError
from app.shared.quotas import PolitiqueQuota

security_logger = logging.getLogger("zylo_office.security")

CODE_LIMITE = "rate_limited"
MESSAGE_LIMITE = "Trop de requêtes. Réessayez plus tard."


class RateLimitEvent(Base):
    """Compteur d'une clé pour une fenêtre donnée.

    `cle` est l'empreinte SHA-256 de (portée, tenant, identité) ; `fenetre` est
    le début de la fenêtre (horodatage UTC) ; `compteur` le nombre de requêtes
    comptées dans cette fenêtre. La clé primaire composée garantit une seule
    ligne par clé et par fenêtre, condition de l'upsert atomique.
    """

    __tablename__ = "rate_limit_events"
    __table_args__ = {"comment": "Compteurs de limites d'usage par clé et fenêtre (BE-253). Empreintes uniquement."}

    cle: Mapped[str] = mapped_column(String(64), primary_key=True, comment="Empreinte SHA-256 de (portée, tenant, identité)")
    fenetre: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, comment="Début de la fenêtre, UTC"
    )
    compteur: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="Requêtes comptées dans la fenêtre")


@dataclass(frozen=True)
class EvenementAbus:
    """Abus détecté : une clé a dépassé son seuil pour la fenêtre courante.

    Ne contient ni identité ni tenant en clair au-delà de `tenant_id`, nécessaire
    au routage. `empreinte` est la clé hachée, pour corréler sans révéler l'identité.
    """

    tenant_id: str
    portee: str
    empreinte: str
    seuil: int
    fenetre_debut: datetime


def maintenant() -> datetime:
    """Horloge du module ; les tests la remplacent par `horloge=` ou par monkeypatch."""
    return datetime.now(timezone.utc)


def politique_limite_api() -> PolitiqueQuota:
    """Limite d'API par tenant et identité, lue dans `Settings` à chaque appel."""
    return PolitiqueQuota(
        nom="api",
        categorie="technique",
        max_requetes=settings.RATE_LIMIT_MAX_REQUETES,
        fenetre_secondes=settings.RATE_LIMIT_FENETRE_SECONDES,
    )


def cle_limite(tenant_id: str, identite: str, portee: str) -> str:
    """Empreinte SHA-256 de (portée, tenant, identité), 64 caractères hexadécimaux.

    Le séparateur `|` suffit : les identifiants (UUID, IP, identifiants de
    compte) ne le contiennent pas. L'empreinte ne révèle ni le tenant ni l'identité.
    """
    return hashlib.sha256(f"{portee}|{tenant_id}|{identite}".encode("utf-8")).hexdigest()


def _debut_fenetre(instant: datetime, fenetre_secondes: int) -> datetime:
    """Début de la fenêtre contenant `instant`, aligné sur l'horloge UNIX."""
    horodatage = int(instant.timestamp())
    return datetime.fromtimestamp(horodatage - horodatage % fenetre_secondes, tz=timezone.utc)


def _journaliser_abus(evenement: EvenementAbus) -> None:
    """Destinataire par défaut : journal de sécurité, sans identité en clair."""
    security_logger.warning(
        "rate_limit_abuse",
        extra={
            "portee": evenement.portee,
            "tenant_id": evenement.tenant_id,
            "empreinte": evenement.empreinte[:12],
            "seuil": evenement.seuil,
        },
    )


# Destinataires de l'événement d'abus (CA-3). Les tests les remplacent ; ajouter
# un destinataire ici ne modifie pas le compteur.
destinataires_abus: list[Callable[[EvenementAbus], None]] = [_journaliser_abus]


async def consomme(
    db: AsyncSession,
    politique: PolitiqueQuota,
    *,
    tenant_id: str,
    identite: str,
    instant: datetime | None = None,
) -> int:
    """Compte une requête pour (tenant, identité) et lève 429 au-delà du seuil.

    Retourne le compteur après incrément quand la requête est acceptée.
    Lève `AppError` (429, `rate_limited`, `Retry-After`) quand le compteur dépasse
    `politique.max_requetes`. Émet un `EvenementAbus` vers `destinataires_abus`
    à la première requête refusée de la fenêtre. La transaction est validée ici
    pour que le compteur survive à la réponse d'erreur.
    """
    instant = instant or maintenant()
    debut = _debut_fenetre(instant, politique.fenetre_secondes)
    cle = cle_limite(tenant_id, identite, politique.nom)

    table = RateLimitEvent.__table__
    insertion = pg_insert(table).values(cle=cle, fenetre=debut, compteur=1)
    instruction = insertion.on_conflict_do_update(
        index_elements=[table.c.cle, table.c.fenetre],
        set_={"compteur": table.c.compteur + 1},
    ).returning(table.c.compteur)
    compteur = (await db.execute(instruction)).scalar_one()
    await db.commit()

    if compteur <= politique.max_requetes:
        return compteur

    if compteur == politique.max_requetes + 1:
        evenement = EvenementAbus(
            tenant_id=tenant_id,
            portee=politique.nom,
            empreinte=cle,
            seuil=politique.max_requetes,
            fenetre_debut=debut,
        )
        for destinataire in destinataires_abus:
            destinataire(evenement)

    fin = debut + timedelta(seconds=politique.fenetre_secondes)
    restant = max(1, math.ceil((fin - instant).total_seconds()))
    raise AppError(
        code=CODE_LIMITE,
        message=MESSAGE_LIMITE,
        status_code=429,
        headers={"Retry-After": str(restant)},
    )


def exiger_limite(
    politique: PolitiqueQuota,
    identifier: Callable[[Request], tuple[str, str]],
    horloge: Callable[[], datetime] = maintenant,
):
    """Fabrique une dépendance FastAPI qui compte la requête sous (tenant, identité).

    `identifier(requete)` renvoie `(tenant_id, identite)`, lus sur la requête
    (en-tête, état posé par un middleware d'authentification). Usage :
    `Depends(exiger_limite(politique_limite_api(), lambda r: (r.state.tenant_id, r.client.host)))`.
    """

    async def dependance(requete: Request, db: AsyncSession = Depends(get_db)) -> None:
        tenant_id, identite = identifier(requete)
        await consomme(db, politique, tenant_id=tenant_id, identite=identite, instant=horloge())

    return dependance
