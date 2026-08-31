from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    zimbra_host: str
    zimbra_admin_port: int = 7071
    zimbra_mail_port: int = 443
    zimbra_use_https: bool = True
    zimbra_verify_ssl: bool = False

    zimbra_admin_user: str
    zimbra_admin_password: str

    zimbra_domain_filter: str | None = None
    zimbra_search_query: str = "is:anywhere"
    zimbra_search_batch_size: int = 100

    app_host: str = "0.0.0.0"
    app_port: int = 8000

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # LLM provider: vastai (Ollama /api/generate) or openai
    llm_provider: str = "vastai"
    vastai_base_url: str = ""
    vastai_token: str = ""
    vastai_model: str = "qwen3.5:35b"
    vastai_cookie_name: str = ""
    vastai_timeout_seconds: float = 300.0

    agent_inbox_limit: int = 10

    # Scheduled sync + AI analysis
    sync_poll_all_mailboxes: bool = True
    sync_target_email: str | None = None
    # Comma/newline-separated mailbox allowlist. When set, automation polls
    # only these active accounts (SYNC_POLL_ALL_MAILBOXES still uses run_all).
    sync_mailboxes: str = ""
    sync_interval_hours: float = 6.0
    database_url: str = "postgresql://zimbra:zimbra_dev@localhost:5432/zimbra_automation"
    sync_fetch_bodies: bool = True
    sync_poll_interval_seconds: int = 60
    sync_inbox_query: str = "in:inbox"
    # Also poll Junk/Spam so client-marked spam is visible locally and to automation.
    sync_include_junk: bool = True
    sync_junk_query: str = "in:junk"
    sync_overlap_minutes: int = 5

    # Automation actions
    automation_dry_run: bool = True
    automation_move_to_folders: bool = True
    automation_auto_replies_folder: str = "Auto Replies"
    # Minimum LLM confidence required to mark sales/marketing mail as spam / move to Junk
    spam_confidence_threshold: float = 0.75

    # Shopify Bot API (order / invoice lookups)
    shopify_bot_base_url: str = "https://bot.gkhair.com"
    shopify_bot_api_key: str = ""
    shopify_bot_timeout_seconds: float = 30.0

    @property
    def sync_mailbox_allowlist(self) -> list[str]:
        raw = self.sync_mailboxes or ""
        seen: set[str] = set()
        emails: list[str] = []
        for chunk in raw.replace("\n", ",").replace(";", ",").split(","):
            email = chunk.strip().lower()
            if email and email not in seen:
                seen.add(email)
                emails.append(email)
        return emails

    @property
    def scheme(self) -> str:
        return "https" if self.zimbra_use_https else "http"

    @property
    def admin_soap_url(self) -> str:
        return f"{self.scheme}://{self.zimbra_host}:{self.zimbra_admin_port}/service/admin/soap"

    @property
    def mail_soap_url(self) -> str:
        return f"{self.scheme}://{self.zimbra_host}:{self.zimbra_mail_port}/service/soap"


settings = Settings()
