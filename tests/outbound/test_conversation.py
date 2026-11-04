import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from dwellcall.consultant.catalog import PropertyRequirements, load_catalog
from dwellcall.consultant.graph import PropertyConsultant
from dwellcall.consultant.state import ConsultationSession, RequirementExtraction, TRANSFER_PROMPT
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.schemas import Utterance


def handoff(session: ConsultationSession, settings: ApiSettings) -> None:
    session.commit(session.propose(RequirementExtraction(requirements=PropertyRequirements(), intent="handoff"), [Utterance(role="user", content="Please connect me to a human")], settings))


def test_transfer_requires_an_entire_spoken_prompt_and_separate_yes(settings: ApiSettings) -> None:
    session = ConsultationSession(transfer_enabled=True)
    handoff(session, settings)
    assert session.pending_transfer_prompt == TRANSFER_PROMPT and not session.transfer_requested
    session.commit(session.propose(RequirementExtraction(requirements=PropertyRequirements()), [
        Utterance(role="agent", content=TRANSFER_PROMPT), Utterance(role="user", content="yes"),
    ], settings))
    assert session.transfer_requested and not session.end_call


@pytest.mark.parametrize(("spoken", "reply"), [(TRANSFER_PROMPT[:25], "yes"), ("I can help with properties", "yes"), (TRANSFER_PROMPT, "yes but call another number"), (TRANSFER_PROMPT, "no"), (TRANSFER_PROMPT, "maybe")])
def test_interruption_ambiguity_and_model_selected_destinations_cannot_authorize_transfer(settings: ApiSettings, spoken: str, reply: str) -> None:
    session = ConsultationSession(transfer_enabled=True)
    handoff(session, settings)
    session.commit(session.propose(RequirementExtraction(requirements=PropertyRequirements()), [Utterance(role="agent", content=spoken), Utterance(role="user", content=reply)], settings))
    assert not session.transfer_requested


def test_cancelled_phone_readback_never_creates_transfer_permission(settings: ApiSettings) -> None:
    async def check() -> None:
        consultant = PropertyConsultant(settings, load_catalog(settings))
        consultant._extractor = AsyncMock()
        consultant._extractor.ainvoke.return_value = RequirementExtraction(requirements=PropertyRequirements(scenario="renting"), intent="handoff")
        consultant._model = Mock()
        consultant._model.astream.side_effect = AssertionError("Handoff readback should use the existing deterministic node")
        session = ConsultationSession(transfer_enabled=True)
        stream = consultant.stream([Utterance(role="user", content="A human please")], session)
        try:
            assert await anext(stream) == TRANSFER_PROMPT
            await stream.aclose()
            assert session.pending_transfer_prompt is None and not session.transfer_requested
        finally:
            await stream.aclose()
            await consultant.close()
    asyncio.run(check())


def test_phone_graph_reuses_existing_requirements_across_turns(settings: ApiSettings) -> None:
    async def check() -> None:
        consultant = PropertyConsultant(settings, load_catalog(settings))
        consultant._extractor = AsyncMock()
        needs = PropertyRequirements(scenario="buying", max_budget=700000, bedrooms=3)
        consultant._extractor.ainvoke.return_value = RequirementExtraction(requirements=needs, intent="review")
        session = ConsultationSession(transfer_enabled=True)
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
