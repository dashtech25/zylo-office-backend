"""Journalisation structurée de l'application (BE-224).

Ce module fournit :

- le formateur JSON unique (`JsonFormatter`), qui émet pour chaque ligne le
  `requestId` et le `correlationId` de la requête en cours ;
- le filtre de redaction (`FiltreRedaction`), installé sur le gestionnaire
  stdout par `setup_logging()`, qui retire les secrets et les courriels ;
- la pseudonymisation des identifiants de tenant (`pseudonyme_tenant`) ;
- le contrôle de lecture des journaux (`exige_lecture_journaux`), qui refuse
  avec 403 sans la permission `PERMISSION_LECTURE_JOURNAUX`.

Deux identifiants distincts circulent par contextvars :

- `request_id_ctx` : identifiant d'une requête HTTP (X-Request-Id) ;
- `correlation_id_ctx` : identifiant de corrélation d'un traitement de bout en
  bout (X-Correlation-Id), repris par les tâches asynchrones créées pendant la
  requête et par les appels d'intégration. Sans X-Correlation-Id valide, il
  vaut le request_id, ce qui garde le contrat BE-001.

Aucun module ne configure son propre logger : tout passe par `setup_logging()`.
"""

import hashlib
import hmac
import json
import logging
import re
import sys
from contextvars import ContextVar

from app.core.config import settings

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Permission nominative de lecture des journaux (format domaine.entite.action).
# Elle n'est accordée qu'à l'opérateur habilité ; voir exige_lecture_journaux().
PERMISSION_LECTURE_JOURNAUX = "journal.log.read"

# Clés d'enregistrement (extra) dont la valeur n'est jamais journalisée.
_CLES_SENSIBLES = frozenset(
    {"password", "mot_de_passe", "token", "secret", "authorization", "cookie", "api_key", "apikey"}
)
# Clés d'enregistrement (extra) qui portent un identifiant de tenant.
_CLES_TENANT = frozenset({"tenantId", "tenant_id"})
# Motif « clé=valeur » d'un secret dans un texte de message : la valeur est masquée.
_MOTIF_SECRET_TEXTE = re.compile(
    r"(?i)(password|mot_de_passe|token|secret|authorization|cookie|api[_-]?key)(\s*[=:]\s*)(\S+)"
)
# Motif d'une adresse de courriel, traitée comme donnée personnelle (PII).
_MOTIF_COURRIEL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_VALEUR_MASQUEE = "***"
_COURRIEL_MASQUE = "<courriel masqué>"

# Attributs standard d'un LogRecord : tout autre attribut présent vient de `extra`.
_ATTRIBUTS_STANDARD = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
) | {"message", "asctime"}


def pseudonyme_tenant(tenant_id: str) -> str:
    """Retourne le pseudonyme stable d'un identifiant de tenant pour les journaux.

    HMAC-SHA256 du tenant, clé dérivée du secret JWT, tronquée à 16 caractères
    hexadécimaux. Un même tenant donne toujours le même pseudonyme (les traces
    restent regroupables), sans que l'identifiant brut n'apparaisse dans les
    journaux plateforme. Le pseudonyme change si le secret JWT est remplacé,
    ce qui est voulu lors d'une rotation."""
    cle = hashlib.sha256(f"zylo-office-journal-tenant:{settings.JWT_SECRET}".encode()).digest()
    return hmac.new(cle, str(tenant_id).encode(), hashlib.sha256).hexdigest()[:16]


def _redige_texte(texte: str) -> str:
    """Masque les valeurs de secrets « clé=valeur » et les courriels d'un texte."""
    texte = _MOTIF_SECRET_TEXTE.sub(lambda m: f"{m.group(1)}{m.group(2)}{_VALEUR_MASQUEE}", texte)
    return _MOTIF_COURRIEL.sub(_COURRIEL_MASQUE, texte)


class FiltreRedaction(logging.Filter):
    """Filtre de redaction appliqué à chaque enregistrement avant formatage.

    - le message est rendu (arguments %s inclus) puis débarrassé des valeurs
      de secrets « password=… », « token=… » et des courriels ; les arguments
      sont vidés pour qu'aucun formateur ne les réinjecte ;
    - les champs `extra` nommés comme un secret (mot de passe, jeton, cookie,
      en-tête d'autorisation…) sont remplacés par `***` ;
    - les champs `extra` de tenant sont remplacés par leur pseudonyme ;
    - les champs `extra` textuels passent par la même redaction de texte.

    Le filtre ne lève jamais d'exception : un enregistrement non redigeable
    reste émis, la sécurité ne doit pas couper la journalisation."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = _redige_texte(record.getMessage())
            record.args = ()
            for cle in list(vars(record)):
                if cle in _ATTRIBUTS_STANDARD:
                    continue
                valeur = getattr(record, cle)
                if cle.lower() in _CLES_SENSIBLES:
                    setattr(record, cle, _VALEUR_MASQUEE)
                elif cle in _CLES_TENANT and valeur is not None:
                    setattr(record, cle, pseudonyme_tenant(valeur))
                elif isinstance(valeur, str):
                    setattr(record, cle, _redige_texte(valeur))
        except Exception:  # noqa: BLE001 - la journalisation ne doit jamais échouer
            pass
        return True


class JsonFormatter(logging.Formatter):
    """Formatteur JSON unique pour tous les logs de l'application — aucun module
    ne doit configurer son propre logger, tous passent par setup_logging().

    Chaque ligne porte `requestId` et `correlationId`, et `tenantId` (pseudonyme)
    si l'événement en porte un. Les autres champs `extra` ne sont pas
    sérialisés : un événement qui doit être cherché dans le message met ses
    valeurs en clé=valeur dans le texte."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            # Les exceptions 500 sont journalisées par le gestionnaire
            # Starlette externe après la réinitialisation de la contextvar.
            # Le handler leur passe alors l'ID récupéré depuis request.state.
            "requestId": getattr(record, "request_id", None) or request_id_ctx.get(),
            "correlationId": getattr(record, "correlation_id", None) or correlation_id_ctx.get(),
        }
        # Seul champ `extra` sérialisé : le tenant, déjà pseudonymisé par
        # FiltreRedaction. Un identifiant brut ne peut donc pas sortir ici.
        if getattr(record, "tenantId", None) is not None:
            payload["tenantId"] = record.tenantId
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """Installe le formateur JSON et le filtre de redaction sur stdout.

    Remplace les gestionnaires du logger racine. Le niveau est DEBUG en
    développement, INFO ailleurs. Appelée une seule fois, à l'import de
    app/main.py (les tests qui l'appellent restaurent le racine après)."""
    level = logging.DEBUG if settings.ENVIRONMENT == "development" else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(FiltreRedaction())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]


def exige_lecture_journaux(permissions: set[str] | frozenset[str]) -> None:
    """Refuse la lecture des journaux sans la permission `PERMISSION_LECTURE_JOURNAUX`.

    Lève `AppError` 403 (code `permission_denied`) et journalise le refus dans
    `zylo_office.security`. Ne décide pas seule l'autorisation générale : elle
    vérifie la permission déjà résolue par le moteur RBAC de l'appelant."""
    if PERMISSION_LECTURE_JOURNAUX in permissions:
        return
    # Import local : app.core.errors importe ce module pour request_id_ctx.
    from app.core.errors import AppError

    logging.getLogger("zylo_office.security").warning("lecture_journaux_refusee")
    raise AppError(
        "permission_denied",
        "Permission de lecture des journaux requise.",
        status_code=403,
    )
