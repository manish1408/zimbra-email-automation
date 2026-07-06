from __future__ import annotations

import logging
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)


class AutomationConsoleReporter:
    """Live console output for automation pipeline runs."""

    def __init__(self, *, enabled: bool | None = None) -> None:
        self._enabled = enabled if enabled is not None else sys.stdout.isatty()
        self._console = None
        self._live = None
        self._step_rows: list[dict[str, Any]] = []
        self._run_start: float | None = None
        self._account = ""
        self._thread_id = ""
        self._message_count = 0
        self._dry_run = False

        if self._enabled:
            try:
                from rich.console import Console
                from rich.live import Live
                from rich.table import Table
                from rich.panel import Panel
                from rich.text import Text

                self._console = Console()
                self._Live = Live
                self._Table = Table
                self._Panel = Panel
                self._Text = Text
            except ImportError:
                self._enabled = False

    def start_run(
        self,
        *,
        account: str,
        thread_id: str,
        message_count: int,
        dry_run: bool,
    ) -> None:
        self._run_start = time.perf_counter()
        self._account = account
        self._thread_id = thread_id
        self._message_count = message_count
        self._dry_run = dry_run
        self._step_rows = []

        header = (
            f"Automation run | account={account} | thread={thread_id} | "
            f"messages={message_count} | dry_run={dry_run}"
        )
        if self._enabled and self._console:
            self._console.print(self._Panel(self._Text(header, style="bold cyan")))
        else:
            logger.info(header)

    def start_step(self, step: str) -> float:
        return time.perf_counter()

    def end_step(self, step: str, started: float, *, error: str | None = None) -> None:
        duration_ms = int((time.perf_counter() - started) * 1000)
        row = {
            "step": step,
            "duration_ms": duration_ms,
            "success": error is None,
            "error": error,
        }
        self._step_rows.append(row)

        if self._enabled and self._console:
            style = "green" if error is None else "red"
            msg = f"  {step} ({duration_ms}ms)"
            if error:
                msg += f" — {error}"
            self._console.print(msg, style=style)
        else:
            if error:
                logger.error("Step %s failed after %dms: %s", step, duration_ms, error)
            else:
                logger.info("Step %s completed in %dms", step, duration_ms)

    def finish_run(
        self,
        *,
        total_duration_ms: int,
        llm_duration_ms: int,
        completed: int,
        failed: int,
    ) -> None:
        summary = (
            f"Run complete | total={total_duration_ms}ms | llm={llm_duration_ms}ms | "
            f"ok={completed} | failed={failed}"
        )
        if self._enabled and self._console and self._Table:
            table = self._Table(title="Pipeline steps")
            table.add_column("Step")
            table.add_column("Duration")
            table.add_column("Status")
            for row in self._step_rows:
                status = "ok" if row["success"] else f"fail: {row.get('error', '')}"
                table.add_row(row["step"], f"{row['duration_ms']}ms", status)
            self._console.print(table)
            self._console.print(self._Panel(self._Text(summary, style="bold")))
        else:
            logger.info(summary)
