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
    "require_any_permission",
    "require_module_permission",
    "require_module_active",
    "require_organization_member",
    "get_current_organization_id",
)
# Gardes de permission : exigent un code de permission précis.
PREFIXES_PERMISSION = ("require_permission", "require_any_permission", "require_module_permission")
# Les routes support plateforme ont un périmètre d'accès distinct des rôles
# tenant : elles exigent l'utilisateur courant ET l'allowlist opérateur.
PREFIXES_GARDE_OPERATEUR = ("require_operator",)
# Préfixe des routes d'un module métier (CLAUDE.md : un dossier par module).
PREFIXES_MODULE = ("/api/v1/zylo-liquid", "/api/v1/zylo-tanker")

# Routes publiques ou authentifiées SANS appartenance à une organisation.
# Chaque entrée est justifiée et datée (2026-10-09). Toute route nouvelle sans
# garde doit être ajoutée ici après revue, avec sa justification.
ROUTES_PUBLIQUES: dict[str, str] = {
    # --- Publiques par nature (aucune donnée d'organisation) ---
    "GET /": "Racine d'accueil, aucune donnée. 2026-10-09.",
    "GET /api/v1/health": "Sonde de santé. 2026-10-09.",
    "GET /api/v1/health/ready": "Sonde de disponibilité : état de la base seulement, sans donnée ni secret (BE-032). 2026-11-03.",
    "GET /api/v1/health/error-demo": "Démonstration du format d'erreur, sans donnée. A retirer en production. 2026-10-09.",
    "POST /api/v1/auth/register": "Endpoint masqué par défaut; AUTH_PUBLIC_REGISTRATION_ENABLED=true n'est admis que si ENVIRONMENT=development ou test (le validateur Settings refuse production/staging). Libre-service sans décision produit réservé aux tests et au développement local. 2026-11-02.",
    "POST /api/v1/auth/login": "Connexion : public par nature, limitée par T-012. 2026-10-09.",
    "POST /api/v1/auth/activate": "Activation d'un compte par jeton à usage unique reçu hors API (T-021) : jeton vérifié et consommé dans le service, limitée par T-012. 2026-10-09.",
    "POST /api/v1/auth/refresh": "Rafraîchissement par jeton de session, sans organisation. 2026-10-09.",
    "POST /api/v1/auth/logout": "Révocation par jeton de session, sans organisation. 2026-10-09.",
    "GET /api/v1/auth/me": "Profil de l'utilisateur connecté (portée utilisateur uniquement). 2026-10-09.",
    "POST /api/v1/auth/change-password": "Changement de mot de passe de l'utilisateur connecté (portée utilisateur uniquement). 2026-10-09.",
    # --- Portée utilisateur : contrôle dans le service ---
    "GET /api/v1/organizations": "Liste des organisations de l'utilisateur connecté (portée utilisateur). 2026-10-09.",
    "POST /api/v1/organizations": "Création d'organisation par tout utilisateur connecté. Quota ORG_CREATION_QUOTA à fixer par le client (T-019, décision en attente). 2026-10-09.",
    "PATCH /api/v1/users/{user_id}": "Photo de profil : soi-même, ou owner d'une organisation dont la cible est membre. Contrôle dans le service (update_user_profile). 2026-10-09.",
    "GET /api/v1/storage/local/{storage_reference}": "Téléchargement par URL signée (signature vérifiée dans le service). 2026-10-09.",
    # --- Catalogues : lecture seule, publics en attendant la décision IAM-020 ---
    "GET /api/v1/modules": "Catalogue des modules (aucune donnée d'organisation). Passera authentifié si la décision catalogues-publics est confirmée (IAM-020). 2026-10-09.",
    "GET /api/v1/billing/plans": "Catalogue de plans, lecture seule (création par API retirée par T-019, option A de T-050). Passera authentifié si IAM-020 est confirmée. 2026-10-09.",
    "GET /api/v1/billing/payment-provider": "Métadonnées statiques du provider de test (configured=false, checkoutAvailable=false), sans donnée tenant ni secret. 2026-11-02.",
    # --- Utilitaires authentifiés, sans lecture ni écriture en base ---
    "POST /api/v1/export/xlsx": "Conversion d'un tableau fourni par l'appelant, authentifiée (get_current_user), sans accès à la base. 2026-10-09.",
    "POST /api/v1/export/docx": "Conversion d'un tableau fourni par l'appelant, authentifiée (get_current_user), sans accès à la base. 2026-10-09.",
    "POST /api/v1/import/xlsx": "Lecture d'un fichier fourni par l'appelant, authentifiée (get_current_user), sans accès à la base. 2026-10-09.",
    "GET /api/v1/notifications/vapid-public-key": "Clé publique VAPID (non secrète), lue avant tout abonnement, aucune donnée d'organisation. 2026-10-09 (T-004b lot 2).",
    "GET /api/v1/account/profile": "Profil de l'utilisateur de la session uniquement (get_current_user, aucun identifiant lu dans la requête). Portée utilisateur. BE-020.",
    "POST /api/v1/auth/password-reset/request": "Demande de réinitialisation par adresse, publique par nature ; réponse uniforme, limitée par T-012.",
    "POST /api/v1/auth/password-reset/confirm": "Confirmation par jeton à usage unique reçu hors API, vérifié et consommé dans le service ; limitée par T-012.",
    "GET /api/v1/internal/ready": "Readiness réservée au réseau interne : 404 hors HEALTH_INTERNAL_NETWORKS (contrôle dans la route, sans session). BE-032.",
}

# Routes sans dépendance FastAPI dont le contrôle de sécurité est effectué
# explicitement dans le handler/service. Les classer comme publiques serait
# trompeur : le webhook exige une signature HMAC avant toute lecture/écriture.
ROUTES_GARDEES_MANUELLEMENT: dict[str, str] = {
    "POST /api/v1/billing/webhooks/flutterwave": "Signature Flutterwave verif-hash comparée en temps constant avant lecture du payload ou accès aux événements; secret absent -> 503, signature invalide -> 401. 2026-11-02.",
    "POST /api/v1/zylo-liquid/gps/ingest": "Secret d'ingestion propre à l'organisation dans X-GPS-Ingest-Secret, vérifié en service avant traitement; absence/invalide -> 401. 2026-10-09.",
    "POST /api/v1/zylo-tanker/gps/ingest": "Secret d'ingestion propre à l'organisation dans X-GPS-Ingest-Secret, vérifié en service avant traitement; absence/invalide -> 401. 2026-10-09.",
}


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str
    name: str
    appartenance: bool
    permissions: tuple[str, ...]
    garde_operateur: bool
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
        garde_operateur = any(n.split(".")[0].startswith(PREFIXES_GARDE_OPERATEUR) for n in noms)
        permissions = []
        for call in appels:
            if call is None:
                continue
            if getattr(call, "__qualname__", "").split(".")[0].startswith(PREFIXES_PERMISSION):
                # `permission_code` (une permission) ou `permission_codes` (l'une d'elles).
                for variable in ("permission_code", "permission_codes"):
                    if variable in call.__code__.co_freevars:
                        index = call.__code__.co_freevars.index(variable)
                        valeur = call.__closure__[index].cell_contents
                        permissions.extend([valeur] if isinstance(valeur, str) else list(valeur))
        for methode in sorted(route.methods):
            infos.append(
                RouteInfo(
                    method=methode,
                    path=chemin,
                    name=route.name,
                    appartenance=appartenance,
                    permissions=tuple(sorted(set(permissions))),
                    garde_operateur=garde_operateur,
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
        elif not info.appartenance and not info.garde_operateur and info.cle not in ROUTES_GARDEES_MANUELLEMENT:
            justification = ROUTES_PUBLIQUES.get(info.cle, "NON CLASSÉE — revoir la garde avant livraison")
            sans.append(f"`{info.method} {info.path}` — {justification}")
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
    lignes += ["", "## Routes protégées par allowlist opérateur", ""]
    routes_operateur = [f"`{info.method} {info.path}`" for info in infos if info.garde_operateur]
    lignes += [f"- {r} — `require_operator` (session utilisateur + allowlist serveur `OPERATOR_READ_USER_IDS`)." for r in routes_operateur] or ["Aucune."]
    lignes += ["", "## Routes avec contrôle manuel documenté", ""]
    lignes += [f"- `{cle}` — {raison}" for cle, raison in sorted(ROUTES_GARDEES_MANUELLEMENT.items())] or ["Aucune."]
    return "\n".join(lignes) + "\n"
