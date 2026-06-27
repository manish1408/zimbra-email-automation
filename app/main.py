from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.graph import build_graph
from app.api.router import api_router
from app.config import settings
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
        "name": "Agent",
        "description": "LangGraph email automation agent with streaming demo endpoints.",
    },
]

STATIC_DEMO_DIR = Path(__file__).resolve().parent / "static" / "demo"


@asynccontextmanager
async def lifespan(application: FastAPI):
    checkpoint_path = Path(settings.agent_checkpoint_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    email_service = EmailSyncService(settings)
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
        await checkpointer.setup()
        application.state.email_service = email_service
        application.state.agent_graph = build_graph(
            email_service=email_service,
            settings=settings,
            checkpointer=checkpointer,
        )
        yield


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
            "- LangGraph email agent with live demo UI at `/demo`\n\n"
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

    if STATIC_DEMO_DIR.is_dir():
        application.mount("/demo", StaticFiles(directory=str(STATIC_DEMO_DIR), html=True), name="demo")

    @application.get("/", tags=["System"], summary="API index")
    async def root():
        return {
            "service": "zimbra-email-automation",
            "version": "1.0.0",
            "demo": "/demo",
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
                "agent_run": "POST /api/v1/agent/run",
                "agent_stream": "POST /api/v1/agent/stream",
                "agent_schema": "GET /api/v1/agent/schema",
            },
        }

    @application.get("/demo-ui", include_in_schema=False)
    async def demo_redirect():
        return RedirectResponse(url="/demo/")

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
