from fastapi import Depends

from app.config import Settings, settings
from app.services.email_sync import EmailSyncService


def get_settings() -> Settings:
    return settings


def get_email_service(config: Settings = Depends(get_settings)) -> EmailSyncService:
    return EmailSyncService(config)
