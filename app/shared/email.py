"""Abstraction d'envoi d'e-mails (T-021, T-049) — aucun transport réel ici.

Intention : le module métier ne connaît que `send_message(...)`. Le choix du
canal (fournisseur SMTP ou API) est une décision du client (question
`docs/questions/rbac/activation-compte.md`) : tant qu'il n'est pas pris, seuls
trois adaptateurs existent.

- `none` (défaut) : aucun envoi. Les flux qui en dépendent (création de compte)
  sont refusés avant toute écriture (503 `user_creation_disabled`).
- `console` : écrit le message sur la sortie standard. Il contient le lien
  d'activation, donc un secret : admis uniquement en `ENVIRONMENT=development`
  (vérifié dans app/core/config.py).
- `memory` : boîte en mémoire, lue par les tests. Admis uniquement en `test`.

Un adaptateur de production (SMTP ou fournisseur) s'ajoute ici, derrière un
nouveau nom de `EMAIL_BACKEND`, sans toucher aux appelants.
"""

import logging
from dataclasses import dataclass
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
    return None
