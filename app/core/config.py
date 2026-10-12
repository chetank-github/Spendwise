from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SpendWise"
    database_url: str
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    ai_provider: str = "gemini"  # "gemini" or "groq"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"
    ai_min_confidence: float = 0.7
    upload_dir: str = "uploads"
    max_upload_mb: int = 5

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()