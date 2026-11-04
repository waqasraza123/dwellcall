from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from dwellcall.admin_security import require_admin_token
from dwellcall.conversations.schemas import ConversationStarted, ConversationStatus, StartConversation, TextReply, TextTurn
from dwellcall.conversations.service import BrowserConversationService
from dwellcall.settings import ApiSettings

BrowserOwner = Annotated[str, Header(alias="X-Browser-Session", pattern=r"^[A-Za-z0-9_-]{43}$")]

def create_conversation_router(settings: ApiSettings, service: BrowserConversationService) -> APIRouter:
    def admin(token: Annotated[str | None, Header(alias="X-Admin-Token")] = None) -> None:
        require_admin_token(settings, token)

    router = APIRouter(prefix="/api/v1/browser-conversations", dependencies=[Depends(admin)])

    @router.get("/availability")
    def availability() -> dict[str, object]:
        return {"voice": settings.browser_voice_enabled or settings.browser_mock_enabled, "text": settings.browser_text_enabled or settings.browser_mock_enabled, "mock": settings.browser_mock_enabled, "max_seconds": settings.conversation_max_duration_seconds}

    @router.post("/sessions", response_model=ConversationStarted)
    async def start(data: StartConversation, owner: BrowserOwner) -> ConversationStarted:
        return await service.start(owner, data)

    @router.get("/sessions/{local_id}", response_model=ConversationStatus)
    def status(local_id: UUID, owner: BrowserOwner) -> ConversationStatus:
        return service.get(local_id, owner)

    @router.post("/sessions/{local_id}/turn", response_model=TextReply)
    async def turn(local_id: UUID, data: TextTurn, owner: BrowserOwner) -> TextReply:
        return await service.reply(owner, local_id, data)

    @router.post("/sessions/{local_id}/end", response_model=ConversationStatus)
    async def end(local_id: UUID, owner: BrowserOwner) -> ConversationStatus:
        return await service.end(owner, local_id)

    @router.post("/sessions/{local_id}/refresh", response_model=ConversationStatus)
    async def refresh(local_id: UUID, owner: BrowserOwner) -> ConversationStatus:
        return await service.refresh(owner, local_id)

    return router
