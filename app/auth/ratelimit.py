"""Limitation de débit et verrouillage progressif de l'authentification (T-012).

Intention (voir docs/questions/securite/limitation-authentification.md) :
- on ne compte que les ÉCHECS, en PostgreSQL (table loginAttempt) : aucune
  infrastructure ajoutée (pas de Redis) ;
- deux portées : le couple (IP, compte), avec verrou progressif (backoff), et
  l'IP seule, avec un plafond global indépendant du compte ;
- une IP déjà connue du titulaire (succès antérieur pour ce compte) ne subit pas
  le verrou par couple : le verrou ne bloque jamais un utilisateur légitime
  depuis son IP habituelle, et une attaque depuis une autre IP ne le touche pas ;
- les comptes inexistants sont comptés comme les autres : le 429 ne révèle pas
  l'existence d'un compte ;
- le journal de sécurité (logger zylo_office.security) ne contient ni mot de
  passe ni email en clair, seulement une empreinte tronquée.
"""

import hashlib
import ipaddress
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import LoginAttempt
from app.core.config import settings
from app.core.errors import AppError

security_logger = logging.getLogger("zylo_office.security")

ACTION_LOGIN = "login"
ACTION_REGISTER = "register"
ACTION_REFRESH = "refresh"

PORTEE_COUPLE = "couple"
PORTEE_IP = "ip"

ISSUE_ECHEC = "failure"
ISSUE_SUCCES = "success"

MESSAGE_LIMITE = "Trop de tentatives. Réessayez plus tard."


def maintenant() -> datetime:
    """Horloge unique du module : les tests la remplacent pour simuler un délai."""
    return datetime.now(timezone.utc)


def _empreinte(*elements: str) -> str:
    return hashlib.sha256("|".join(elements).encode("utf-8")).hexdigest()


def _cle_couple(action: str, ip: str, email: str) -> str:
    return _empreinte(action, PORTEE_COUPLE, ip, email.strip().lower())


def _cle_ip(action: str, ip: str) -> str:
    return _empreinte(action, PORTEE_IP, ip)


def adresse_client(request: Request) -> str:
    """Adresse du client réel.

    X-Forwarded-For est lu seulement si le pair direct est un proxy de confiance.
    On parcourt la chaîne de droite à gauche (le proxy ajoute l'adresse à droite) :
    la première adresse qui n'est pas un proxy de confiance est le client. Une
    chaîne invalide retombe sur le pair direct, sans permettre de contourner le
    compteur par une valeur fantaisiste.
    """
    pair = request.client.host if request.client else "inconnue"
    proxies = set(settings.AUTH_RATE_LIMIT_TRUSTED_PROXIES)
    if pair not in proxies:
        return pair
    chaine = [element.strip() for element in request.headers.get("x-forwarded-for", "").split(",") if element.strip()]
    for candidate in reversed(chaine):
        if candidate in proxies:
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            return pair
        return candidate
    return pair


def _verrou_jusqua(nombre_echecs: int, dernier_echec: datetime, seuil: int) -> datetime | None:
    """Instant de fin du verrou, ou None si le seuil n'est pas atteint.

    Backoff : base x 2^(échecs au-delà du seuil), plafonné à la durée maximale.
    """
    if nombre_echecs < seuil:
        return None
    exposant = min(nombre_echecs - seuil, 30)
    duree = min(settings.AUTH_RATE_LIMIT_LOCK_BASE_SECONDS * (2**exposant), settings.AUTH_RATE_LIMIT_LOCK_MAX_SECONDS)
    return dernier_echec + timedelta(seconds=duree)


async def _echecs_recents(db: AsyncSession, cle: str, instant: datetime) -> tuple[int, datetime | None]:
    fenetre_debut = instant - timedelta(seconds=settings.AUTH_RATE_LIMIT_WINDOW_SECONDS)
    resultat = await db.execute(
        select(func.count(LoginAttempt.id), func.max(LoginAttempt.occurredAt)).where(
            LoginAttempt.keyHash == cle,
            LoginAttempt.outcome == ISSUE_ECHEC,
            LoginAttempt.occurredAt > fenetre_debut,
        )
    )
    nombre, dernier = resultat.one()
    return nombre or 0, dernier


async def _couple_connu(db: AsyncSession, cle: str) -> bool:
    resultat = await db.execute(
        select(LoginAttempt.id).where(LoginAttempt.keyHash == cle, LoginAttempt.outcome == ISSUE_SUCCES).limit(1)
    )
    return resultat.first() is not None


@dataclass(frozen=True)
class _Controle:
    cle: str
    portee: str
    seuil: int


async def verifie_limites(db: AsyncSession, request: Request, action: str, email: str | None) -> None:
    """Lève AppError 429 si une portée est verrouillée. Ne lève rien sinon."""
    if not settings.AUTH_RATE_LIMIT_ENABLED:
        return
    ip = adresse_client(request)
    instant = maintenant()

    controles = [_Controle(_cle_ip(action, ip), PORTEE_IP, settings.AUTH_RATE_LIMIT_MAX_FAILURES_PER_IP)]
    if email is not None:
        cle_couple = _cle_couple(action, ip, email)
        # Une IP déjà connue du titulaire n'est pas soumise au verrou par couple.
        if not await _couple_connu(db, cle_couple):
            controles.append(
                _Controle(cle_couple, PORTEE_COUPLE, settings.AUTH_RATE_LIMIT_MAX_FAILURES_PER_ACCOUNT)
            )

    for controle in controles:
        nombre, dernier = await _echecs_recents(db, controle.cle, instant)
        if dernier is None:
            continue
        jusqua = _verrou_jusqua(nombre, dernier, controle.seuil)
        if jusqua is None or instant >= jusqua:
            continue
        attente = max(1, int((jusqua - instant).total_seconds() + 0.999))
        security_logger.warning(
            "auth_rate_limited",
            extra={"action": action, "portee": controle.portee, "ip": ip, "cle": controle.cle[:12], "attente_s": attente},
        )
        raise AppError(
            code="rate_limited",
            message=MESSAGE_LIMITE,
            status_code=429,
            headers={"Retry-After": str(attente)},
        )


async def enregistre_echec(db: AsyncSession, request: Request, action: str, email: str | None) -> None:
    """Compte un échec pour l'IP et, si fourni, pour le couple (IP, compte).

    Appelé même quand la limite est désactivée, pour que la réactivation prenne
    immédiatement en compte les échecs récents. Purge les échecs hors fenêtre
    pour ces mêmes clés, afin que la table reste bornée.
    """
    ip = adresse_client(request)
    instant = maintenant()
    portees = [(_cle_ip(action, ip), PORTEE_IP)]
    if email is not None:
        portees.append((_cle_couple(action, ip, email), PORTEE_COUPLE))

    for cle, portee in portees:
        db.add(LoginAttempt(action=action, scope=portee, keyHash=cle, outcome=ISSUE_ECHEC, occurredAt=instant))
    await db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.keyHash.in_([cle for cle, _ in portees]),
            LoginAttempt.outcome == ISSUE_ECHEC,
            LoginAttempt.occurredAt < instant - timedelta(seconds=settings.AUTH_RATE_LIMIT_WINDOW_SECONDS),
        )
    )
    await db.commit()
    security_logger.warning("auth_failure", extra={"action": action, "ip": ip, "portee": PORTEE_COUPLE if email else PORTEE_IP})


async def enregistre_succes(db: AsyncSession, request: Request, action: str, email: str) -> None:
    """Après un succès : remet à zéro les échecs du couple et mémorise l'IP connue."""
    ip = adresse_client(request)
    cle = _cle_couple(action, ip, email)
    await db.execute(delete(LoginAttempt).where(LoginAttempt.keyHash == cle, LoginAttempt.outcome == ISSUE_ECHEC))
    if not await _couple_connu(db, cle):
        db.add(
            LoginAttempt(
                action=action,
                scope=PORTEE_COUPLE,
                keyHash=cle,
                outcome=ISSUE_SUCCES,
                occurredAt=maintenant(),
            )
        )
    await db.commit()
