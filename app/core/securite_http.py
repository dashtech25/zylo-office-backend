"""Durcissement de la surface HTTP de l'API (T-015).

Deux éléments, volontairement petits :

- `options_documentation` : Swagger (`/docs`), ReDoc (`/redoc`) et le schéma
  OpenAPI (`/openapi.json`) ne sont montés qu'en `ENVIRONMENT=development`.
  Intention : cartographier l'API (BCK-014) n'a aucun intérêt en production et
  offre un inventaire complet à un attaquant. Le défaut de `app/core/config.py`
  est `production` : sans variable, la documentation est donc fermée.

- `EnTetesSecuriteMiddleware` : en-têtes de sécurité ajoutés à chaque réponse
  HTTP, uniquement s'ils ne sont pas déjà posés par la route (ex. un téléchargement
  qui fixerait son propre en-tête). Intention : limiter le sniffing de type MIME
  (`nosniff`), le clickjacking (`X-Frame-Options`) et la fuite du chemin complet
  vers des tiers (`Referrer-Policy`).

  Volontairement absents : une CSP. Une CSP `default-src 'none'` bloquerait les
  images (avatars, miniatures) que le frontend charge depuis l'API ; le durcissement
  des fichiers téléchargés (type actif, `Content-Disposition`) relève de T-014.

ASGI pur (comme `RequestIdMiddleware`), pour ne pas bufferiser les réponses en
flux (SSE de `/trucks/live-positions`).
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

ENVIRONMENT_DEVELOPPEMENT = "development"

EN_TETES_SECURITE: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
)


def options_documentation(environment: str) -> dict[str, str | None]:
    """Arguments `docs_url`, `redoc_url`, `openapi_url` pour FastAPI.

    Hors `development` (y compris valeur absente ou inconnue) : toutes à None,
    donc aucune route de documentation n'est enregistrée. Fail-closed, comme
    le reste de la configuration.
    """
    if environment == ENVIRONMENT_DEVELOPPEMENT:
        return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


class EnTetesSecuriteMiddleware:
    """Ajoute EN_TETES_SECURITE aux réponses HTTP, sans écraser un en-tête déjà posé."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                presents = {nom.lower() for nom, _ in headers}
                for nom, valeur in EN_TETES_SECURITE:
                    if nom not in presents:
                        headers.append((nom, valeur))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
