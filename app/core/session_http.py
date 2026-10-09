"""Transport HTTP des sessions : cookies, jeton CSRF et contrôle d'origine (T-037a).

Trois cookies, un rôle chacun :

- `zylo_access` : jeton d'accès (JWT). HttpOnly, chemin `/` (lu par toute l'API).
- `zylo_refresh` : jeton de rafraîchissement. HttpOnly, chemin `/api/v1/auth` :
  il n'accompagne que les routes d'authentification, jamais le reste de l'API.
- `zylo_csrf` : jeton CSRF, volontairement lisible par l'interface (il ne donne
  aucun accès). Double soumission : l'interface le recopie dans l'en-tête
  `X-CSRF-Token` sur chaque requête non sûre.

Pourquoi double soumission et pas seulement SameSite : `SameSite=Lax` bloque déjà
la plupart des envois inter-sites, mais pas ceux d'un sous-domaine compromis ni
les navigateurs anciens. La vérification d'`Origin` ferme le reste. Cette
combinaison suit la recommandation vérifiée de
docs/architecture/bonnes-pratiques/securite-rbac-multitenant.md (R10).

Ce module ne connaît aucun module métier : il est utilisé par app/core/security.py
et app/auth/router.py.
"""

import hmac
import secrets
from datetime import datetime, timezone

from fastapi import Request, Response

from app.core.config import settings
from app.core.errors import AppError

NOM_COOKIE_ACCES = "zylo_access"
NOM_COOKIE_RAFRAICHISSEMENT = "zylo_refresh"
NOM_COOKIE_CSRF = "zylo_csrf"
ENTETE_CSRF = "X-CSRF-Token"

# Préfixe des routes d'authentification : API_PREFIX (/api/v1) + /auth (app/main.py).
CHEMIN_AUTH = "/api/v1/auth"
METHODES_SURES = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def transition_active() -> bool:
    """Vrai tant que la date de fin de transition n'est pas passée.

    Intention : pendant la transition, les clients qui envoient encore
    `Authorization` ou `refreshToken` dans le corps continuent de fonctionner.
    Après, seuls les cookies comptent, et le corps des réponses ne porte plus de jeton.
    """
    return datetime.now(timezone.utc) < settings.AUTH_HEADER_ACCEPTED_UNTIL


def _attributs_communs() -> dict:
    return {
        "secure": settings.cookies_secure,
        "samesite": settings.AUTH_COOKIE_SAMESITE,
        "domain": settings.AUTH_COOKIE_DOMAIN,
    }


def pose_sessions(response: Response, acces: str, rafraichissement: str) -> str:
    """Pose les trois cookies de session et renvoie la valeur du jeton CSRF.

    Le jeton CSRF est renouvelé à chaque émission : une session volée ne garde
    pas un CSRF utilisable après une rotation.
    """
    csrf = secrets.token_urlsafe(32)
    communs = _attributs_communs()
    response.set_cookie(
        NOM_COOKIE_ACCES,
        acces,
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        httponly=True,
        **communs,
    )
    response.set_cookie(
        NOM_COOKIE_RAFRAICHISSEMENT,
        rafraichissement,
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path=CHEMIN_AUTH,
        httponly=True,
        **communs,
    )
    response.set_cookie(
        NOM_COOKIE_CSRF,
        csrf,
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path="/",
        httponly=False,
        **communs,
    )
    return csrf


def efface_sessions(response: Response) -> None:
    """Efface les cookies de session. Les attributs doivent correspondre à la pose
    (chemin, domaine, Secure, SameSite), sinon le navigateur garde l'original."""
    communs = _attributs_communs()
    response.delete_cookie(NOM_COOKIE_ACCES, path="/", httponly=True, **communs)
    response.delete_cookie(NOM_COOKIE_RAFRAICHISSEMENT, path=CHEMIN_AUTH, httponly=True, **communs)
    response.delete_cookie(NOM_COOKIE_CSRF, path="/", httponly=False, **communs)


def verifie_csrf_et_origine(request: Request) -> None:
    """Refuse une requête non sûre portée par cookie si elle n'est pas légitime.

    - Origine : si l'en-tête `Origin` est présent, il doit figurer dans
      CORS_ORIGINS. Un navigateur l'envoie sur toute requête inter-site non sûre.
    - Double soumission : le cookie `zylo_csrf` et l'en-tête `X-CSRF-Token`
      doivent exister et être identiques (comparaison à temps constant).

    Les méthodes sûres (GET, HEAD, OPTIONS) ne modifient rien et ne sont pas contrôlées.
    """
    if request.method in METHODES_SURES:
        return
    origine = request.headers.get("origin")
    if origine is not None and origine not in settings.CORS_ORIGINS:
        raise AppError(
            code="origin_refused",
            message="Requête refusée : origine non autorisée.",
            status_code=403,
        )
    cookie = request.cookies.get(NOM_COOKIE_CSRF)
    entete = request.headers.get(ENTETE_CSRF)
    if not cookie or not entete or not hmac.compare_digest(cookie.encode(), entete.encode()):
        raise AppError(
            code="csrf_invalid",
            message="Requête refusée : jeton de protection CSRF absent ou invalide.",
            status_code=403,
        )
