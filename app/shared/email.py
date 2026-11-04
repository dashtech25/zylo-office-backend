"""Abstraction d'envoi d'e-mails (T-021, T-049, réinitialisation compte).

Intention : le module métier ne connaît que `send_message(...)`. Le choix du
canal (fournisseur SMTP ou API) reste réversible. Un adaptateur SMTP standard
library est disponible en production derrière une configuration explicite;
aucun fournisseur, compte ni secret n'est intégré au code.

- `none` (défaut) : aucun envoi. Les flux qui en dépendent (création de compte)
  sont refusés avant toute écriture (503 `user_creation_disabled`).
- `console` : écrit le message sur la sortie standard. Il contient le lien
  d'activation, donc un secret : admis uniquement en `ENVIRONMENT=development`
  (vérifié dans app/core/config.py).
- `memory` : boîte en mémoire, lue par les tests. Admis uniquement en `test`.
- `smtp` : SMTP avec STARTTLS, obligatoire en production pour réellement
  envoyer invitations/récupérations. Host, port, nom, secret et expéditeur
  viennent exclusivement de variables d'environnement.

La récupération répond avec un texte neutre même si `none` est configuré; dans
ce cas aucun jeton n'est créé et aucun message n'est prétendu livré.
"""

import logging
import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage as MimeEmailMessage
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger("zylo_office.email")


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Développement uniquement : la sortie standard reçoit le lien d'activation."""

    async def send(self, message: EmailMessage) -> None:
        print(f"[e-mail de développement] à={message.to} sujet={message.subject}\n{message.body}", flush=True)


class MemoryEmailSender:
    """Test uniquement : conserve les messages pour les assertions."""

    def __init__(self) -> None:
        self._messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self._messages.append(message)

    def messages(self) -> list[EmailMessage]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()


class SmtpEmailSender:
    """Transport SMTP production avec TLS explicite, sans journaliser le contenu."""

    def __init__(self) -> None:
        self._host = settings.EMAIL_SMTP_HOST
        self._port = settings.EMAIL_SMTP_PORT
        self._username = settings.EMAIL_SMTP_USERNAME
        self._password = (
            settings.EMAIL_SMTP_PASSWORD.get_secret_value() if settings.EMAIL_SMTP_PASSWORD is not None else None
        )
        self._from = settings.EMAIL_SMTP_FROM_ADDRESS
        self._timeout = settings.EMAIL_SMTP_TIMEOUT_SECONDS

    async def send(self, message: EmailMessage) -> None:
        # smtplib est bloquant; l'envoi ne doit pas immobiliser la boucle ASGI.
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: EmailMessage) -> None:
        if not all((self._host, self._username, self._password, self._from)):
            # La validation Settings devrait rendre ce cas inaccessible. Garder
            # une garde locale évite toutefois une connexion SMTP ouverte.
            raise RuntimeError("SMTP transport is not fully configured")

        mime = MimeEmailMessage()
        mime["From"] = self._from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.body)

        context = ssl.create_default_context()
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as transport:
            transport.ehlo()
            transport.starttls(context=context)
            transport.ehlo()
            transport.login(self._username, self._password)
            transport.send_message(mime)


_memoire = MemoryEmailSender()


def memory_outbox() -> list[EmailMessage]:
    """Liste vivante des messages envoyés (EMAIL_BACKEND=memory uniquement).
    Les tests la lisent et la vident avec `.clear()`."""
    return _memoire._messages


def get_email_sender() -> EmailSender | None:
    """Adaptateur configuré, ou None si l'envoi n'est pas configuré."""
    backend = settings.EMAIL_BACKEND
    if backend == "console":
        return ConsoleEmailSender()
    if backend == "memory":
        return _memoire
    if backend == "smtp":
        return SmtpEmailSender()
    return None
