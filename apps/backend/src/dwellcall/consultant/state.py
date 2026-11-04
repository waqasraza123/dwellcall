from dataclasses import dataclass, field
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dwellcall.consultant.catalog import PropertyRequirements
from dwellcall.consultant.spoken import normalized_speech, require_spoken_confirmation
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.schemas import Utterance

Intent = Literal["continue", "compare", "review", "objection", "handoff"]
CLOSING_PHRASES = frozenset({
    "bye", "goodbye", "thanks goodbye", "thank you goodbye", "that s all",
    "thats all", "that is all", "that s all thank you", "thats all thanks",
    "end the call", "please end the call", "please stop", "stop the call",
    "stop", "end call", "hang up", "please hang up", "i am done", "i m done",
    "im done", "no thanks goodbye", "thats all thank you", "that s all thanks",
})
REJECTIONS = frozenset({"no", "no that s wrong", "no thats wrong", "that s not correct", "not correct"})
AI_ONLY_HANDOFF_REPLY = (
    "DwellCall is an AI-native voice platform operated only by AI agents. "
    "There are no human agents to transfer you to. I can keep helping you here."
)


def human_handoff_requested(transcript: list[Utterance]) -> bool:
    if not transcript or transcript[-1].role != "user":
        return False
    speech = normalized_speech(transcript[-1].content)
    return speech in {
        "human", "a human", "a human please", "human please", "a real person please",
        "real person", "human agent", "a live agent", "someone real",
        "operator", "operator please", "a representative please", "live agent",
        "transfer me", "please transfer me", "can you transfer me",
        "can you please transfer me", "transfer this call", "i want a human",
    } or re.search(
        r"\b(?:speak|talk|connect|transfer|handoff|hand off|put me through|can i get|i want|i need|may i have|i would like|i d like|let me|give me|send me|pass me|get me)\b"
        r".{0,100}\b(?:human|person|operator|representative|supervisor|manager|live agent|real estate agent)\b",
        speech,
    ) is not None


def closing_requested(transcript: list[Utterance]) -> bool:
    return bool(
        transcript and transcript[-1].role == "user"
        and normalized_speech(transcript[-1].content) in CLOSING_PHRASES
    )


class RequirementExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirements: PropertyRequirements
    intent: Intent = "continue"
    compare_ids: tuple[str, ...] = Field(default=(), max_length=3)
    objection: Literal["budget", "location", "features", "timing", "other"] | None = None


def requirement_summary(needs: PropertyRequirements, settings: ApiSettings) -> str:
    parts = [f"Fictional {needs.scenario or 'property'} consultation in {needs.location or settings.supported_location}."]
    if needs.max_budget is not None:
        period = "per month" if needs.scenario == "renting" else "purchase budget"
        parts.append(f"Maximum budget: {settings.currency} {needs.max_budget} {period}.")
    if needs.bedrooms is not None:
        parts.append(f"Minimum bedrooms: {needs.bedrooms}.")
    if needs.neighborhood:
        parts.append(f"Requested neighborhood: {needs.neighborhood}.")
    if needs.move_in:
        parts.append(f"Requested timing: {needs.move_in}.")
    if needs.pets is not None:
        parts.append("Pets: yes." if needs.pets else "Pets: no.")
    if needs.must_have:
        parts.append("Required features: " + ", ".join(needs.must_have) + ".")
    summary = " ".join(parts)
    if len(summary) > 1000:
        raise ValueError("Shorten the requirements before preparing a consultation summary")
    return summary


def requirements_readback(needs: PropertyRequirements, version: int, settings: ApiSettings) -> str:
    return (
        f"Requirements revision {version}. {requirement_summary(needs, settings)} "
        "Is that correct? Say yes to confirm these requirements, or tell me what to correct. "
        "This does not grant storage, CRM or contact permission."
    )


@dataclass(frozen=True)
class ConsultationUpdate:
    requirements: PropertyRequirements
    version: int
    confirmed_version: int | None
    pending_readback: str | None
    confirmed_summary: str | None
    reply: str | None = None
    end_call: bool = False


@dataclass
class ConsultationSession:
    requirements: PropertyRequirements = field(default_factory=PropertyRequirements)
    version: int = 0
    confirmed_version: int | None = None
    pending_readback: str | None = None
    confirmed_summary: str | None = None
    end_call: bool = False

    def propose(
        self, extraction: RequirementExtraction, transcript: list[Utterance],
        settings: ApiSettings,
    ) -> ConsultationUpdate:
        needs = extraction.requirements
        changed = needs != self.requirements
        version = self.version + int(changed)
        confirmed = None if changed else self.confirmed_version
        summary = None if changed else self.confirmed_summary
        readback = None if changed else self.pending_readback
        latest = transcript[-1] if transcript else None
        speech = normalized_speech(latest.content) if latest and latest.role == "user" else ""
        if speech in REJECTIONS:
            if confirmed is not None and not changed:
                version += 1
            confirmed, summary, readback = None, None, None
        reply = None
        if human_handoff_requested(transcript) or extraction.intent == "handoff":
            return ConsultationUpdate(needs, version, confirmed, None, summary, AI_ONLY_HANDOFF_REPLY)
        if readback and needs.ready:
            try:
                require_spoken_confirmation(transcript, readback)
            except ValueError:
                readback = None
            else:
                confirmed = version
                summary = requirement_summary(needs, settings)
                readback = None
                reply = "Thank you, those requirements are confirmed. Would you like to compare any of the fictional examples?"
        if speech in CLOSING_PHRASES:
            return ConsultationUpdate(
                needs, version, confirmed, None, summary,
                "Thank you for exploring these fictional homes. No showing or follow-up has been arranged. Goodbye.",
                True,
            )
        if reply is None and extraction.intent == "review" and needs.ready:
            try:
                readback = requirements_readback(needs, version, settings)
            except ValueError:
                reply = "There are too many details to recap at once. Which requirements are most important to keep?"
            else:
                reply = readback
        return ConsultationUpdate(needs, version, confirmed, readback, summary, reply)

    def commit(self, update: ConsultationUpdate) -> None:
        self.requirements = update.requirements
        self.version = update.version
        self.confirmed_version = update.confirmed_version
        self.pending_readback = update.pending_readback
        self.confirmed_summary = update.confirmed_summary
        self.end_call = update.end_call

    def confirmed_fields(self, settings: ApiSettings) -> dict[str, object]:
        if self.confirmed_version != self.version or self.confirmed_summary is None:
            raise ValueError("Confirm the current requirements before preparing a review")
        needs = self.requirements
        details = list(needs.must_have)
        if needs.bedrooms is not None:
            details.append(f"Minimum bedrooms: {needs.bedrooms}")
        if needs.neighborhood:
            details.append(f"Requested neighborhood: {needs.neighborhood}")
        if needs.move_in:
            details.append(f"Requested timing: {needs.move_in}")
        if needs.pets is not None:
            details.append("Pets: yes" if needs.pets else "Pets: no")
        return {
            "scenario": needs.scenario,
            "budget": {
                "amount": str(needs.max_budget), "currency": settings.currency,
                "period": "monthly" if needs.scenario == "renting" else "purchase",
            },
            "location": needs.location or settings.supported_location,
            "requirements": details,
            "summary": self.confirmed_summary,
            "fictional_properties": True,
        }
