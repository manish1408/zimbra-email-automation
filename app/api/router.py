from fastapi import APIRouter

from app.api.routes import agent, automation, local, mailboxes, sync, system, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(users.router)
api_router.include_router(mailboxes.router)
api_router.include_router(sync.router)
api_router.include_router(agent.router)
api_router.include_router(automation.router)
api_router.include_router(local.router)
