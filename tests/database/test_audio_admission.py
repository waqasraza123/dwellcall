import os
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from dwellcall.database.connection import create_database_engine
from dwellcall.database.models import AudioAdmissionGuard, Base
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings, DatabaseConnectionSettings
from dwellcall.telephony.retell.service import AudioSessionService


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    url = os.environ.get("DWELLCALL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Owner must supply a separate DWELLCALL_TEST_DATABASE_URL")
    configuration = DatabaseConnectionSettings(
        _env_file=".env", app_environment="test", test_database_url=url,
    )
    engine = create_database_engine(configuration, service_name="admission-tests")
    schema = f"dwellcall_test_{uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(isolated)
        factory = sessionmaker(bind=isolated, expire_on_commit=False)
        with factory() as session, session.begin():
            session.add(AudioAdmissionGuard(id=1))
        yield factory
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


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
