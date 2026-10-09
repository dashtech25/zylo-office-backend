from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Zylo Office Backend"
    ENVIRONMENT: str = "development"
    PORT: int = 3002
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
    # jamais d'URL codée en dur dans le code.
    DATABASE_URL: str = "postgresql+asyncpg://zylo_office:changeme@localhost:5432/zylo_office"

    JWT_SECRET: str = "changeme-generate-a-real-random-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Stockage documentaire (mission « vente-maintenant-reglementation »,
    # Phase 5 §2 : MinIO/S3-compatible retenu en cible ; "local" par défaut
    # en développement — même contrat d'interface (app/shared/storage.py),
    # jamais d'accès direct dispersé dans les modules métier.
    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_ROOT: str = "./var/storage"
    STORAGE_SIGNED_URL_SECRET: str = "changeme-generate-a-real-random-secret"
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


settings = Settings()
