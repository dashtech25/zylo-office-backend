"""Pagination des listes de l'API (BE-191).

Deux mécanismes coexistent, sans rupture pour les listes déjà en service :

- `PaginationParams` + `paginate()` : décalage (`limit`/`offset`), réponse
  `Page` avec `total`. Conservé pour les listes existantes (QE-API-36) : les
  remplacer changerait leur réponse.
- `PaginationCurseur` + `paginate_curseur()` : curseur opaque (`cursor`/`limit`),
  réponse `PageCurseur` avec `next_cursor`. Pour les nouvelles listes.

Contrat du curseur :

- ordre déterministe : la clé de tri doit se terminer par une colonne unique
  (l'identifiant), sinon deux lignes à valeur égale pourraient alterner entre
  pages ; l'ordre est croissant ;
- opaque : les valeurs de la clé sont signées (HMAC-SHA256, clé dérivée de
  JWT_SECRET) ; un curseur altéré est refusé (400) ;
- lié au tenant : le curseur porte le tenant d'origine ; le présenter pour un
  autre tenant renvoie 404, sans révéler l'existence de la ressource.

Le curseur ne contient aucun secret : seulement l'identifiant du tenant et les
valeurs de la clé de tri de la dernière ligne lue.

Les bornes de `limit` (défaut 20, minimum 1, maximum 100, QE-API-17) sont
vérifiées ici et renvoient 400 (`limite_hors_bornes`), comme le veut BE-191 ;
`PaginationParams` garde son 422 existant.

Documentation de module : chemin NON DÉFINI (QE-API-02), docstrings seules.
"""

import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi import Query
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql import Select

from app.core.config import settings
from app.core.errors import AppError
from app.shared.schemas import Page, PageCurseur, PageCurseurMeta, PageMeta

LIMIT_DEFAUT = 20
LIMIT_MIN = 1
LIMIT_MAX = 100

_PREFIXE_CLE = b"pagination-curseur|"


class PaginationParams:
    """Dépendance FastAPI générique — tout endpoint de liste du socle ou d'un
    futur module doit l'utiliser plutôt que de redéfinir limit/offset."""

    def __init__(self, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        self.limit = limit
        self.offset = offset


class PaginationCurseur:
    """Dépendance FastAPI pour les listes par curseur (BE-191).

    `limit` absent vaut 20. Une valeur hors de [1, 100] lève `AppError` 400
    (code `limite_hors_bornes`) : le contrôle se fait ici et non par `Query(le=)`,
    qui renverrait un 422. `cursor` absent = première page ; un curseur invalide
    est refusé à la lecture de la page, par `paginate_curseur`.
    """

    def __init__(self, limit: int | None = Query(None), cursor: str | None = Query(None)):
        if limit is None:
            limit = LIMIT_DEFAUT
        if not LIMIT_MIN <= limit <= LIMIT_MAX:
            raise AppError(
                "limite_hors_bornes",
                f"Le paramètre limit doit être compris entre {LIMIT_MIN} et {LIMIT_MAX}.",
                status_code=400,
                field_errors={"limit": [f"doit être entre {LIMIT_MIN} et {LIMIT_MAX}"]},
            )
        self.limit = limit
        self.cursor = cursor


def _signature(corps: bytes) -> str:
    """HMAC-SHA256 du corps, clé dérivée de JWT_SECRET (aucune nouvelle variable)."""
    cle = hashlib.sha256(_PREFIXE_CLE + settings.JWT_SECRET.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(hmac.new(cle, corps, hashlib.sha256).digest()).decode("ascii").rstrip("=")


def _serialiser_valeur(valeur: Any) -> list[str]:
    """Étiquette chaque valeur de clé par son type, pour la relire à l'identique."""
    if isinstance(valeur, datetime):
        return ["dt", valeur.isoformat()]
    if isinstance(valeur, uuid.UUID):
        return ["uuid", str(valeur)]
    if isinstance(valeur, bool):
        raise TypeError("Valeur booléenne non prévue dans une clé de tri.")
    if isinstance(valeur, int):
        return ["int", str(valeur)]
    if isinstance(valeur, str):
        return ["str", valeur]
    raise TypeError(f"Type non prévu dans une clé de tri : {type(valeur).__name__}.")


def _deserialiser_valeur(etiquette: str, texte: str) -> Any:
    if etiquette == "dt":
        return datetime.fromisoformat(texte)
    if etiquette == "uuid":
        return uuid.UUID(texte)
    if etiquette == "int":
        return int(texte)
    if etiquette == "str":
        return texte
    raise ValueError("étiquette inconnue")


def encoder_curseur(tenant_id: uuid.UUID, valeurs: Sequence[Any]) -> str:
    """Produit le curseur opaque : `<charge>.<signature>`, charge = JSON encodé en
    base64 url, contenant le tenant et les valeurs de la clé de tri."""
    charge = {"t": str(tenant_id), "k": [_serialiser_valeur(v) for v in valeurs]}
    corps = json.dumps(charge, separators=(",", ":")).encode("utf-8")
    partie = base64.urlsafe_b64encode(corps).decode("ascii").rstrip("=")
    return f"{partie}.{_signature(partie.encode('ascii'))}"


def decoder_curseur(curseur: str, tenant_id: uuid.UUID) -> list[Any]:
    """Vérifie la signature puis le tenant, et renvoie les valeurs de la clé.

    Signature absente ou fausse, ou charge illisible : 400 (`curseur_invalide`).
    Curseur valide mais émis pour un autre tenant : 404 (`curseur_introuvable`),
    même réponse qu'une ressource absente.
    """
    invalide = AppError("curseur_invalide", "Le curseur de pagination est invalide.", status_code=400)
    partie, sep, signature = curseur.partition(".")
    if not sep or not hmac.compare_digest(signature, _signature(partie.encode("ascii", "replace"))):
        raise invalide
    try:
        charge = json.loads(base64.urlsafe_b64decode(partie + "=" * (-len(partie) % 4)))
        if charge["t"] != str(tenant_id):
            raise AppError("curseur_introuvable", "Page introuvable.", status_code=404)
        return [_deserialiser_valeur(etiquette, texte) for etiquette, texte in charge["k"]]
    except AppError:
        raise
    except (ValueError, KeyError, TypeError):
        raise invalide


async def paginate_curseur(
    db: AsyncSession,
    stmt: Select,
    params: PaginationCurseur,
    schema,
    tenant_id: uuid.UUID,
    colonnes_tri: Sequence[InstrumentedAttribute],
) -> PageCurseur:
    """Lit une page par curseur (keyset) de `stmt`.

    - `stmt` doit déjà filtrer le tenant ; `colonnes_tri` est la clé de tri, dont
      la dernière colonne est unique (ex. `(createdAt, id)`) ; ordre croissant.
    - On lit `limit + 1` lignes pour savoir s'il reste une page sans second
      comptage. `next_cursor` encode la clé de la dernière ligne rendue.
    - Un curseur de page suivante ne contient pas de `total` : il n'est pas
      garanti stable si des lignes sont ajoutées entre deux pages.
    """
    cles = tuple(colonnes_tri)
    requete = stmt.order_by(*cles)
    if params.cursor is not None:
        valeurs = decoder_curseur(params.cursor, tenant_id)
        if len(valeurs) != len(cles):
            raise invalide
        requete = requete.where(tuple_(*cles) > tuple_(*valeurs))
    result = await db.execute(requete.limit(params.limit + 1))
    lignes = result.scalars().all()
    a_suivant = len(lignes) > params.limit
    lignes = lignes[: params.limit]
    suivant = None
    if a_suivant and lignes:
        derniere = lignes[-1]
        suivant = encoder_curseur(tenant_id, [getattr(derniere, c.key) for c in cles])
    return PageCurseur(
        data=[schema.model_validate(ligne) for ligne in lignes],
        meta=PageCurseurMeta(limit=params.limit, next_cursor=suivant),
    )


async def paginate(db: AsyncSession, stmt: Select, params: PaginationParams, schema) -> Page:
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(params.limit).offset(params.offset))
    rows = result.scalars().all()
    return Page(
        data=[schema.model_validate(row) for row in rows],
        meta=PageMeta(total=total or 0, limit=params.limit, offset=params.offset),
    )
