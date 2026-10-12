from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SpendWise"
    database_url: str
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    gemini_api_key: str = ""
    upload_dir: str = "uploads"
    max_upload_mb: int = 5

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()