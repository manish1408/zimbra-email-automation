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


class MailboxAutomationRunResponse(BaseModel):
    account: str
    thread_id: str | None = None
    analysis_run_id: int | None = None
    message_count: int = 0
    classified: int | None = None
    moved: int | None = None
    spam: int | None = None
    forwarded: int | None = None
    acked: int | None = None
    drafts: int | None = None
    dry_run: bool = False
    move_to_folders: bool = True
    skipped: bool = False
    reason: str | None = None
    errors: list[str] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class AccountSyncResult(AccountMessages):
    automation: MailboxAutomationRunResponse | None = None


class SyncResult(BaseModel):
    accounts_processed: int
    total_messages: int
    accounts: list[AccountMessages]


class AgentTrainingResponse(BaseModel):
    general_rules: str = ""
    draft_reply_rules: str = ""
    updated_at: str | None = None


class AgentTrainingGeneralUpdateRequest(BaseModel):
    general_rules: str = Field(default="", max_length=8000)


class AgentTrainingDraftReplyUpdateRequest(BaseModel):
    draft_reply_rules: str = Field(default="", max_length=8000)


class ClassificationConfigSchema(BaseModel):
    spam_folder: str = "Junk"
    default_forward: str | None = None
    ack_template: str = ""
    classification_instructions: str = ""


class ClassificationCategorySchema(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    classification_hints: str = ""
    folder: str = Field(min_length=1, max_length=128)
    forward_to: str | None = None
    send_ack: bool = True
    needs_live_agent: bool = False
    is_spam: bool = False
    route_by_person: bool = False
    skip_forward: bool = False
    sort_order: int = 0
    enabled: bool = True


class ClassificationEmployeeSchema(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=3, max_length=256)
    aliases: list[str] = Field(default_factory=list)


class ClassificationRulesResponse(BaseModel):
    config: ClassificationConfigSchema
    categories: list[ClassificationCategorySchema] = Field(default_factory=list)
    employees: list[ClassificationEmployeeSchema] = Field(default_factory=list)
    updated_at: str | None = None


class ClassificationRulesUpdateRequest(BaseModel):
    config: ClassificationConfigSchema
    categories: list[ClassificationCategorySchema] = Field(default_factory=list)
    employees: list[ClassificationEmployeeSchema] = Field(default_factory=list)


class MessageMetadata(BaseModel):
    zimbra_id: str
    account: str
    category: str | None = None
    is_spam: bool = False
    folder_path: str | None = None
    forwarded_to: str | None = None
    ack_sent_at: str | None = None
    draft_saved: bool = False
    classification: dict | None = None
    draft_reply_text: str | None = None
    ack_body_text: str | None = None
    report: dict | None = None
    error: str | None = None
    processed_at: str | None = None
    analyzed_at: str | None = None


class MessageAutomationRunRequest(BaseModel):
    force: bool = False


class MessageAutomationRunSummary(BaseModel):
    id: int
    thread_id: str
    status: str
    dry_run: bool = False
    classification: dict | None = None
    actions: dict | None = None
    draft_reply_text: str | None = None
    ack_body_text: str | None = None
    error: str | None = None
    created_at: str | None = None


class MessageAutomationResult(BaseModel):
    account: str
    message_id: str
    thread_id: str
    status: str
    dry_run: bool = False
    classification: dict | None = None
    actions: dict | None = None
    draft_reply_text: str | None = None
    ack_body_text: str | None = None
    report: dict = Field(default_factory=dict)
    error: str | None = None
    processed_at: str | None = None
    runs: list[MessageAutomationRunSummary] = Field(default_factory=list)


class MessageAutomationRunListResponse(BaseModel):
    account: str
    message_id: str
    runs: list[MessageAutomationRunSummary]


class LocalMailboxStats(BaseModel):
    account: str
    total: int
    unanalyzed: int
    last_seen_date: str | None = None
    last_poll_at: str | None = None
    last_poll_new_count: int = 0


class LocalMessageListResponse(BaseModel):
    account: str
    total: int
    limit: int
    offset: int
    has_more: bool
    messages: list[MessageSummary]


class AnalysisRunSummary(BaseModel):
    id: int
    account: str
    thread_id: str
    dominant_intent: str | None = None
    message_count: int | None = None
    report: dict = Field(default_factory=dict)
    created_at: str | None = None


class AnalysisRunListResponse(BaseModel):
    account: str
    runs: list[AnalysisRunSummary]
