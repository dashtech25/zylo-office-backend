from urllib.parse import urlsplit

from pydantic import model_validator
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
    # Lien transmis au titulaire : `<base>#token=<jeton>`. Le jeton est dans le
    # fragment (non envoyé au serveur, absent des journaux d'accès).
    ACTIVATION_URL_BASE: str = "http://localhost:3001/activer"
    # Durée de validité d'un jeton d'activation (décision T-049 : 72 heures).
    USER_INVITATION_TTL_HOURS: int = 72

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

    @model_validator(mode="after")
    def _valide_envoi_des_messages(self) -> "Settings":
        # Intention : un journal d'activation (qui contient le jeton) ne peut
        # jamais être actif hors développement, et une boîte mémoire jamais hors test.
        backends = {"none", "console", "memory"}
        if self.EMAIL_BACKEND not in backends:
            raise ConfigurationSecretError(
                f"EMAIL_BACKEND inconnu : {self.EMAIL_BACKEND!r} (valeurs admises : none, console, memory)."
            )
        if self.EMAIL_BACKEND == "console" and self.ENVIRONMENT != ENVIRONMENT_DEVELOPPEMENT:
            raise ConfigurationSecretError("EMAIL_BACKEND=console n'est admis qu'avec ENVIRONMENT=development.")
        if self.EMAIL_BACKEND == "memory" and self.ENVIRONMENT != "test":
            raise ConfigurationSecretError("EMAIL_BACKEND=memory n'est admis qu'avec ENVIRONMENT=test.")
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
