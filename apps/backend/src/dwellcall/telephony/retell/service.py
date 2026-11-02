from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.database.models import AudioAdmissionGuard, AudioSession
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings


class AudioSessionService:
    def __init__(self, sessions: sessionmaker[Session], settings: ApiSettings) -> None:
        self.sessions = sessions
        self.settings = settings

    @staticmethod
    def _lock(session: Session) -> None:
        session.execute(
            select(AudioAdmissionGuard.id)
            .where(AudioAdmissionGuard.id == 1)
            .with_for_update()
        ).scalar_one()

    def reserve(self, call_id: str, agent_id: str) -> None:
        now = datetime.now(UTC)
        today = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
        with self.sessions() as session, session.begin():
            self._lock(session)
            existing = session.get(AudioSession, call_id)
            active = session.scalar(
                select(AudioSession).where(AudioSession.status != "ended").limit(1)
            )
            base = select(AudioSession).where(
                AudioSession.created_at >= today,
                AudioSession.reserved_cost_cents > 0,
            ).subquery()
            daily = session.scalar(select(func.count()).select_from(base)) or 0
            reserved = session.scalar(select(func.sum(base.c.reserved_cost_cents))) or 0
            if (
                existing is not None
                or active is not None
                or daily >= self.settings.conversation_daily_session_limit
                or reserved + self.settings.conversation_reserved_cost_cents
                > self.settings.conversation_daily_budget_cents
            ):
                raise ApiError(
                    status_code=429, code="AUDIO_SESSION_LIMIT",
                    message="A call is active, unresolved, already used, or the daily limit was reached",
                )
            session.add(AudioSession(
                call_id=call_id, agent_id=agent_id, status="active", created_at=now,
                reserved_cost_cents=self.settings.conversation_reserved_cost_cents,
            ))

    def disconnect(self, call_id: str) -> None:
        with self.sessions() as session, session.begin():
            row = session.get(AudioSession, call_id, with_for_update=True)
            if row is not None and row.status == "active":
                row.status = "unknown"

    def finalize(self, call_id: str, agent_id: str) -> None:
        now = datetime.now(UTC)
        with self.sessions() as session, session.begin():
            self._lock(session)
            row = session.get(AudioSession, call_id, with_for_update=True)
            if row is None:
                session.add(AudioSession(
                    call_id=call_id, agent_id=agent_id, status="ended", created_at=now,
                    reserved_cost_cents=0, finalized_at=now,
                ))
            elif row.agent_id == agent_id and row.status != "ended":
                row.status = "ended"
                row.finalized_at = now

    def is_active(self, call_id: str) -> bool:
        with self.sessions() as session:
            row = session.get(AudioSession, call_id)
            return row is not None and row.status == "active"
