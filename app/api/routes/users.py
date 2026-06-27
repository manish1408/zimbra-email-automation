from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_email_service
from app.models.schemas import User, UserListResponse
from app.services.email_sync import EmailSyncService

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "",
    response_model=UserListResponse,
    summary="List all mail users",
    description="Returns every Zimbra mail account visible to the configured admin user.",
)
async def list_users(service: EmailSyncService = Depends(get_email_service)):
    try:
        return await service.list_users()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/{user_email}",
    response_model=User,
    summary="Get user by email",
    description="Look up a single Zimbra mail account. URL-encode `@` as `%40` (e.g. `user%40mail.gkhair.com`).",
)
async def get_user(
    user_email: str,
    service: EmailSyncService = Depends(get_email_service),
):
    try:
        user = await service.get_user(user_email)
        if not user.id:
            raise HTTPException(status_code=404, detail=f"User not found: {user_email}")
        return user
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
