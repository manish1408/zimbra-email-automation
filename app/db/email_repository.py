from __future__ import annotations

from typing import Any

from app.db.postgres_repository import PostgresEmailRepository
from app.models.schemas import MessageDetail, MessageSummary

DbConnection = Any

_POSTGRES_PREFIXES = ("postgresql://", "postgres://")


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql://" + database_url[len("postgres://") :]
    return database_url


def require_postgres_database_url(database_url: str) -> str:
    normalized = normalize_database_url(database_url.strip())
    if not normalized.startswith("postgresql://"):
        raise ValueError(
            "DATABASE_URL must be a PostgreSQL connection string "
            "(postgresql:// or postgres://). SQLite is not supported."
        )
    return normalized


class EmailRepository:
    """PostgreSQL persistence for synced mailboxes and automation results."""

    def __init__(self, database_url: str):
        self.database_url = require_postgres_database_url(database_url)
        self._backend = PostgresEmailRepository(self.database_url)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    @staticmethod
    def to_summary_dict(message: MessageDetail | MessageSummary) -> dict[str, Any]:
        return message.model_dump(by_alias=True)

    async def get_agent_training(self, conn: DbConnection | None = None) -> dict[str, Any]:
        return await self._backend.get_agent_training(conn)

    async def upsert_agent_training(self, content: str, conn: DbConnection | None = None) -> dict[str, Any]:
        return await self._backend.upsert_agent_general_rules(content, conn)

    async def upsert_agent_general_rules(
        self, general_rules: str, conn: DbConnection | None = None
    ) -> dict[str, Any]:
        return await self._backend.upsert_agent_general_rules(general_rules, conn)

    async def upsert_agent_draft_reply_rules(
        self, draft_reply_rules: str, conn: DbConnection | None = None
    ) -> dict[str, Any]:
        return await self._backend.upsert_agent_draft_reply_rules(draft_reply_rules, conn)

    async def get_classification_rules(self, conn: DbConnection | None = None) -> dict[str, Any]:
        return await self._backend.get_classification_rules(conn)

    async def save_classification_rules(
        self, payload: dict[str, Any], conn: DbConnection | None = None
    ) -> dict[str, Any]:
        return await self._backend.save_classification_rules(payload, conn)
