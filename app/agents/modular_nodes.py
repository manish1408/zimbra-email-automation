from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Iterator

from app.agents.action_nodes import ActionNodeContext, make_base_action_nodes
from app.agents.state import MessageActionRecord, MessageClassification, PipelineState
from app.services.automation_rules import evaluate_message, load_automation_rules
from app.services.classification_service import ClassificationService
from app.services.draft_service import DraftService, build_shopify_context_payload
from app.services.email_thread import build_thread_context
from app.services.llm import llm_configured
from app.services.automation_run_logs import persist_message_automation_logs
from app.services.shopify.bot_client import OrderNotFoundError, ShopifyBotClient, ShopifyBotError
from app.services.shopify.order_reference import extract_order_reference

logger = logging.getLogger(__name__)


def _messages(state: PipelineState) -> list[dict[str, Any]]:
    return list(state.get("enriched_messages") or state.get("messages") or [])


def _conn(state: PipelineState):
    return state.get("db_conn")


def _trace(
    traces: dict[str, dict[str, Any]],
    msg_id: str,
    step: str,
    action: str,
    success: bool,
    *,
    duration_ms: int | None = None,
    started_at: str | None = None,
    **extra: Any,
) -> None:
    entry = traces.setdefault(msg_id, {"steps": []})
    step_data: dict[str, Any] = {
        "step": step,
        "action": action,
        "success": success,
        "started_at": started_at or datetime.now(UTC).isoformat(),
        **extra,
    }
    if duration_ms is not None:
        step_data["duration_ms"] = duration_ms
    entry["steps"].append(step_data)


@contextmanager
def _trace_step(
    traces: dict[str, dict[str, Any]],
    msg_id: str,
    step: str,
    action: str,
) -> Iterator[dict[str, Any]]:
    started_at = datetime.now(UTC).isoformat()
    t0 = perf_counter()
    extra: dict[str, Any] = {}
    success = True
    try:
        yield extra
    except Exception as exc:
        success = False
        extra["error"] = str(exc)
        raise
    finally:
        _trace(
            traces,
            msg_id,
            step,
            action,
            success,
            started_at=started_at,
            duration_ms=int((perf_counter() - t0) * 1000),
            **extra,
        )


def _rule_classification(
    msg_id: str,
    message: dict[str, Any],
    rule: dict[str, Any],
) -> MessageClassification:
    category = rule.get("set_category") or "rule_matched"
    is_spam = category == "spam"
    return MessageClassification(
        message_id=msg_id,
        subject=message.get("subject"),
        category=category,
        is_spam=is_spam,
        confidence=1.0,
        requested_person=None,
        needs_live_agent=False,
        reasoning=f"Matched automation rule {rule.get('rule_id')}",
        route_target=None,
        is_invoice_question=False,
        is_order_status_question=False,
        needs_response_generation=False,
        needs_forwarding=False,
        automation_source="rule",
        rule_id=rule.get("rule_id"),
    )


def make_modular_action_nodes(ctx: ActionNodeContext) -> dict[str, Any]:
    base_nodes = make_base_action_nodes(ctx)
    automation_rules = load_automation_rules()

    async def apply_automation_rules(state: PipelineState) -> dict:
        messages = _messages(state)
        conn = _conn(state)
        rule_results: dict[str, dict[str, Any]] = dict(state.get("rule_results") or {})
        traces: dict[str, dict[str, Any]] = dict(state.get("automation_traces") or {})
        action_records: dict[str, MessageActionRecord] = dict(
            state.get("action_records") or {}
        )
        errors = list(state.get("action_errors") or [])

        for message in messages:
            msg_id = str(message.get("id", ""))
            if not msg_id:
                continue
            result = evaluate_message(message, automation_rules)
            if not result.matched:
                continue

            rule_data = {
                "matched": True,
                "rule_id": result.rule_id,
                "no_action": result.no_action,
                "skip_llm": result.skip_llm,
                "mark_analyzed": result.mark_analyzed,
                "move_to_folder": result.move_to_folder,
                "set_category": result.set_category,
            }
            rule_results[msg_id] = rule_data
            _trace(traces, msg_id, "apply_automation_rules", "rule_match", True, rule_id=result.rule_id)

            record: MessageActionRecord = {
                "message_id": msg_id,
                "category": result.set_category or "rule_matched",
                "is_spam": (result.set_category or "") == "spam",
                "folder_path": result.move_to_folder,
                "folder_moved": False,
                "forwarded_to": None,
                "draft_saved": False,
                "draft_reply_text": None,
                "error": None,
                "automation_trace": traces.get(msg_id),
            }

            if result.no_action:
                _trace(traces, msg_id, "apply_automation_rules", "no_action", True)
                action_records[msg_id] = record
                continue

            if result.move_to_folder and conn is not None:
                try:
                    moved = await ctx.executor.apply_rule_folder_move(
                        conn,
                        state["user_email"],
                        message,
                        result.move_to_folder,
                    )
                    record["folder_moved"] = moved
                    record["folder_path"] = result.move_to_folder
                    _trace(
                        traces,
                        msg_id,
                        "apply_automation_rules",
                        "move_to_folder",
                        True,
                        folder=result.move_to_folder,
                    )
                except Exception as exc:
                    if result.skip_llm:
                        logger.warning(
                            "Non-fatal rule folder move failed for %s → %s: %s",
                            msg_id,
                            result.move_to_folder,
                            exc,
                        )
                        record["folder_moved"] = False
                        _trace(
                            traces,
                            msg_id,
                            "apply_automation_rules",
                            "move_to_folder",
                            False,
                            error=str(exc),
                            non_fatal=True,
                        )
                    else:
                        record["error"] = str(exc)
                        errors.append(f"{msg_id}: {exc}")
                        _trace(
                            traces,
                            msg_id,
                            "apply_automation_rules",
                            "move_to_folder",
                            False,
                            error=str(exc),
                        )
                action_records[msg_id] = record
            elif result.move_to_folder:
                action_records[msg_id] = record

        return {
            "rule_results": rule_results,
            "automation_traces": traces,
            "action_records": action_records,
            "action_errors": errors,
            "current_node": "apply_automation_rules",
        }

    async def persist_rule_matched(state: PipelineState) -> dict:
        """Persist and log rule-matched messages before slow LLM steps."""
        account = state["user_email"]
        conn = _conn(state)
        messages = _messages(state)
        rule_results = state.get("rule_results") or {}
        action_records: dict[str, MessageActionRecord] = dict(
            state.get("action_records") or {}
        )
        traces = dict(state.get("automation_traces") or {})
        errors = list(state.get("action_errors") or [])
        by_id = {str(m.get("id")): m for m in messages}
        rule_classifications: list[MessageClassification] = []
        actions_taken: list[MessageActionRecord] = []
        logged_ids: list[str] = []

        if not ctx.email_repository or conn is None:
            return {"current_node": "persist_rule_matched"}

        for msg_id, rule in rule_results.items():
            if not rule.get("skip_llm"):
                continue
            message = by_id.get(msg_id)
            record = action_records.get(msg_id)
            if not message or not record:
                continue
            if not state.get("force_reprocess") and await ctx.email_repository.is_message_processed(
                conn, account, msg_id
            ):
                continue

            classification = _rule_classification(msg_id, message, rule)
            rule_classifications.append(classification)
            try:
                await ctx.executor.persist_action(
                    conn,
                    account,
                    msg_id,
                    record,
                    classification,
                    automation_thread_id=state.get("automation_thread_id"),
                    report=state.get("report"),
                )
                actions_taken.append(record)
                logged_ids.append(msg_id)
            except Exception as exc:
                errors.append(f"{msg_id}: persist failed: {exc}")

        if logged_ids:
            await ctx.email_repository.mark_analyzed(conn, account, logged_ids)
            log_state = {
                **state,
                "classifications": rule_classifications,
                "actions_taken": actions_taken,
                "action_errors": errors,
                "automation_traces": traces,
            }
            await persist_message_automation_logs(
                ctx.email_repository,
                conn,
                log_state,
                total_duration_ms=0,
                llm_duration_ms=0,
            )
            if hasattr(conn, "commit"):
                await conn.commit()
            logger.info(
                "Persisted %d rule-matched message(s) before LLM: %s",
                len(logged_ids),
                logged_ids,
            )

        return {
            "classifications": list(state.get("classifications") or []) + rule_classifications,
            "actions_taken": list(state.get("actions_taken") or []) + actions_taken,
            "automation_logged_ids": list(state.get("automation_logged_ids") or []) + logged_ids,
            "action_errors": errors,
            "current_node": "persist_rule_matched",
        }

    async def classify_messages(state: PipelineState) -> dict:
        messages = _messages(state)
        rule_results = state.get("rule_results") or {}
        to_classify = [
            m
            for m in messages
            if not (rule_results.get(str(m.get("id", ""))) or {}).get("skip_llm")
            and str(m.get("id", "")) not in set(state.get("automation_logged_ids") or [])
        ]
        if not to_classify or not llm_configured(ctx.settings):
            return {
                "classifications": list(state.get("classifications") or []),
                "current_node": "classify_messages",
            }

        traces = dict(state.get("automation_traces") or {})
        errors = list(state.get("action_errors") or [])
        t0 = perf_counter()
        batch_result = await ClassificationService(ctx.settings).classify_batch(
            to_classify,
            classification_rules=state["classification_rules"],
            agent_training=state.get("agent_training"),
        )
        classify_ms = int((perf_counter() - t0) * 1000)
        for failure in batch_result.errors:
            msg_id = failure["message_id"]
            _trace(
                traces,
                msg_id,
                "classify_messages",
                "classify",
                False,
                duration_ms=0,
                error=failure["error"],
            )
            errors.append(
                {
                    "message_id": msg_id,
                    "action": "classify",
                    "error": failure["error"],
                }
            )
        account = state["user_email"]
        resolved = await ctx.resolver.resolve_routes_async(
            batch_result.classifications, account
        )
        for item in resolved:
            msg_id = item["message_id"]
            if item.get("needs_forwarding"):
                if not item.get("route_target"):
                    item["route_target"] = await ctx.resolver.resolve_forward_target(
                        item, account
                    )
            else:
                item["route_target"] = None
            _trace(
                traces,
                msg_id,
                "classify_messages",
                "classify",
                True,
                duration_ms=classify_ms // max(len(resolved), 1),
                category=item.get("category"),
            )

        return {
            "classifications": list(state.get("classifications") or []) + resolved,
            "automation_traces": traces,
            "action_errors": errors,
            "current_node": "classify_messages",
        }

    async def apply_routing_actions(state: PipelineState) -> dict:
        account = state["user_email"]
        conn = _conn(state)
        messages = _messages(state)
        by_id = {str(m.get("id")): m for m in messages}
        rule_results = state.get("rule_results") or {}
        classifications = state.get("classifications") or []
        traces = dict(state.get("automation_traces") or {})
        action_records: dict[str, MessageActionRecord] = dict(
            state.get("action_records") or {}
        )
        errors = list(state.get("action_errors") or [])

        for classification in classifications:
            msg_id = classification["message_id"]
            rule = rule_results.get(msg_id) or {}
            if rule.get("skip_llm"):
                continue

            message = by_id.get(msg_id)
            if not message or conn is None:
                continue

            record = action_records.get(msg_id) or {
                "message_id": msg_id,
                "category": classification["category"],
                "is_spam": classification.get("is_spam", False),
                "folder_path": None,
                "folder_moved": False,
                "forwarded_to": None,
                "draft_saved": False,
                "draft_reply_text": None,
                "error": None,
            }

            try:
                folder_name, moved = await ctx.executor.apply_folder_move(
                    conn, account, message, classification
                )
                record["folder_path"] = folder_name
                record["folder_moved"] = moved
                _trace(traces, msg_id, "apply_routing_actions", "folder_move", True, folder=folder_name)

                route_target = classification.get("route_target")
                if ctx.resolver.should_forward(classification) and route_target:
                    forwarded = await ctx.executor.apply_forward(
                        account,
                        msg_id,
                        route_target,
                        classification=classification,
                    )
                    record["forwarded_to"] = forwarded
                    _trace(traces, msg_id, "apply_routing_actions", "forward", True, to=forwarded)
            except Exception as exc:
                record["error"] = str(exc)
                errors.append(f"{msg_id}: {exc}")
                _trace(traces, msg_id, "apply_routing_actions", "routing", False, error=str(exc))

            record["automation_trace"] = traces.get(msg_id)
            action_records[msg_id] = record

        return {
            "action_records": action_records,
            "automation_traces": traces,
            "action_errors": errors,
            "current_node": "apply_routing_actions",
        }

    async def fetch_shopify_context(state: PipelineState) -> dict:
        account = state["user_email"]
        messages = _messages(state)
        by_id = {str(m.get("id")): m for m in messages}
        rule_results = state.get("rule_results") or {}
        classifications = state.get("classifications") or []
        shopify_context: dict[str, dict[str, Any]] = dict(state.get("shopify_context") or {})
        traces = dict(state.get("automation_traces") or {})
        client = ShopifyBotClient(ctx.settings)

        for classification in classifications:
            msg_id = classification["message_id"]
            if (rule_results.get(msg_id) or {}).get("skip_llm"):
                continue
            if not classification.get("needs_response_generation"):
                continue
            if classification.get("is_spam") or classification.get("needs_live_agent"):
                continue
            wants_shopify = classification.get("is_order_status_question") or classification.get(
                "is_invoice_question"
            )
            if not wants_shopify:
                shopify_context[msg_id] = {"outcome": "none"}
                continue

            message = by_id.get(msg_id)
            if not message:
                continue

            related: list[dict[str, Any]] = []
            try:
                thread_messages = await ctx.email_service.search_thread_messages(
                    account,
                    message.get("subject"),
                    exclude_id=msg_id,
                    limit=3,
                )
                related = [item.model_dump(by_alias=True) for item in thread_messages]
            except Exception:
                related = []

            thread = build_thread_context(message, related)
            reference = extract_order_reference(
                thread["current_text"],
                thread["history_text"],
            )

            if reference.ambiguous or not reference.reference:
                ctx_payload = build_shopify_context_payload(classification, reference)
                shopify_context[msg_id] = ctx_payload
                _trace(traces, msg_id, "fetch_shopify_context", "skip_api", True, outcome=ctx_payload.get("outcome"))
                continue

            if not client.configured():
                ctx_payload = build_shopify_context_payload(
                    classification,
                    reference,
                    error="not_configured",
                )
                shopify_context[msg_id] = ctx_payload
                _trace(
                    traces,
                    msg_id,
                    "fetch_shopify_context",
                    "skip_api",
                    False,
                    outcome=ctx_payload.get("outcome"),
                    error="not_configured",
                    order_reference=reference.reference,
                )
                continue

            order_summary = None
            invoice_summary = None
            error = None
            try:
                if classification.get("is_order_status_question"):
                    order = await client.get_order(reference.reference)
                    order_summary = order.model_dump()
                    _trace(traces, msg_id, "fetch_shopify_context", "order_api", True)
                elif classification.get("is_invoice_question"):
                    invoice = await client.get_invoice(reference.reference)
                    invoice_summary = invoice.model_dump()
                    _trace(traces, msg_id, "fetch_shopify_context", "invoice_api", True)
            except OrderNotFoundError:
                error = "not_found"
                _trace(traces, msg_id, "fetch_shopify_context", "api_404", True)
            except ShopifyBotError as exc:
                error = str(exc)
                _trace(traces, msg_id, "fetch_shopify_context", "api_error", False, error=error)

            shopify_context[msg_id] = build_shopify_context_payload(
                classification,
                reference,
                order_summary=order_summary,
                invoice_summary=invoice_summary,
                error=error,
            )

        return {
            "shopify_context": shopify_context,
            "automation_traces": traces,
            "current_node": "fetch_shopify_context",
        }

    async def generate_drafts(state: PipelineState) -> dict:
        account = state["user_email"]
        messages = _messages(state)
        by_id = {str(m.get("id")): m for m in messages}
        rule_results = state.get("rule_results") or {}
        classifications = state.get("classifications") or []
        shopify_context = state.get("shopify_context") or {}
        draft_replies: dict[str, str] = dict(state.get("draft_replies") or {})
        traces = dict(state.get("automation_traces") or {})
        errors = list(state.get("action_errors") or [])

        if not llm_configured(ctx.settings):
            return {"draft_replies": draft_replies, "current_node": "generate_drafts"}

        draft_service = DraftService(ctx.settings)
        for classification in classifications:
            msg_id = classification["message_id"]
            if (rule_results.get(msg_id) or {}).get("skip_llm"):
                continue
            if not classification.get("needs_response_generation"):
                continue

            message = by_id.get(msg_id)
            if not message:
                continue

            related: list[dict[str, Any]] = []
            try:
                thread_messages = await ctx.email_service.search_thread_messages(
                    account,
                    message.get("subject"),
                    exclude_id=msg_id,
                    limit=3,
                )
                related = [item.model_dump(by_alias=True) for item in thread_messages]
            except Exception:
                related = []

            try:
                draft_text = await draft_service.generate_draft(
                    message,
                    classification,
                    related,
                    shopify_context.get(msg_id),
                    draft_reply_rules=state.get("draft_reply_rules"),
                    agent_training=state.get("agent_training"),
                )
                if draft_text:
                    draft_replies[msg_id] = draft_text
                    _trace(traces, msg_id, "generate_drafts", "draft_llm", True)
                else:
                    errors.append(f"{msg_id}: draft LLM returned empty text")
                    _trace(traces, msg_id, "generate_drafts", "draft_llm", False, error="empty")
            except Exception as exc:
                errors.append(f"{msg_id}: {exc}")
                _trace(traces, msg_id, "generate_drafts", "draft_llm", False, error=str(exc))

        return {
            "draft_replies": draft_replies,
            "automation_traces": traces,
            "action_errors": errors,
            "current_node": "generate_drafts",
        }

    async def apply_draft_actions(state: PipelineState) -> dict:
        account = state["user_email"]
        messages = _messages(state)
        by_id = {str(m.get("id")): m for m in messages}
        classifications = state.get("classifications") or []
        rule_results = state.get("rule_results") or {}
        draft_replies = state.get("draft_replies") or {}
        action_records: dict[str, MessageActionRecord] = dict(
            state.get("action_records") or {}
        )
        traces = dict(state.get("automation_traces") or {})
        errors = list(state.get("action_errors") or [])

        for classification in classifications:
            msg_id = classification["message_id"]
            if (rule_results.get(msg_id) or {}).get("skip_llm"):
                continue
            if not classification.get("needs_response_generation"):
                continue

            message = by_id.get(msg_id)
            if not message:
                continue

            record = action_records.get(msg_id) or {
                "message_id": msg_id,
                "category": classification["category"],
                "is_spam": classification.get("is_spam", False),
                "folder_path": None,
                "folder_moved": False,
                "forwarded_to": None,
                "draft_saved": False,
                "draft_reply_text": None,
                "error": None,
            }

            draft_text = draft_replies.get(msg_id)
            if not draft_text:
                record["error"] = record.get("error") or "Expected draft text was not generated"
                action_records[msg_id] = record
                continue

            record["draft_reply_text"] = draft_text
            for attempt in range(2):
                try:
                    saved = await ctx.executor.apply_response_draft(
                        account, message, draft_text
                    )
                    record["draft_saved"] = saved
                    _trace(traces, msg_id, "apply_draft_actions", "save_draft", True)
                    break
                except Exception as exc:
                    if attempt == 1:
                        record["error"] = str(exc)
                        errors.append(f"{msg_id}: save_draft failed: {exc}")
                        _trace(traces, msg_id, "apply_draft_actions", "save_draft", False, error=str(exc))
            record["automation_trace"] = traces.get(msg_id)
            action_records[msg_id] = record

        return {
            "action_records": action_records,
            "automation_traces": traces,
            "action_errors": errors,
            "current_node": "apply_draft_actions",
        }

    async def persist_message_actions(state: PipelineState) -> dict:
        account = state["user_email"]
        conn = _conn(state)
        messages = _messages(state)
        classifications = state.get("classifications") or []
        action_records: dict[str, MessageActionRecord] = dict(
            state.get("action_records") or {}
        )
        actions_taken: list[MessageActionRecord] = []
        errors = list(state.get("action_errors") or [])

        if not ctx.email_repository or conn is None:
            return {
                "actions_taken": [],
                "action_errors": ["email_repository not configured"],
                "current_node": "persist_message_actions",
            }

        class_by_id = {c["message_id"]: c for c in classifications}
        for message in messages:
            msg_id = str(message.get("id", ""))
            if not msg_id:
                continue
            if not state.get("force_reprocess") and await ctx.email_repository.is_message_processed(
                conn, account, msg_id
            ):
                continue

            record = action_records.get(msg_id)
            classification = class_by_id.get(msg_id)
            if not record and classification:
                record = {
                    "message_id": msg_id,
                    "category": classification.get("category"),
                    "is_spam": classification.get("is_spam", False),
                    "folder_path": None,
                    "folder_moved": False,
                    "forwarded_to": None,
                    "draft_saved": False,
                    "draft_reply_text": None,
                    "error": None,
                    "automation_trace": (state.get("automation_traces") or {}).get(msg_id),
                }

            if not record:
                continue

            try:
                await ctx.executor.persist_action(
                    conn,
                    account,
                    msg_id,
                    record,
                    classification,
                    automation_thread_id=state.get("automation_thread_id"),
                    report=state.get("report"),
                )
                actions_taken.append(record)
            except Exception as exc:
                errors.append(f"{msg_id}: persist failed: {exc}")

        zimbra_ids = [str(m.get("id")) for m in messages if m.get("id")]
        if zimbra_ids:
            await ctx.email_repository.mark_analyzed(conn, account, zimbra_ids)
        if hasattr(conn, "commit"):
            await conn.commit()

        return {
            "actions_taken": actions_taken,
            "action_errors": errors,
            "current_node": "persist_message_actions",
        }

    return {
        "ingest_mailbox": base_nodes["ingest_mailbox"],
        "enrich_messages": base_nodes["enrich_messages"],
        "apply_automation_rules": apply_automation_rules,
        "persist_rule_matched": persist_rule_matched,
        "classify_messages": classify_messages,
        "apply_routing_actions": apply_routing_actions,
        "fetch_shopify_context": fetch_shopify_context,
        "generate_drafts": generate_drafts,
        "apply_draft_actions": apply_draft_actions,
        "persist_message_actions": persist_message_actions,
        "format_run_report": base_nodes["format_run_report"],
    }
