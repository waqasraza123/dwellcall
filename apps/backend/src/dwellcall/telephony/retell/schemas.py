from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

CallId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,200}$")]


class RetellCall(BaseModel):
    model_config = ConfigDict(strict=True)

    call_id: CallId
    agent_id: str = Field(min_length=1, max_length=200)
    agent_version: int = Field(ge=0)
    call_type: Literal["web_call", "phone_call"]
    call_status: Literal["registered", "not_connected", "ongoing", "ended", "error"]
    start_timestamp: int | None = Field(default=None, ge=0)


class Utterance(BaseModel):
    model_config = ConfigDict(strict=True)

    role: Literal["agent", "user", "system"]
    content: str = Field(max_length=2000)


class TranscriptEvent(BaseModel):
    model_config = ConfigDict(strict=True)

    transcript: list[Utterance] = Field(max_length=60)

    @model_validator(mode="after")
    def bounded_transcript(self) -> "TranscriptEvent":
        if sum(len(turn.content) for turn in self.transcript) > 30000:
            raise ValueError("Transcript exceeds the conversation limit")
        return self


class ResponseRequired(TranscriptEvent):
    interaction_type: Literal["response_required", "reminder_required"]
    response_id: int = Field(ge=0)


class UpdateOnly(TranscriptEvent):
    interaction_type: Literal["update_only"]


class PingPong(BaseModel):
    model_config = ConfigDict(strict=True)

    interaction_type: Literal["ping_pong"]
    timestamp: int


class CallDetails(BaseModel):
    interaction_type: Literal["call_details"]
    call: RetellCall


REQUEST = TypeAdapter(
    Annotated[
        ResponseRequired | UpdateOnly | PingPong | CallDetails,
        Field(discriminator="interaction_type"),
    ]
)


class RetellWebhook(BaseModel):
    event: Literal["call_started", "call_ended", "call_analyzed"]
    call: RetellCall


class ConfigResponse(BaseModel):
    response_type: Literal["config"] = "config"
    config: dict[str, bool] = Field(
        default_factory=lambda: {"auto_reconnect": False, "call_details": True}
    )


class PingPongResponse(BaseModel):
    response_type: Literal["ping_pong"] = "ping_pong"
    timestamp: int


class Response(BaseModel):
    response_type: Literal["response"] = "response"
    response_id: int
    content: str
    content_complete: bool
    end_call: bool = False
