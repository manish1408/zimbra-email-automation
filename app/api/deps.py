from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import Depends

from app.config import Settings, settings
from app.db.email_repository import DbConnection, EmailRepository
from app.services.email_sync import EmailSyncService


def get_settings() -> Settings:
    return settings


def get_email_service(config: Settings = Depends(get_settings)) -> EmailSyncService:
    return EmailSyncService(config)


def get_email_repository(config: Settings = Depends(get_settings)) -> EmailRepository:
    return EmailRepository(config.database_url)


async def get_db_connection(
    repository: EmailRepository = Depends(get_email_repository),
) -> AsyncGenerator[Any, None]:
    conn = await repository.connect()
    try:
        yield conn
    finally:
        await conn.close()


DbConn = Annotated[DbConnection, Depends(get_db_connection)]
