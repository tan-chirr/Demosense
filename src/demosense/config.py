from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    jwt_secret: str
    # comma-separated list of allowed frontend origins, e.g. a Lovable app URL.
    # "*" (the default) is fine for a bearer-token API with no cookie auth -
    # tighten this once the frontend's real origin is known.
    cors_allow_origins: str = "*"


settings = Settings()
