from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import settings
from app.db.email_repository import require_postgres_database_url
from app.db.pool import close_pool, init_pool
from app.services.email_sync import EmailSyncService

OPENAPI_TAGS = [
    {
        "name": "System",
        "description": "Health checks and Zimbra connectivity tests.",
    },
    {
        "name": "Users",
        "description": "List and look up Zimbra mail accounts.",
    },
    {
        "name": "Mailboxes",
        "description": "View inbox, search messages, read content, and list folders for any user.",
    },
    {
        "name": "Sync",
        "description": "Bulk mailbox export endpoints for automation workflows.",
    },
    {
        "name": "Automation",
        "description": "Per-message and mailbox-wide email automation pipelines.",
    },
    {
        "name": "Agent",
        "description": "Global agent training and classification/routing rules.",
    },
]


@asynccontextmanager
async def lifespan(application: FastAPI):
    await init_pool(require_postgres_database_url(settings.database_url))
    application.state.email_service = EmailSyncService(settings)
    try:
        yield
    finally:
        await close_pool()


def create_app() -> FastAPI:
    application = FastAPI(
        title="Zimbra Email Automation API",
        description=(
            "REST API for Zimbra mail automation using admin credentials.\n\n"
            "**Key capabilities**\n"
            "- List all mail users on the server\n"
            "- View any user's inbox (paginated)\n"
            "- Search messages and fetch full content\n"
            "- List mailbox folders\n"
            "- Bulk sync mailboxes for automation\n"
            "- Per-message automation (classify, route, draft)\n\n"
            "**Note:** When using email addresses in URL paths, encode `@` as `%40` "
            "(e.g. `mayank.gautam%40mail.gkhair.com`)."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        swagger_ui_parameters={
            "docExpansion": "list",
            "defaultModelsExpandDepth": 2,
            "tryItOutEnabled": True,
            "persistAuthorization": True,
        },
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router)

    @application.get("/", tags=["System"], summary="API index")
    async def root():
        return {
            "service": "zimbra-email-automation",
            "version": "1.0.0",
            "swagger": "/docs",
            "redoc": "/redoc",
            "openapi": "/openapi.json",
            "api_base": "/api/v1",
            "endpoints": {
                "list_users": "GET /api/v1/users",
                "user_inbox": "GET /api/v1/users/{email}/inbox",
                "search_messages": "GET /api/v1/users/{email}/messages",
                "get_message": "GET /api/v1/users/{email}/messages/{id}",
                "list_folders": "GET /api/v1/users/{email}/folders",
                "sync_all": "POST /api/v1/sync",
                "run_automation": "POST /api/v1/automation/users/{email}/messages/{id}/run",
                "agent_training": "GET /api/v1/agent/training",
                "agent_general_rules": "PUT /api/v1/agent/training/general-rules",
                "agent_draft_reply_rules": "PUT /api/v1/agent/training/draft-reply-rules",
                "classification_rules": "GET/PUT /api/v1/agent/classification-rules",
            },
        }

    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )
