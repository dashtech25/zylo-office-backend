"""Inventaire des routes HTTP et de leurs gardes (T-023).

Intention : une seule lecture de l'application (`app.main.app`) qui sert aux
tests d'inventaire, à la matrice d'autorisation et au générateur de
documentation (`scripts/dev/generer_matrice_autorisation.py`). Aucune règle
de sécurité n'est décidée ici : ce module LIT les dépendances FastAPI.

Lecture des gardes : une dépendance est une garde si son nom de fabrique
(le premier segment de `__qualname__`) commence par un préfixe connu. La
permission exigée est lue dans la fermeture (`permission_code`), pas devinée
à partir du nom de la route.

Ce module ne contient aucun test (pas de préfixe `test_`).
"""

from dataclasses import dataclass

from fastapi.routing import APIRoute

# Gardes d'appartenance : prouvent que l'utilisateur est membre actif de
# l'organisation ciblée (ou qu'une garde de module/permission l'impose).
PREFIXES_APPARTENANCE = (
    "require_permission",
    "require_module_permission",
    "require_module_active",
    "require_organization_member",
    "get_current_organization_id",
)
# Gardes de permission : exigent un code de permission précis.
PREFIXES_PERMISSION = ("require_permission", "require_module_permission")
# Préfixe des routes d'un module métier (CLAUDE.md : un dossier par module).
PREFIXES_MODULE = ("/api/v1/zylo-liquid", "/api/v1/zylo-tanker")

# Routes publiques ou authentifiées SANS appartenance à une organisation.
# Chaque entrée est justifiée et datée (2026-10-09). Toute route nouvelle sans
# garde doit être ajoutée ici après revue, avec sa justification.
ROUTES_PUBLIQUES: dict[str, str] = {
    "GET /": "Racine d'accueil, aucune donnée. 2026-10-09.",
    "GET /api/v1/health": "Sonde de santé. 2026-10-09.",
    "GET /api/v1/health/error-demo": "Démonstration du format d'erreur, sans donnée. A retirer en production. 2026-10-09.",
    "POST /api/v1/auth/register": "Inscription : public par nature, limitée par T-012/T-013. 2026-10-09.",
    "POST /api/v1/auth/login": "Connexion : public par nature, limitée par T-012. 2026-10-09.",
    "POST /api/v1/auth/refresh": "Rafraîchissement par jeton de session, sans organisation. 2026-10-09.",
    "POST /api/v1/auth/logout": "Révocation par jeton de session, sans organisation. 2026-10-09.",
    "GET /api/v1/auth/me": "Profil de l'utilisateur connecté (portée utilisateur). 2026-10-09.",
    "POST /api/v1/auth/activate": "Activation d'un compte créé par une organisation : jeton à usage unique (256 bits, haché, expiration 72 h), seule preuve. Pas de limitation de débit dédiée : à traiter. 2026-10-09 (T-021).",
    "POST /api/v1/auth/change-password": "Changement de mot de passe de l'utilisateur connecté (portée utilisateur). 2026-10-09.",
    "GET /api/v1/organizations": "Liste des organisations de l'utilisateur connecté (portée utilisateur). 2026-10-09.",
    "POST /api/v1/organizations": "Création d'organisation par un utilisateur connecté ; quota à traiter par T-019 (valeur client). 2026-10-09.",
    "PATCH /api/v1/users/{user_id}": "Profil de l'utilisateur connecté, contrôle d'identité dans le service. A vérifier. 2026-10-09.",
    "GET /api/v1/modules": "Catalogue des modules. Passe authentifié si la décision catalogues-publics est confirmée (IAM-020). 2026-10-09.",
    "GET /api/v1/billing/plans": "Catalogue de plans. Passe authentifié si la décision catalogues-publics est confirmée (IAM-020). 2026-10-09.",
    "POST /api/v1/billing/plans": "DETTE CONNUE : tout utilisateur connecté peut créer un plan. Retrait de la route à faire par T-019. 2026-10-09.",
    "POST /api/v1/zylo-liquid/gps/ingest": "Webhook GPS : authentifié par le secret d'ingestion de l'organisation (en-tête). 2026-10-09.",
    "POST /api/v1/zylo-tanker/gps/ingest": "Webhook GPS : authentifié par le secret d'ingestion de l'organisation (en-tête). 2026-10-09.",
    "GET /api/v1/notifications/vapid-public-key": "Clé publique VAPID (non secrète), lue avant tout abonnement, aucune donnée d'organisation. 2026-10-09 (T-004b lot 2).",
    "POST /api/v1/export/xlsx": "Conversion de tableau fourni par l'appelant, sans donnée d'organisation. A vérifier. 2026-10-09.",
    "POST /api/v1/export/docx": "Conversion de tableau fourni par l'appelant, sans donnée d'organisation. A vérifier. 2026-10-09.",
    "POST /api/v1/import/xlsx": "Lecture d'un fichier fourni par l'appelant, sans donnée d'organisation. A vérifier. 2026-10-09.",
    "GET /api/v1/storage/local/{storage_reference}": "Téléchargement par URL signée (signature vérifiée dans le service). 2026-10-09.",
}


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str
    name: str
    appartenance: bool
    permissions: tuple[str, ...]
    module_routes: bool

    @property
    def cle(self) -> str:
        return f"{self.method} {self.path}"


def _dependances(dependant, acc: list) -> list:
    for sous in dependant.dependencies:
        acc.append(sous.call)
        _dependances(sous, acc)
    return acc


def _iter_routes(router, prefix: str = "", ctx_deps: tuple = ()):
    """Parcourt les routeurs imbriqués (FastAPI >= 0.14x : `_IncludedRouter`)."""
    for route in router.routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route, ctx_deps
        elif type(route).__name__ == "_IncludedRouter":
            ctx = route.include_context
            deps = tuple(ctx_deps) + tuple(getattr(d, "dependency", None) for d in (ctx.dependencies or []))
            yield from _iter_routes(ctx.included_router, prefix + ctx.prefix, deps)


def inventaire(app) -> list[RouteInfo]:
    infos: list[RouteInfo] = []
    for chemin, route, ctx_deps in _iter_routes(app.router):
        appels = _dependances(route.dependant, []) + list(ctx_deps)
        noms = [getattr(c, "__qualname__", "") for c in appels if c is not None]
        appartenance = any(n.split(".")[0].startswith(PREFIXES_APPARTENANCE) for n in noms)
        permissions = []
        for call in appels:
            if call is None:
                continue
            if getattr(call, "__qualname__", "").split(".")[0].startswith(PREFIXES_PERMISSION):
                if "permission_code" in call.__code__.co_freevars:
                    index = call.__code__.co_freevars.index("permission_code")
                    permissions.append(call.__closure__[index].cell_contents)
        for methode in sorted(route.methods):
            infos.append(
                RouteInfo(
                    method=methode,
                    path=chemin,
                    name=route.name,
                    appartenance=appartenance,
                    permissions=tuple(sorted(set(permissions))),
                    module_routes=chemin.startswith(PREFIXES_MODULE),
                )
            )
    return sorted(infos, key=lambda i: (i.path, i.method))


def matrice_markdown(infos: list[RouteInfo]) -> str:
    """Table permission -> routes, générée depuis le code (une source de vérité)."""
    par_permission: dict[str, list[str]] = {}
    sans: list[str] = []
    for info in infos:
        if info.permissions:
            for code in info.permissions:
                par_permission.setdefault(code, []).append(f"`{info.method} {info.path}`")
        elif not info.appartenance:
            sans.append(f"`{info.method} {info.path}`")
    lignes = [
        "# Matrice d'autorisation (T-023)",
        "",
        "Généré par `scripts/dev/generer_matrice_autorisation.py` : ne pas éditer à la main.",
        "Source : les dépendances FastAPI des routes (`tests/route_inventory.py`).",
        "",
        "## Permission -> routes",
        "",
        "| Permission | Routes |",
        "|---|---|",
    ]
    for code in sorted(par_permission):
        lignes.append(f"| `{code}` | {'<br>'.join(par_permission[code])} |")
    lignes += ["", "## Routes sans permission ni appartenance", ""]
    lignes += [f"- {r}" for r in sans] or ["Aucune."]
    return "\n".join(lignes) + "\n"
