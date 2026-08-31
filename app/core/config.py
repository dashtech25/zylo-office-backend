from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Zylo Office Backend"
    ENVIRONMENT: str = "development"
    PORT: int = 3007
    CORS_ORIGINS: list[str] = [
        "http://localhost:3006",
        "http://127.0.0.1:3006",
    ]


settings = Settings()
