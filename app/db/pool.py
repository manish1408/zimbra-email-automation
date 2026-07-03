from __future__ import annotations

from pathlib import Path

import asyncpg

_SCHEMA_DIR = Path(__file__).resolve().parent / "migrations"
_pool: asyncpg.Pool | None = None


async def init_pool(database_url: str, *, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    """Create the shared pool and run schema migrations once."""
    global _pool
    if _pool is not None:
        return _pool

    _pool = await asyncpg.create_pool(database_url, min_size=min_size, max_size=max_size)
    async with _pool.acquire() as conn:
        for path in sorted(_SCHEMA_DIR.glob("*.sql")):
            await conn.execute(path.read_text())
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized. Call init_pool() first.")
    return _pool
