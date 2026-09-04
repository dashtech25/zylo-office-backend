from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Zylo Office Backend"
    ENVIRONMENT: str = "development"
    PORT: int = 3002
    CORS_ORIGINS: list[str] = [
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]

    # En local, DATABASE_URL pointe vers PostgreSQL local. Une fois déployé,
    # cette même variable doit pointer vers la base de données en ligne —
    # jamais d'URL codée en dur dans le code.
    DATABASE_URL: str = "postgresql+asyncpg://zylo_office:changeme@localhost:5432/zylo_office"

    JWT_SECRET: str = "changeme-generate-a-real-random-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30


settings = Settings()
