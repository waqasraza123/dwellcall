import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.database.models.workspace import OperatorAction
from dwellcall.errors import ApiError


def reserve_operator_action(sessions: sessionmaker[Session], key: str, path: str, body: bytes) -> None:
    try:
        parsed = UUID(key)
        if parsed.version != 4:
            raise ValueError
    except ValueError:
        raise ApiError(status_code=422, code="ACTION_KEY_REQUIRED", message="Start a deliberate operator action with a new request ID") from None
    digest = hashlib.sha256(path.encode() + b"\0" + body).hexdigest()
    try:
        with sessions() as session, session.begin():
            session.add(OperatorAction(key=str(parsed), fingerprint=digest, created_at=datetime.now(UTC)))
            session.flush()
    except IntegrityError:
        raise ApiError(status_code=409, code="ACTION_ALREADY_SUBMITTED", message="This action was already submitted. Refresh its history before starting another action") from None
