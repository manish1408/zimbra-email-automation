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
    agent_checkpoint_path: str = "data/agent_checkpoints.db"

    # Scheduled sync + AI analysis
    sync_target_email: str | None = None
    sync_interval_hours: float = 6.0
    database_url: str = "sqlite:///data/emails.db"
    sync_fetch_bodies: bool = True
    sync_poll_interval_seconds: int = 60
    sync_inbox_query: str = "in:inbox"
    sync_overlap_minutes: int = 5

    # Automation actions
    automation_dry_run: bool = True
    automation_move_to_folders: bool = True
    auto_send_ack: bool = True
    routing_rules_path: str = "config/routing_rules.yaml"
    employees_path: str = "config/employees.yaml"

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
