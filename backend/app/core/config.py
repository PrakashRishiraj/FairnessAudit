from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List
import os


class Settings(BaseSettings):
    APP_NAME: str = "FairnessAudit API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    # Comma-separated origins string, e.g. "*" or "https://a.com,https://b.com"
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001"

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]
    UPLOAD_DIR: str = "uploads"
    MAX_FILE_SIZE_MB: int = 50
    SAMPLE_DATA_DIR: str = "app/data/samples"

    # AI & Cloud Integrations
    GEMINI_API_KEY: str = ""
    GCP_PROJECT_ID: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:3000/audit?tab=drive"
    ALERT_EMAIL: str = ""
    WEBHOOK_URL: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

# Ensure upload directory exists
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.SAMPLE_DATA_DIR, exist_ok=True)
