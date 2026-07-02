from __future__ import annotations

from typing import Any

from app.db.postgres_repository import PostgresEmailRepository
from app.db.sqlite_repository import SqliteEmailRepository
from app.models.schemas import MessageDetail, MessageSummary

DbConnection = Any


def create_email_repository(database_url: str) -> SqliteEmailRepository | PostgresEmailRepository:
    if database_url.startswith("postgresql://"):
        return PostgresEmailRepository(database_url)
    return SqliteEmailRepository(database_url)


class EmailRepository:
    """Unified facade: SQLite by default, PostgreSQL when DATABASE_URL uses postgresql://."""

    def __init__(self, database_url: str):
        self._backend = create_email_repository(database_url)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    @staticmethod
    def to_summary_dict(message: MessageDetail | MessageSummary) -> dict[str, Any]:
        return message.model_dump(by_alias=True)
