import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock

from langchain_core.messages import AIMessageChunk

from dwellcall.consultant.catalog import PropertyRequirements, load_catalog
from dwellcall.consultant.graph import PropertyConsultant
from dwellcall.consultant.state import ConsultationSession, RequirementExtraction
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.schemas import Utterance


def test_graph_streams_only_reply_and_passes_filtered_catalog(settings: ApiSettings) -> None:
    async def check() -> None:
        consultant = PropertyConsultant(settings, load_catalog(settings))
        extraction = RequirementExtraction(requirements=PropertyRequirements(
            scenario="renting", max_budget=2300, bedrooms=1, pets=True, move_in=None, neighborhood=None,
        ))
        consultant._extractor = AsyncMock()
        consultant._extractor.ainvoke.return_value = extraction
        class Model:
            async def astream(self, messages: list) -> AsyncIterator[AIMessageChunk]:
                context = json.loads(messages[-1].content)
                assert [item["id"] for item in context["matches"]] == ["rental-willow-flat"]
                yield AIMessageChunk(content="Willow ")
                yield AIMessageChunk(content="Terrace")
        consultant._model = Model()
        try:
            tokens = [token async for token in consultant.stream([
                Utterance(role="user", content="One bedroom under 2300, with my dog"),
            ], ConsultationSession())]
            assert tokens == ["Willow ", "Terrace"]
        finally:
            await consultant.close()
    asyncio.run(check())


def test_cancelled_stream_does_not_commit_unspoken_readback_or_revision(settings: ApiSettings) -> None:
    async def check() -> None:
        consultant = PropertyConsultant(settings, load_catalog(settings))
        consultant._extractor = AsyncMock()
        consultant._model = Mock()
        consultant._model.astream.side_effect = AssertionError("A readback invoked the model")
        consultant._extractor.ainvoke.return_value = RequirementExtraction(
            requirements=PropertyRequirements(scenario="renting", max_budget=2300, bedrooms=1),
            intent="review",
        )
        session = ConsultationSession()
        stream = consultant.stream([Utterance(role="user", content="Please recap")], session)
        try:
            assert "Requirements revision 1" in await anext(stream)
            await stream.aclose()
            assert session.version == 0 and session.pending_readback is None
            assert session.confirmed_version is None
        finally:
            await stream.aclose()
            await consultant.close()
    asyncio.run(check())


def test_concurrent_calls_keep_requirement_state_separate(settings: ApiSettings) -> None:
    async def check() -> None:
        consultant = PropertyConsultant(settings, load_catalog(settings))
        class Extractor:
            async def ainvoke(self, messages):
                data = json.loads(messages[-1].content)
                budget = int(data["transcript"][-1]["content"])
                return RequirementExtraction(requirements=PropertyRequirements(
                    scenario="renting", max_budget=budget, bedrooms=1,
                ))
        class Model:
            async def astream(self, messages):
                yield AIMessageChunk(content="A fictional example.")
        consultant._extractor = Extractor()
        consultant._model = Model()
        first, second = ConsultationSession(), ConsultationSession()
        async def consume(session, text):
            return [token async for token in consultant.stream([
                Utterance(role="user", content=text),
            ], session)]
        try:
            await asyncio.gather(consume(first, "2000"), consume(second, "3000"))
            assert first.requirements.max_budget == 2000
            assert second.requirements.max_budget == 3000
        finally:
            await consultant.close()
    asyncio.run(check())


def test_explicit_goodbye_closes_without_a_language_model_request(settings: ApiSettings) -> None:
    async def check() -> None:
        consultant = PropertyConsultant(settings, load_catalog(settings))
        consultant._extractor = AsyncMock()
        consultant._model = Mock()
        consultant._model.astream.side_effect = AssertionError("Closing invoked the model")
        consultant._extractor.ainvoke.side_effect = AssertionError("Closing invoked the model")
        session = ConsultationSession()
        try:
            response = "".join([part async for part in consultant.stream([
                Utterance(role="user", content="Please end the call"),
            ], session)])
            assert "Goodbye" in response and session.end_call is True
            consultant._extractor.ainvoke.assert_not_called()
            assert session.confirmed_version is None
        finally:
            await consultant.close()
    asyncio.run(check())
