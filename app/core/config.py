"""Configuration de l'application, chargée une fois à l'import (BE-221).

Source unique : la classe `Settings` (pydantic-settings). Ordre de lecture des
valeurs, du plus prioritaire au moins prioritaire : variables d'environnement du
processus, puis fichier `.env` du répertoire de lancement (absent en production,
où les variables sont injectées), puis valeur par défaut déclarée ci-dessous.
Une variable présente remplace entièrement la valeur par défaut.

Environnement : `ENVIRONMENT` vaut `production` par défaut. Seule la valeur exacte
`development` autorise les replis publics (`FALLBACK_*`). Toute autre valeur
applique les règles strictes (échec fermé, voir `ConfigurationSecretError`).

Paramètres (origine : variable d'environnement ; défaut ; NON DÉFINI si absent des
sources) :
- Application : `APP_NAME` (défaut « Zylo Office Backend »), `ENVIRONMENT`
  (défaut `production`), `PORT` (3002), `CORS_ORIGINS` (liste JSON ; défaut :
  frontend de développement 3001 et e2e 3055, jamais `*`).
- Base : `DATABASE_URL` (défaut local PostgreSQL 5432, mot de passe de repli
  refusé hors development). Dans les tests, `TEST_DATABASE_URL` est copiée dans
  `DATABASE_URL` par tests/conftest.py après garde de nom `zylo_t<NNN>_test`.
- Secrets sans valeur utilisable hors development : `JWT_SECRET`,
  `STORAGE_SIGNED_URL_SECRET` (au moins 32 caractères, pas le repli),
  `APP_FIELD_ENCRYPTION_KEY` (défaut vide, exigée hors development et test).
  Les valeurs ne sont jamais écrites dans les messages d'erreur.
- JWT : `JWT_ALGORITHM` (HS256), `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (15),
  `JWT_REFRESH_TOKEN_EXPIRE_DAYS` (30).
- Stockage : `STORAGE_BACKEND` (local), `STORAGE_LOCAL_ROOT` (./var/storage),
  `STORAGE_SIGNED_URL_TTL_SECONDS` (900), `STORAGE_S3_*` (NON DÉFINI : aucune
  valeur par défaut sauf bucket `zylo-office-documents` et région `us-east-1`).
- Intégration Holykell : `HOLYKELL_SYNC_BASE_URL` (vide = boucle désactivée),
  `HOLYKELL_SYNC_INTERVAL_SEC` (5).
- Balayage structurel : `STRUCTURAL_SWEEP_INTERVAL_SEC` (300).
- Web Push : `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` (vides = canal désactivé),
  `VAPID_CLAIMS_EMAIL`.
- Messagerie : `EMAIL_BACKEND` (none ; console réservé à development, memory à
  test, smtp à production), `EMAIL_SMTP_*` (NON DÉFINI hors smtp : aucune valeur
  par défaut), `ACTIVATION_URL_BASE`, `USER_INVITATION_TTL_HOURS` (72),
  `PASSWORD_RESET_URL_BASE`, `PASSWORD_RESET_TTL_MINUTES` (30, entre 1 et 60).
- Limitation d'authentification : `AUTH_RATE_LIMIT_*` (fenêtre 900 s, 10 échecs par
  compte, 100 par IP), `AUTH_RATE_LIMIT_TRUSTED_PROXIES` (vide : aucun proxy).
- Sessions : `AUTH_COOKIE_SECURE` (NON DÉFINI par défaut : Secure hors development),
  `AUTH_COOKIE_SAMESITE` (lax), `AUTH_COOKIE_DOMAIN` (NON DÉFINI : hôte exact),
  `AUTH_PUBLIC_REGISTRATION_ENABLED` (false ; true refusé hors development et test),
  `AUTH_HEADER_ACCEPTED_UNTIL` (2026-11-30, fuseau UTC obligatoire).

Documentation détaillée des usages : docs/process/configuration.md.
"""
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valeurs de repli : elles figurent dans le code et dans `.env.example`, donc
# publiques. Elles ne doivent jamais servir hors développement local.
FALLBACK_JWT_SECRET = "changeme-generate-a-real-random-secret"
FALLBACK_DB_PASSWORD = "changeme"

# Longueur minimale d'un secret de signature (HS256 : 256 bits, soit 32 octets).
SECRET_MIN_LENGTH = 32

# Seule valeur d'ENVIRONMENT qui autorise les replis. Toute autre valeur,
# absente comprise, applique les règles strictes (fail-closed).
ENVIRONMENT_DEVELOPPEMENT = "development"


class ConfigurationSecretError(RuntimeError):
    """Démarrage refusé : un secret est absent, de repli ou trop court.

    Intention : ce n'est volontairement pas une ValueError. Pydantic joint à
    une ValidationError la valeur d'entrée du modèle (donc les secrets lus
    depuis .env) ; une exception hors de ce cadre remonte telle quelle, avec
    seulement le nom des variables en cause.
    """


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Zylo Office Backend"
    # Durée de vie d'une prévisualisation de commande opérateur (BE-125). NON DÉFINI
    # (QE-ADM-07) : aucune valeur par défaut ; à None, la preview est refusée (503).
    ADMIN_PREVIEW_TTL_SECONDS: int | None = None
    # Locale des messages d'erreur (BE-256). NON DÉFINI (QE-EXP-23) : aucune
    # valeur par défaut ; à None, les textes de repli du code sont renvoyés.
    DEFAULT_LOCALE: str | None = None
    # Intention : le défaut est `production`. Une image ou un shell sans
    # variable applique les règles strictes ; les replis exigent un choix
    # explicite `development` (voir docs/process/configuration.md).
    ENVIRONMENT: str = "production"
    PORT: int = 3002
    # Origines autorisées par CORS. Configurable par variable d'environnement
    # (liste JSON, ex. CORS_ORIGINS=["http://localhost:3203"]) : une variable
    # présente remplace entièrement ce défaut. Le défaut couvre le frontend de
    # développement (3001) et le serveur e2e Playwright (3055).
    CORS_ORIGINS: list[str] = [
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        # Port dédié au serveur e2e Playwright (playwright.config.ts) —
        # sans ça, tout test e2e qui parle à un vrai backend (au lieu du
        # mock in-browser habituel) échoue au préflight CORS avant même
        # d'atteindre l'endpoint testé.
        "http://localhost:3055",
        "http://127.0.0.1:3055",
    ]

    # En local, DATABASE_URL pointe vers PostgreSQL local. Une fois déployé,
    # cette même variable doit pointer vers la base de données en ligne —
    # jamais d'URL codée en dur dans le code. Le mot de passe de repli est
    # refusé hors développement (voir le validateur ci-dessous).
    DATABASE_URL: str = "postgresql+asyncpg://zylo_office:changeme@localhost:5432/zylo_office"

    JWT_SECRET: str = FALLBACK_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Stockage documentaire (mission « vente-maintenant-reglementation »,
    # Phase 5 §2 : MinIO/S3-compatible retenu en cible ; "local" par défaut
    # en développement — même contrat d'interface (app/shared/storage.py),
    # jamais d'accès direct dispersé dans les modules métier.
    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_ROOT: str = "./var/storage"
    STORAGE_SIGNED_URL_SECRET: str = FALLBACK_JWT_SECRET
    # Clé de chiffrement des champs sensibles (T-027 l'utilise). Déclarée ici :
    # vide par défaut, obligatoire hors development et test (voir le validateur).
    APP_FIELD_ENCRYPTION_KEY: str = ""
    STORAGE_SIGNED_URL_TTL_SECONDS: int = 900
    # BE-173 (QE-PAR-07) : durée de rétention d'un export d'audit, en secondes. Aucune
    # valeur par défaut : sans configuration, une demande d'export est refusée (503).
    AUDIT_EXPORT_EXPIRATION_SECONDS: int | None = None
    STORAGE_S3_ENDPOINT_URL: str | None = None
    STORAGE_S3_BUCKET: str = "zylo-office-documents"
    STORAGE_S3_ACCESS_KEY: str | None = None
    STORAGE_S3_SECRET_KEY: str | None = None
    STORAGE_S3_REGION: str = "us-east-1"

    # Sondage continu de l'API Holykell (h-smartlink.com / simulateur en dev)
    # — Étape 2 de la refonte alertes (décision D1) : la boucle tourne DANS
    # ce process (app/modules/zylo_liquid/telemetry_sync.py, démarrée par
    # app/main.py), plus jamais dépendante d'un script externe lancé à la
    # main. Vide par défaut = boucle désactivée (dev sans simulateur).
    HOLYKELL_SYNC_BASE_URL: str | None = None
    HOLYKELL_SYNC_INTERVAL_SEC: int = 5

    # Balayage structurel (D5 — prix/mapping capteur/calibration manquants) —
    # indépendant de Holykell, tourne toujours (contrairement au sondage
    # ci-dessus). Intervalle long : ces états ne changent pas à la seconde.
    STRUCTURAL_SWEEP_INTERVAL_SEC: int = 300

    # Notifications Web Push (RFC 8030) — clé publique communiquée telle
    # quelle au navigateur (`PushManager.subscribe`), clé privée jamais
    # exposée hors de ce process. Vide par défaut = canal désactivé
    # silencieusement (`notify_new_alert` no-op), jamais une erreur au
    # démarrage en dev sans clés générées.
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_CLAIMS_EMAIL: str = "contact@zylo.example"

    # Envoi des messages (invitations T-021/T-049). `none` par défaut : la
    # création de compte est alors DÉSACTIVÉE (503), tant que l'envoi n'est
    # pas configuré en production. `console` (journal stdout, contient le lien
    # d'activation) n'est admis qu'en development ; `memory` (boîte de test)
    # n'est admis qu'en test. Voir app/shared/email.py.
    EMAIL_BACKEND: str = "none"
    # Transport SMTP neutre, jamais activé implicitement. Les credentials sont
    # fournis uniquement par l'environnement; aucun secret n'est versionné.
    EMAIL_SMTP_HOST: str | None = None
    EMAIL_SMTP_PORT: int = 587
    EMAIL_SMTP_USERNAME: str | None = None
    EMAIL_SMTP_PASSWORD: SecretStr | None = None
    EMAIL_SMTP_FROM_ADDRESS: str | None = None
    EMAIL_SMTP_STARTTLS: bool = True
    EMAIL_SMTP_TIMEOUT_SECONDS: int = 10
    # Lien transmis au titulaire : `<base>#token=<jeton>`. Le jeton est dans le
    # fragment (non envoyé au serveur, absent des journaux d'accès).
    ACTIVATION_URL_BASE: str = "http://localhost:3001/activer"
    # Durée de validité d'un jeton d'activation (décision T-049 : 72 heures).
    USER_INVITATION_TTL_HOURS: int = 72
    # Idempotence des commandes (BE-232, QE-EXP-06 : TTL NON DÉFINI dans la
    # définition). Hypothèse appliquée : 24 h. Une clé plus ancienne est traitée
    # comme nouvelle (app/core/idempotency.py). Lu à chaque appel, pas à l'import.
    IDEMPOTENCY_KEY_TTL_HOURS: int = 24
    # Backoff des tentatives d'intégration (BE-164, QE-PAR-09) : valeurs NON DÉFINIES
    # par la définition. Aucun défaut codé : `None` tant que l'environnement ne les fournit
    # pas, et la politique refuse de démarrer (app/integrations/tentatives.py).
    INTEGRATION_BACKOFF_BASE_SECONDS: int | None = None
    INTEGRATION_BACKOFF_CAP_SECONDS: int | None = None

    # BE-163 : fenêtre anti-rejeu des webhooks entrants (QE-PAR-09). Aucune valeur par défaut
    # codée : sans cette valeur, la réception des webhooks échoue fermée (503).
    WEBHOOK_FENETRE_ANTI_REJEU_SECONDS: int | None = None
    # Consommation d'événements (BE-235, QE-EXP-08) : nombre maximal de tentatives par
    # consommateur avant envoi en lettre morte (DLQ). NON DÉFINI par la définition : aucun
    # défaut codé. À None, la consommation refuse de tourner (503) au lieu de deviner.
    EVENTS_CONSUMER_MAX_TENTATIVES: int | None = None
    # Réinitialisation par e-mail, token fragment pour qu'il ne soit pas envoyé
    # dans les journaux/referers HTTP.
    PASSWORD_RESET_URL_BASE: str = "http://localhost:3001/forgot-password"
    PASSWORD_RESET_TTL_MINUTES: int = 30

    # Limitation de débit de l'authentification (T-012, docs/questions/securite/
    # limitation-authentification.md). Compteurs d'échecs dans PostgreSQL (table
    # loginAttempt), fenêtre glissante. Verrou par couple (IP, compte) avec backoff
    # (base x 2^(échecs au-delà du seuil), plafonné) ; plafond global par IP.
    # Retour arrière : AUTH_RATE_LIMIT_ENABLED=false (sans revert de code).
    AUTH_RATE_LIMIT_ENABLED: bool = True
    AUTH_RATE_LIMIT_WINDOW_SECONDS: int = 900
    AUTH_RATE_LIMIT_MAX_FAILURES_PER_ACCOUNT: int = 10
    AUTH_RATE_LIMIT_MAX_FAILURES_PER_IP: int = 100
    AUTH_RATE_LIMIT_LOCK_BASE_SECONDS: int = 60
    AUTH_RATE_LIMIT_LOCK_MAX_SECONDS: int = 900
    # Adresses des proxys de confiance (reverse proxy). X-Forwarded-For n'est lu
    # que si l'adresse du pair direct figure dans cette liste. Vide = aucun proxy.
    AUTH_RATE_LIMIT_TRUSTED_PROXIES: list[str] = []

    # Quotas (BE-191) : deux familles configurées séparément. Quota produit : nombre
    # de requêtes par fenêtre, par tenant (décision produit, QE-API-17). Limite
    # technique : protection de l'infrastructure, indépendante du produit.
    QUOTA_PRODUIT_MAX_REQUETES: int = 600
    QUOTA_PRODUIT_FENETRE_SECONDES: int = 60
    LIMITE_TECHNIQUE_MAX_REQUETES: int = 1200
    LIMITE_TECHNIQUE_FENETRE_SECONDES: int = 60

    # Réseaux internes autorisés à lire la readiness (`/api/v1/internal/ready`,
    # BE-240), en notation CIDR. Vide = aucun réseau interne : la route répond 404
    # pour tout le monde. Seule l'adresse du pair direct est comparée (pas de
    # X-Forwarded-For), pour qu'un en-tête fourni par un client ne puisse pas
    # ouvrir la route.
    HEALTH_INTERNAL_NETWORKS: list[str] = []

    # Sessions par cookies (T-037a, docs/architecture/securite/sessions.md).
    # Les jetons d'accès et de rafraîchissement sont posés en cookies HttpOnly ;
    # l'interface ne les lit jamais. `AUTH_COOKIE_SECURE` vaut None par défaut :
    # Secure est alors vrai hors `development`. Un `false` explicite n'est admis
    # qu'en development (voir le validateur). `lax` par défaut : les liens
    # d'entrée depuis l'extérieur restent utilisables, les envois inter-sites
    # non-GET sont coupés. `none` est refusé (il exigerait Secure partout).
    AUTH_COOKIE_SECURE: bool | None = None
    AUTH_COOKIE_SAMESITE: Literal["lax", "strict"] = "lax"
    # Domaine du cookie. None = hôte exact (recommandé : interface et API sur le
    # même site, sans Domain, donc sans partage avec les sous-domaines).
    AUTH_COOKIE_DOMAIN: str | None = None
    # L'inscription publique n'est pas activée par défaut : la création de
    # comptes passe par les invitations d'organisation tant que le produit
    # n'a pas approuvé le libre-service.
    AUTH_PUBLIC_REGISTRATION_ENABLED: bool = False
    # Fin de la transition (T-037a). Jusqu'à cette date : l'en-tête Authorization
    # est accepté et les jetons restent dans le JSON des réponses d'authentification,
    # pour les clients existants. Après : cookies seuls, aucun jeton dans le corps.
    # Date proposée, à confirmer avant le déploiement (docs/architecture/securite/sessions.md §4).
    AUTH_HEADER_ACCEPTED_UNTIL: datetime = datetime(2026, 11, 30, tzinfo=timezone.utc)

    @property
    def cookies_secure(self) -> bool:
        if self.AUTH_COOKIE_SECURE is not None:
            return self.AUTH_COOKIE_SECURE
        return self.ENVIRONMENT != ENVIRONMENT_DEVELOPPEMENT

    @model_validator(mode="after")
    def _valide_sessions_et_cors(self) -> "Settings":
        # Intention : un cookie d'accès non Secure ne doit jamais sortir d'un
        # environnement réel, et CORS avec identifiants ne doit jamais accepter
        # un joker (n'importe quelle origine pourrait alors lire les réponses
        # authentifiées). Les messages nomment la variable, jamais sa valeur.
        if self.AUTH_COOKIE_SECURE is False and self.ENVIRONMENT != ENVIRONMENT_DEVELOPPEMENT:
            raise ConfigurationSecretError(
                "AUTH_COOKIE_SECURE=false n'est admis qu'avec ENVIRONMENT=development (variable : AUTH_COOKIE_SECURE)."
            )
        if self.AUTH_HEADER_ACCEPTED_UNTIL.tzinfo is None:
            raise ConfigurationSecretError("AUTH_HEADER_ACCEPTED_UNTIL doit être une date avec fuseau horaire.")
        if any(origine.strip() == "*" for origine in self.CORS_ORIGINS):
            raise ConfigurationSecretError("CORS_ORIGINS ne doit jamais contenir « * » : CORS est utilisé avec identifiants (variable : CORS_ORIGINS).")
        return self

    @model_validator(mode="after")
    def _refuse_inscription_publique_hors_environnements_non_productifs(self) -> "Settings":
        # Le libre-service nécessite une décision produit ainsi qu'un flux de
        # vérification e-mail; même une variable explicitement à true ne doit
        # pas pouvoir l'activer en production ou en staging.
        if self.AUTH_PUBLIC_REGISTRATION_ENABLED and self.ENVIRONMENT not in {ENVIRONMENT_DEVELOPPEMENT, "test"}:
            raise ConfigurationSecretError(
                "AUTH_PUBLIC_REGISTRATION_ENABLED=true est admis uniquement en development ou test."
            )
        return self

    @model_validator(mode="after")
    def _valide_envoi_des_messages(self) -> "Settings":
        # Intention : un journal d'activation (qui contient le jeton) ne peut
        # jamais être actif hors développement, et une boîte mémoire jamais hors test.
        backends = {"none", "console", "memory", "smtp"}
        if self.EMAIL_BACKEND not in backends:
            raise ConfigurationSecretError(
                f"EMAIL_BACKEND inconnu : {self.EMAIL_BACKEND!r} (valeurs admises : none, console, memory)."
            )
        if self.EMAIL_BACKEND == "console" and self.ENVIRONMENT != ENVIRONMENT_DEVELOPPEMENT:
            raise ConfigurationSecretError("EMAIL_BACKEND=console n'est admis qu'avec ENVIRONMENT=development.")
        if self.EMAIL_BACKEND == "memory" and self.ENVIRONMENT != "test":
            raise ConfigurationSecretError("EMAIL_BACKEND=memory n'est admis qu'avec ENVIRONMENT=test.")
        if self.EMAIL_BACKEND == "smtp":
            if self.ENVIRONMENT != "production":
                raise ConfigurationSecretError("EMAIL_BACKEND=smtp n'est admis qu'avec ENVIRONMENT=production.")
            if not self.EMAIL_SMTP_HOST or not self.EMAIL_SMTP_FROM_ADDRESS:
                raise ConfigurationSecretError(
                    "EMAIL_BACKEND=smtp exige EMAIL_SMTP_HOST et EMAIL_SMTP_FROM_ADDRESS."
                )
            if (
                not self.EMAIL_SMTP_USERNAME
                or self.EMAIL_SMTP_PASSWORD is None
                or not self.EMAIL_SMTP_PASSWORD.get_secret_value()
            ):
                raise ConfigurationSecretError(
                    "EMAIL_BACKEND=smtp exige EMAIL_SMTP_USERNAME et EMAIL_SMTP_PASSWORD."
                )
            if not self.EMAIL_SMTP_STARTTLS:
                raise ConfigurationSecretError(
                    "EMAIL_BACKEND=smtp exige EMAIL_SMTP_STARTTLS=true."
                )
            if not (1 <= self.EMAIL_SMTP_PORT <= 65535):
                raise ConfigurationSecretError("EMAIL_SMTP_PORT doit être entre 1 et 65535.")
            if not (1 <= self.EMAIL_SMTP_TIMEOUT_SECONDS <= 60):
                raise ConfigurationSecretError("EMAIL_SMTP_TIMEOUT_SECONDS doit être entre 1 et 60.")
        if not (1 <= self.PASSWORD_RESET_TTL_MINUTES <= 60):
            raise ConfigurationSecretError("PASSWORD_RESET_TTL_MINUTES doit être entre 1 et 60.")
        if self.EMAIL_BACKEND == "smtp":
            reset_url = urlsplit(self.PASSWORD_RESET_URL_BASE)
            if reset_url.scheme != "https" or not reset_url.netloc or reset_url.query or reset_url.fragment:
                raise ConfigurationSecretError(
                    "Avec EMAIL_BACKEND=smtp, PASSWORD_RESET_URL_BASE doit être une URL HTTPS sans query ni fragment."
                )
            # La page frontend canonique est /forgot-password. Un préfixe de
            # déploiement reste permis (ex. /zylo/forgot-password), mais pas
            # un autre écran terminal qui rendrait le lien inutilisable.
            if reset_url.path.rstrip("/").split("/")[-1] != "forgot-password":
                raise ConfigurationSecretError(
                    "Avec EMAIL_BACKEND=smtp, PASSWORD_RESET_URL_BASE doit terminer par /forgot-password."
                )
        return self

    @model_validator(mode="after")
    def _refuse_fallback_secrets_hors_development(self) -> "Settings":
        # Intention : l'import de ce module échoue (donc `import app.main` et
        # uvicorn aussi) plutôt que de servir des jetons signés avec une clé
        # publique. Le message nomme les variables, jamais leur valeur.
        if self.ENVIRONMENT == ENVIRONMENT_DEVELOPPEMENT:
            return self

        fautives: list[str] = []
        if _secret_refuse(self.JWT_SECRET, FALLBACK_JWT_SECRET):
            fautives.append("JWT_SECRET")
        if _secret_refuse(self.STORAGE_SIGNED_URL_SECRET, FALLBACK_JWT_SECRET):
            fautives.append("STORAGE_SIGNED_URL_SECRET")
        if _mot_de_passe_db(self.DATABASE_URL) == FALLBACK_DB_PASSWORD:
            fautives.append("DATABASE_URL (mot de passe de repli)")

        # Clé de chiffrement : exigée hors development et test (test la fournit
        # ou n'en a pas besoin). Absente, vide ou trop courte : refus.
        if self.ENVIRONMENT != "test" and _secret_refuse(self.APP_FIELD_ENCRYPTION_KEY, ""):
            fautives.append("APP_FIELD_ENCRYPTION_KEY")

        if fautives:
            raise ConfigurationSecretError(
                f"Démarrage refusé (ENVIRONMENT={self.ENVIRONMENT!r}, hors development) : "
                f"variables à corriger : {', '.join(fautives)} (absentes, de repli ou trop courtes). "
                f"Définir des valeurs propres (au moins {SECRET_MIN_LENGTH} caractères) "
                "ou ENVIRONMENT=development en local."
            )
        return self


def _secret_refuse(valeur: str, repli: str) -> bool:
    """Vrai si le secret vaut la valeur de repli ou est trop court."""
    return valeur == repli or len(valeur) < SECRET_MIN_LENGTH


def _mot_de_passe_db(url: str) -> str | None:
    """Mot de passe de l'URL de base, ou None s'il n'y en a pas (ex. socket Unix)."""
    return urlsplit(url).password


settings = Settings()
