from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from asyncpg.exceptions import UniqueViolationError

from app.config import Settings
from app.db.pool import get_pool

logger = logging.getLogger(__name__)

_LLM_RESOURCE = "llm"
_PROCESS_TAG = f"{socket.gethostname()}:{os.getpid()}"


async def _cleanup_stale_holders(
    conn,
    resource: str,
    *,
    stale_seconds: float,
) -> None:
    await conn.execute(
        """
        DELETE FROM distributed_semaphore_holders
        WHERE resource = $1
          AND acquired_at < NOW() - ($2::double precision * INTERVAL '1 second')
        """,
        resource,
        stale_seconds,
    )


async def _try_acquire(conn, resource: str, max_slots: int, owner: str) -> bool:
    await _cleanup_stale_holders(conn, resource, stale_seconds=900.0)
    rows = await conn.fetch(
        "SELECT slot FROM distributed_semaphore_holders WHERE resource = $1",
        resource,
    )
    taken = {int(row["slot"]) for row in rows}
    for slot in range(max(1, max_slots)):
        if slot in taken:
            continue
        try:
            await conn.execute(
                """
                INSERT INTO distributed_semaphore_holders (resource, slot, owner)
                VALUES ($1, $2, $3)
                """,
                resource,
                slot,
                owner,
            )
            return True
        except UniqueViolationError:
            continue
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                continue
            raise
    return False


async def _release(conn, resource: str, owner: str) -> None:
    await conn.execute(
        """
        DELETE FROM distributed_semaphore_holders
        WHERE resource = $1 AND owner = $2
        """,
        resource,
        owner,
    )


@asynccontextmanager
async def llm_concurrency_limit(settings: Settings) -> AsyncIterator[None]:
    """Limit concurrent LLM calls across all poller/API processes."""
    max_slots = int(settings.llm_global_concurrency or 0)
    if max_slots <= 0:
        yield
        return

    owner = f"{_PROCESS_TAG}:{uuid.uuid4().hex[:10]}"
    wait_seconds = max(1.0, float(settings.llm_concurrency_wait_seconds))
    deadline = time.monotonic() + wait_seconds
    pool = get_pool()

    while True:
        conn = await pool.acquire()
        try:
            if await _try_acquire(conn, _LLM_RESOURCE, max_slots, owner):
                logger.debug("Acquired LLM slot (%s)", owner)
                break
        finally:
            await pool.release(conn)

        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out after {wait_seconds:g}s waiting for an LLM concurrency slot "
                f"(max={max_slots})"
            )
        await asyncio.sleep(0.25)

    try:
        yield
    finally:
        conn = await pool.acquire()
        try:
            await _release(conn, _LLM_RESOURCE, owner)
            logger.debug("Released LLM slot (%s)", owner)
        finally:
            await pool.release(conn)
