from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str
    zimbra_host: str
    zimbra_connected: bool = False


class ConnectionTestResponse(BaseModel):
    connected: bool
    zimbra_host: str
    admin_user: str
    account_count: int = 0
    message: str


class User(BaseModel):
    """Zimbra mail account."""

    model_config = ConfigDict(json_schema_extra={"example": {"id": "abc-123", "email": "user@mail.gkhair.com", "display_name": "Jane Doe", "status": "active"}})

    id: str
    email: str
    display_name: str | None = None
    status: str | None = None


class UserListResponse(BaseModel):
    total: int
    users: list[User]


class MessageSummary(BaseModel):
    id: str
    account: str
    subject: str | None = None
    from_address: str | None = Field(default=None, serialization_alias="from")
    to_addresses: list[str] = Field(default_factory=list, serialization_alias="to")
    date: str | None = None
    fragment: str | None = None
    folder: str | None = None
    size: int | None = None
    is_read: bool | None = None

    model_config = ConfigDict(populate_by_name=True)


class MessageDetail(MessageSummary):
    body: str | None = None


class InboxResponse(BaseModel):
    user: User
    query: str = "in:inbox"
    total: int
    limit: int
    offset: int
    has_more: bool
    messages: list[MessageSummary]


class MessageSearchResponse(BaseModel):
    user: User
    query: str
    total: int
    limit: int
    offset: int
    has_more: bool
    messages: list[MessageSummary]


class Folder(BaseModel):
    id: str
    name: str
    path: str | None = None
    unread_count: int | None = None
    message_count: int | None = None


class FolderListResponse(BaseModel):
    user: User
    folders: list[Folder]


class AccountMessages(BaseModel):
    user: User
    message_count: int
    messages: list[MessageSummary]


class SyncResult(BaseModel):
    accounts_processed: int
    total_messages: int
    accounts: list[AccountMessages]


class GraphNodeSchema(BaseModel):
    name: str


class GraphEdgeSchema(BaseModel):
    from_node: str = Field(alias="from")
    to: str | None = None
    condition: str | None = None
    paths: list[str] | None = None

    model_config = ConfigDict(populate_by_name=True)


class GraphSchemaResponse(BaseModel):
    name: str
    entrypoint: str
    nodes: list[GraphNodeSchema]
    edges: list[GraphEdgeSchema]


class AgentRunRequest(BaseModel):
    user_email: str = Field(description="Mailbox to analyze")
    limit: int | None = Field(default=None, ge=1, le=50)
    instruction: str | None = Field(default=None, description="Optional focus for triage")
    session_id: str | None = Field(default=None, description="Demo session identifier")


class AgentRunResult(BaseModel):
    thread_id: str
    user_email: str
    dominant_intent: str | None = None
    dominant_category: str | None = None
    message_count: int = 0
    classifications: list[dict] = Field(default_factory=list)
    compliance_flags: list[str] = Field(default_factory=list)
    sales_insights: str | None = None
    summary: str | None = None
    executive_report: str | None = None
    draft_reply: str | None = None
    archive_suggestion: str | None = None
    report: dict = Field(default_factory=dict)
