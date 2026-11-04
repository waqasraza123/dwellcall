import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from dwellcall.consultant.catalog import PropertyRequirements, load_catalog
from dwellcall.consultant.graph import PropertyConsultant
from dwellcall.consultant.state import AI_ONLY_HANDOFF_REPLY, ConsultationSession, RequirementExtraction
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.schemas import Response, Utterance


@pytest.mark.parametrize("message", [
    "A human please", "Can I speak to a human?", "Connect me to a real person",
    "Transfer me", "Please let me talk to a live agent", "I need a supervisor",
])
def test_human_requests_receive_the_ai_only_explanation_without_model_calls(settings: ApiSettings, message: str) -> None:
    async def check() -> None:
        consultant = PropertyConsultant(settings, load_catalog(settings))
        consultant._extractor = AsyncMock()
        consultant._extractor.ainvoke.side_effect = AssertionError("Human requests must not depend on extraction")
        consultant._model = Mock()
        consultant._model.astream.side_effect = AssertionError("Human requests must use the fixed explanation")
        session = ConsultationSession()
        try:
            reply = "".join([part async for part in consultant.stream([Utterance(role="user", content=message)], session)])
            assert reply == AI_ONLY_HANDOFF_REPLY and not session.end_call
        finally:
            await consultant.close()
    asyncio.run(check())


def test_model_classified_handoff_receives_the_same_permanent_explanation(settings: ApiSettings) -> None:
    session = ConsultationSession()
    update = session.propose(RequirementExtraction(requirements=PropertyRequirements(), intent="handoff"), [Utterance(role="user", content="Could somebody else take over?")], settings)
    assert update.reply == AI_ONLY_HANDOFF_REPLY and not update.end_call


def test_yes_after_a_legacy_transfer_question_cannot_authorize_a_transfer(settings: ApiSettings) -> None:
    session = ConsultationSession()
    update = session.propose(RequirementExtraction(requirements=PropertyRequirements()), [Utterance(role="agent", content="Would you like to connect to a human?"), Utterance(role="user", content="yes")], settings)
    session.commit(update)
    with pytest.raises(ValidationError):
        Response(response_id=1, content="", content_complete=True, transfer_number="+12025550125")


@pytest.mark.parametrize(("scenario", "budget", "bedrooms"), [("renting", 2300, 1), ("buying", 700000, 3), ("luxury", 1500000, 4)])
def test_phone_graph_reuses_existing_requirements_across_turns(settings: ApiSettings, scenario: str, budget: int, bedrooms: int) -> None:
    async def check() -> None:
        consultant = PropertyConsultant(settings, load_catalog(settings))
        consultant._extractor = AsyncMock()
        needs = PropertyRequirements.model_validate({"scenario": scenario, "max_budget": budget, "bedrooms": bedrooms})
        consultant._extractor.ainvoke.return_value = RequirementExtraction(requirements=needs, intent="review")
        session = ConsultationSession(requirements=PropertyRequirements.model_validate({"scenario": scenario}))
        try:
            parts = [part async for part in consultant.stream([Utterance(role="user", content="Please recap my purchase requirements")], session)]
            assert session.requirements == needs and session.pending_readback == "".join(parts)
            consultant._extractor.ainvoke.return_value = RequirementExtraction(requirements=needs)
            transcript = [Utterance(role="agent", content="".join(parts)), Utterance(role="user", content="yes")]
            reply = "".join([part async for part in consultant.stream(transcript, session)])
            assert session.confirmed_version == session.version and "confirmed" in reply
            assert ConsultationSession().confirmed_version is None
        finally:
            await consultant.close()
    asyncio.run(check())
