from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dwellcall.consultant.catalog import PropertyRequirements
from dwellcall.telephony.retell.schemas import TranscriptEvent, Utterance


class StartConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    mode: Literal["voice", "text"]
    scenario: Literal["renting", "buying", "luxury"]
    ai_consent: Literal[True]
    fictional_data_only: Literal[True]

    @field_validator("ai_consent", "fictional_data_only", mode="before")
    @classmethod
    def explicit_consent(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Confirm AI processing and use fictional property information only")
        return value


class TextTurn(TranscriptEvent):
    state_token: str = Field(min_length=1, max_length=16000)

    @field_validator("transcript")
    @classmethod
    def user_message_required(cls, turns: list[Utterance]) -> list[Utterance]:
        if not turns or turns[-1].role != "user" or not turns[-1].content.strip() or any(turn.role == "system" for turn in turns):
            raise ValueError("End the transcript with a user message; system messages are not accepted")
        return turns


class TextState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID
    turn: int = Field(ge=0)
    requirements: PropertyRequirements
    version: int = Field(default=0, ge=0)
    confirmed_version: int | None = Field(default=None, ge=0)
    pending_readback: str | None = Field(default=None, max_length=2000)
    confirmed_summary: str | None = Field(default=None, max_length=2000)


class ConversationStatus(BaseModel):
    id: UUID
    mode: Literal["voice", "text"]
    scenario: Literal["renting", "buying", "luxury"]
    status: Literal["active", "unknown", "ended"]
    mock: bool
    expires_at: datetime
    provider_call_id: str | None
    turn_count: int
    turn_in_flight: bool


class ConversationStarted(BaseModel):
    conversation: ConversationStatus
    greeting: str
    state_token: str | None = None
    grant: dict[str, object] | None = None


class TextReply(BaseModel):
    reply: str
    state_token: str
    conversation: ConversationStatus
