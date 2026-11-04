"""Vérification de l'état technique du service (BE-032).

Ce module porte la sonde de disponibilité de la base, utilisée par la route
`GET /api/v1/health/ready` (readiness). Il appartient au socle `core/` : il ne
connaît aucun module métier et n'importe que la session de base de données.

Contrat :

- `GET /api/v1/health` (liveness) ne touche pas la base : il répond `ok` tant
  que le processus répond. Il est défini dans `app/api/v1/endpoints/health.py`.
- `GET /api/v1/health/ready` appelle `base_repond` : `ready` si la base répond,
  `not ready` (HTTP 503) sinon. Un orchestrateur retire alors l'instance du
  trafic sans la redémarrer.

Garanties de sécurité :

- la réponse ne contient jamais le message d'erreur de la base : celui-ci peut
  citer une URL de connexion ou un hôte interne. Seul le booléen de la sonde
  sort de ce module ;
- la route est publique (aucune session, aucune organisation) : elle ne révèle
  aucune donnée, et ne doit donc pas dépendre de l'authentification, faute de
  quoi un orchestrateur ne pourrait pas la interroger.

Piège évité : la sonde ne doit pas laisser la session dans un état invalide
après un échec. Un `rollback` est donc émis avant de rendre la main, sans quoi
la transaction en erreur resterait ouverte dans le pool.
"""

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


async def base_repond(db: AsyncSession) -> bool:
    """Renvoie True si la base répond à un `SELECT 1`, False sinon.

    Les erreurs SQLAlchemy (connexion refusée, délai dépassé, base absente) et
    les erreurs réseau bas niveau (`OSError`, dont `ConnectionRefusedError`)
    donnent False. Toute autre exception remonte : elle signale un bug, pas une
    base indisponible, et ne doit pas être masquée en « not ready ».
    """
    try:
        await db.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        await db.rollback()
        return False
    return True
