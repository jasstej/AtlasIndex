import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # API Configurations (Locked to loopback 127.0.0.1 for secure coding compliance)
    host: str = "127.0.0.1"
    port: int = 8000
    
    # Database Configuration
    database_url: str = "sqlite:///atlasindex.db"
    
    # Watcher & Scan Configs
    default_scan_path: str = os.path.expanduser("~")
    
    # Port allocation series start
    port_series_start: int = 3000

    # Pydantic Configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
