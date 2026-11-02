import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.service import AudioSessionService


def test_two_workers_cannot_both_reserve(
    sessions: sessionmaker[Session], settings: ApiSettings,
) -> None:
    barrier = threading.Barrier(2)
    def reserve(index: int) -> str:
        barrier.wait(timeout=5)
        try:
            AudioSessionService(sessions, settings).reserve(f"call_{index}", "agent")
            return "admitted"
        except ApiError as error:
            assert error.status_code == 429
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(reserve, range(2)))
    assert sorted(outcomes) == ["admitted", "blocked"]


def test_disconnect_blocks_until_final_evidence_and_cannot_resurrect(
    sessions: sessionmaker[Session], settings: ApiSettings,
) -> None:
    service = AudioSessionService(sessions, settings)
    service.reserve("call_one", "agent")
    service.disconnect("call_one")
    with pytest.raises(ApiError):
        service.reserve("call_two", "agent")
    service.finalize("call_one", "agent")
    service.finalize("call_one", "agent")
    service.disconnect("call_one")
    with pytest.raises(ApiError):
        service.reserve("call_one", "agent")
    service.reserve("call_two", "agent")


def test_spending_reservations_are_not_refunded_on_end(
    sessions: sessionmaker[Session], settings: ApiSettings,
) -> None:
    configuration = settings.model_copy(update={"conversation_daily_budget_cents": 100})
    service = AudioSessionService(sessions, configuration)
    service.reserve("call_one", "agent")
    service.finalize("call_one", "agent")
    with pytest.raises(ApiError):
        service.reserve("call_two", "agent")


def test_end_before_socket_admission_is_a_permanent_tombstone(
    sessions: sessionmaker[Session], settings: ApiSettings,
) -> None:
    service = AudioSessionService(sessions, settings)
    service.finalize("call_late_socket", "agent")
    with pytest.raises(ApiError):
        service.reserve("call_late_socket", "agent")
