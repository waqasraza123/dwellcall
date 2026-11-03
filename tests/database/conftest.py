import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from dwellcall.database.connection import create_database_engine
from dwellcall.database.models import AudioAdmissionGuard, Base, CrmDispatchState, ListingSource
from dwellcall.listings.registry import SYNTHETIC_PERMISSION, SYNTHETIC_SOURCE_KEY
from dwellcall.settings import DatabaseConnectionSettings


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
            session.add(CrmDispatchState(id=1, next_attempt_at=datetime(1970, 1, 1, tzinfo=UTC)))
            session.add(ListingSource(key=SYNTHETIC_SOURCE_KEY, permission=dict(SYNTHETIC_PERMISSION), permission_version=1, created_at=datetime.now(UTC)))
        yield factory
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


