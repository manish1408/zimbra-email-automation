from __future__ import annotations

from typing import Any

from app.db.email_repository import EmailRepository


def _is_spam_folder(folder_path: Any) -> bool:
    return str(folder_path or "").strip().lower() in {"junk", "spam"}


def _actions_from_record(record: dict[str, Any]) -> dict[str, Any]:
    folder_path = record.get("folder_path")
    folder_moved = bool(record.get("folder_moved"))
    return {
        "folder_path": folder_path,
        "folder_moved": folder_moved,
        "forwarded_to": record.get("forwarded_to"),
        "draft_saved": bool(record.get("draft_saved")),
        "moved_to_spam": folder_moved
        and (bool(record.get("is_spam")) or _is_spam_folder(folder_path)),
    }


def _message_lookup(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    messages = state.get("enriched_messages") or state.get("messages") or []
    return {str(m.get("id")): m for m in messages if m.get("id")}


def _classification_for(
    msg_id: str, state: dict[str, Any]
) -> dict[str, Any] | None:
    for item in state.get("classifications") or []:
        if item.get("message_id") == msg_id:
            return dict(item)
    return None


def _format_action_error(err: Any, *, message_id: str | None = None) -> str | None:
    if isinstance(err, dict):
        err_msg = str(err.get("error") or err)
        err_id = str(err.get("message_id") or "")
        if message_id and err_id and err_id != message_id:
            return None
        if message_id and err_id == message_id:
            return (
                err_msg
                if err_msg.startswith(f"{message_id}:")
                else f"{message_id}: {err_msg}"
            )
        return f"{err_id}: {err_msg}" if err_id else err_msg
    text = str(err)
    if message_id and not text.startswith(f"{message_id}:"):
        return None
    return text


def format_action_errors(
    action_errors: list[Any],
    *,
    message_id: str | None = None,
) -> str:
    parts: list[str] = []
    for err in action_errors:
        formatted = _format_action_error(err, message_id=message_id)
        if formatted:
            parts.append(formatted)
    return "; ".join(parts)


def _run_status(
    msg_id: str,
    record: dict[str, Any],
    action_errors: list[Any],
) -> tuple[str, str | None]:
    record_error = record.get("error")
    msg_errors: list[str] = []
    for err in action_errors:
        formatted = _format_action_error(err, message_id=msg_id)
        if formatted:
            msg_errors.append(formatted)
    if record_error or msg_errors:
        error = record_error or "; ".join(msg_errors)
        return "failed", error
    return "completed", None


def finalize_trace_summaries(
    traces: dict[str, dict[str, Any]],
    *,
    total_duration_ms: int,
    llm_duration_ms: int,
) -> None:
    for entry in traces.values():
        entry["total_duration_ms"] = total_duration_ms
        entry["llm_duration_ms"] = llm_duration_ms


async def persist_message_automation_logs(
    repository: EmailRepository,
    conn: Any,
    state: dict[str, Any],
    *,
    total_duration_ms: int,
    llm_duration_ms: int,
) -> list[int]:
    """Insert one message_automation_runs row per processed message."""
    account = state["user_email"]
    thread_id = state.get("automation_thread_id") or ""
    report = state.get("report") or {}
    dry_run = bool(report.get("dry_run"))
    actions_taken = state.get("actions_taken") or []
    action_errors = list(state.get("action_errors") or [])
    traces = state.get("automation_traces") or {}
    by_id = _message_lookup(state)

    finalize_trace_summaries(
        traces,
        total_duration_ms=total_duration_ms,
        llm_duration_ms=llm_duration_ms,
    )

    count = max(len(actions_taken), 1)
    per_msg_duration = total_duration_ms // count
    per_msg_llm = llm_duration_ms // count
    run_ids: list[int] = []

    if not actions_taken:
        return run_ids

    for record in actions_taken:
        msg_id = str(record.get("message_id") or "")
        if not msg_id:
            continue
        message = by_id.get(msg_id) or {}
        status, error = _run_status(msg_id, record, action_errors)
        trace = traces.get(msg_id) or record.get("automation_trace")
        if isinstance(trace, dict):
            trace = dict(trace)
            trace.setdefault("total_duration_ms", per_msg_duration)
            trace.setdefault("llm_duration_ms", per_msg_llm)

        run_id = await repository.save_message_automation_run(
            conn,
            account,
            msg_id,
            thread_id,
            status,
            dry_run=dry_run,
            classification=_classification_for(msg_id, state),
            actions=_actions_from_record(record),
            draft_reply_text=record.get("draft_reply_text"),
            report=report,
            error=error,
            duration_ms=per_msg_duration,
            llm_duration_ms=per_msg_llm,
            automation_trace=trace,
            subject=message.get("subject"),
            from_address=message.get("from") or message.get("from_address"),
        )
        run_ids.append(run_id)

    if hasattr(conn, "commit"):
        await conn.commit()
    return run_ids
