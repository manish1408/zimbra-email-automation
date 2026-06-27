from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.agents.schema import load_graph_schema
from app.config import settings
from app.models.schemas import (
    AgentRunRequest,
    AgentRunResult,
    GraphEdgeSchema,
    GraphNodeSchema,
    GraphSchemaResponse,
)

router = APIRouter(prefix="/agent", tags=["Agent"])

GRAPH_NODE_NAMES = {
    "ingest_mailbox",
    "enrich_messages",
    "classify_intent",
    "urgent_escalation",
    "compliance_review",
    "sales_pipeline",
    "support_agent",
    "zimbra_tools",
    "draft_support_reply",
    "newsletter_batch",
    "general_briefing",
    "merge_insights",
    "quality_review",
    "refine_output",
    "format_executive_report",
}


def _thread_id(request: AgentRunRequest) -> str:
    session_id = request.session_id or uuid.uuid4().hex[:8]
    return f"demo:{request.user_email}:{session_id}"


def _initial_state(request: AgentRunRequest) -> dict[str, Any]:
    return {
        "user_email": request.user_email,
        "limit": request.limit or settings.agent_inbox_limit,
        "instruction": request.instruction,
    }


def _to_run_result(thread_id: str, state: dict[str, Any]) -> AgentRunResult:
    report = state.get("report") or {}
    dominant = report.get("dominant_intent") or state.get("dominant_intent")
    return AgentRunResult(
        thread_id=thread_id,
        user_email=state.get("user_email") or report.get("user_email") or "",
        dominant_intent=dominant,
        dominant_category=dominant,
        message_count=report.get("message_count", len(state.get("messages") or [])),
        classifications=report.get("classifications") or state.get("classifications") or [],
        compliance_flags=report.get("compliance_flags") or state.get("compliance_flags") or [],
        sales_insights=report.get("sales_insights") or state.get("sales_insights"),
        summary=report.get("summary") or state.get("merged_insights") or state.get("branch_output"),
        executive_report=report.get("executive_report") or state.get("executive_report"),
        draft_reply=report.get("draft_reply") or state.get("draft_reply"),
        archive_suggestion=report.get("archive_suggestion") or state.get("archive_suggestion"),
        report=report,
    )


@router.get(
    "/schema",
    response_model=GraphSchemaResponse,
    summary="Agent graph schema",
    description="Returns the LangGraph Builder YAML schema for demo UI visualization.",
)
async def get_schema() -> GraphSchemaResponse:
    raw = load_graph_schema()
    edges = []
    for edge in raw.get("edges", []):
        edges.append(
            GraphEdgeSchema(
                **{
                    "from": edge.get("from", edge.get("from_node")),
                    "to": edge.get("to"),
                    "condition": edge.get("condition"),
                    "paths": edge.get("paths"),
                }
            )
        )
    nodes = [GraphNodeSchema(name=node["name"]) for node in raw.get("nodes", [])]
    return GraphSchemaResponse(
        name=raw.get("name", "EmailAgent"),
        entrypoint=raw.get("entrypoint", "fetch_inbox"),
        nodes=nodes,
        edges=edges,
    )


@router.post(
    "/run",
    response_model=AgentRunResult,
    summary="Run email agent",
    description="Synchronously execute the email automation LangGraph for a mailbox.",
)
async def run_agent(request_body: AgentRunRequest, request: Request) -> AgentRunResult:
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    graph = request.app.state.agent_graph
    thread_id = _thread_id(request_body)
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(_initial_state(request_body), config=config)
    return _to_run_result(thread_id, result)


@router.post(
    "/stream",
    summary="Stream agent execution",
    description="Server-Sent Events stream of node lifecycle and output updates.",
)
async def stream_agent(request_body: AgentRunRequest, request: Request) -> StreamingResponse:
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    graph = request.app.state.agent_graph
    thread_id = _thread_id(request_body)
    config = {"configurable": {"thread_id": thread_id}}

    async def event_generator():
        try:
            async for event in graph.astream_events(
                _initial_state(request_body),
                config=config,
                version="v2",
            ):
                event_type = event.get("event")
                payload: dict[str, Any] = {
                    "event": event_type,
                    "name": event.get("name"),
                }
                if event_type == "on_chain_start":
                    node_name = event.get("name")
                    if node_name not in GRAPH_NODE_NAMES:
                        continue
                    payload["type"] = "node_start"
                    payload["node"] = node_name
                elif event_type == "on_chain_end":
                    node_name = event.get("name")
                    if node_name not in GRAPH_NODE_NAMES:
                        continue
                    payload["type"] = "node_end"
                    payload["node"] = node_name
                    output = event.get("data", {}).get("output")
                    if isinstance(output, dict):
                        if output.get("report"):
                            payload["report"] = output["report"]
                        if output.get("classifications"):
                            payload["classifications"] = output["classifications"]
                        if output.get("summary"):
                            payload["summary"] = output["summary"]
                        if output.get("draft_reply"):
                            payload["draft_reply"] = output["draft_reply"]
                        if output.get("archive_suggestion"):
                            payload["archive_suggestion"] = output["archive_suggestion"]
                        if output.get("executive_report"):
                            payload["executive_report"] = output["executive_report"]
                        if output.get("compliance_flags"):
                            payload["compliance_flags"] = output["compliance_flags"]
                        if output.get("sales_insights"):
                            payload["sales_insights"] = output["sales_insights"]
                        if output.get("dominant_intent"):
                            payload["dominant_intent"] = output["dominant_intent"]
                        if output.get("dominant_category"):
                            payload["dominant_category"] = output["dominant_category"]
                elif event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    token = getattr(chunk, "content", None) if chunk else None
                    if token:
                        payload["type"] = "token"
                        payload["content"] = token
                yield f"data: {json.dumps(payload, default=str)}\n\n"
            snapshot = await graph.aget_state(config)
            final = _to_run_result(thread_id, snapshot.values if snapshot else {})
            yield f"data: {json.dumps({'type': 'done', 'result': final.model_dump()}, default=str)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, default=str)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/sessions/{thread_id}",
    summary="Inspect agent session",
    description="Return the latest checkpoint state for a demo thread.",
)
async def get_session(thread_id: str, request: Request) -> dict[str, Any]:
    graph = request.app.state.agent_graph
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "thread_id": thread_id,
        "state": snapshot.values,
        "next": snapshot.next,
    }
