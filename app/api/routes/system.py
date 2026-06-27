from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_email_service, get_settings
from app.config import Settings
from app.models.schemas import ConnectionTestResponse, HealthResponse
from app.services.email_sync import EmailSyncService

router = APIRouter(prefix="/system", tags=["System"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns API status and configured Zimbra host.",
)
async def health(
    config: Settings = Depends(get_settings),
    service: EmailSyncService = Depends(get_email_service),
):
    connected, _, _ = await service.test_connection()
    return HealthResponse(
        status="ok",
        zimbra_host=config.zimbra_host,
        zimbra_connected=connected,
    )


@router.get(
    "/test-connection",
    response_model=ConnectionTestResponse,
    summary="Test Zimbra connection",
    description="Authenticates with Zimbra admin SOAP API and returns account count.",
)
async def test_connection(
    config: Settings = Depends(get_settings),
    service: EmailSyncService = Depends(get_email_service),
):
    connected, count, message = await service.test_connection()
    if not connected:
        raise HTTPException(status_code=502, detail=message)
    return ConnectionTestResponse(
        connected=connected,
        zimbra_host=config.zimbra_host,
        admin_user=config.zimbra_admin_user,
        account_count=count,
        message=message,
    )
