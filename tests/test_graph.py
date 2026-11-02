import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessageChunk

from dwellcall.consultant.catalog import RentalRequirements, load_catalog
from dwellcall.consultant.graph import RentalConsultant
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.schemas import Utterance


def test_graph_streams_only_reply_and_passes_filtered_catalog(settings: ApiSettings) -> None:
    async def check() -> None:
        consultant = RentalConsultant(settings, load_catalog(settings))
        extraction = RentalRequirements(
            max_monthly_rent=2300, bedrooms=1, pets=True, move_in=None, neighborhood=None,
        )
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
            ])]
            assert tokens == ["Willow ", "Terrace"]
        finally:
            await consultant.close()
    asyncio.run(check())
