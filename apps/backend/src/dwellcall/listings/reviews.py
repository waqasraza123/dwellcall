from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.database.models import ListingAgent, ListingAgentObservation, ListingEntity, ListingObservation, ListingReview, ListingSource
from dwellcall.errors import ApiError
from dwellcall.listings.permissions import permission, retained
from dwellcall.listings.schemas import ReviewResolutionInput
from dwellcall.listings.service import audit, current_listing_data, ingestion_lock


def review_data(row: ListingReview) -> dict[str, object]:
    return {
        "id": str(row.id), "source_key": row.source_key,
        "source_listing_id": row.source_listing_id, "reason": row.reason,
        "candidate_ids": row.candidate_ids, "evidence": row.snapshot,
        "created_at": row.created_at, "status": row.status,
        "resolution": row.resolution, "resolved_at": row.resolved_at,
        "applied_at": row.applied_at,
        "requires_reimport": row.status == "approved" and row.applied_at is None,
    }


class ListingReviewService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def _visible(session: Session, review_id: UUID, *, lock: bool = False) -> tuple[ListingReview, ListingSource]:
        row = session.get(ListingReview, review_id, with_for_update=lock)
        source = session.get(ListingSource, row.source_key) if row else None
        if row is None or source is None or not retained(source, row.created_at, display=True):
            raise ApiError(status_code=404, code="REVIEW_NOT_FOUND", message="Review is unavailable or outside current source rights/retention")
        return row, source

    def inspect(self, review_id: UUID) -> dict[str, object]:
        with self.sessions() as session:
            row, _ = self._visible(session, review_id)
            candidates: list[dict[str, object]] = []
            for value in row.candidate_ids:
                if row.snapshot.get("subject_type") == "agent":
                    agent = session.get(ListingAgent, UUID(value))
                    records = session.execute(select(ListingAgentObservation, ListingSource).join(
                        ListingObservation, ListingObservation.id == ListingAgentObservation.observation_id,
                    ).join(ListingSource, ListingSource.key == ListingObservation.source_key).where(
                        ListingAgentObservation.agent_id == UUID(value),
                    ).order_by(ListingAgentObservation.collected_at.desc())).all()
                    visible = [record for record, source in records if retained(source, record.collected_at, display=True)]
                    candidates.append({"id": value, "agent": visible[0].snapshot if visible else None,
                                       "suppressed": agent.suppressed_at is not None if agent else None})
                else:
                    data, provenance = current_listing_data(session, UUID(value))
                    candidates.append({"id": value, "property": data, "provenance": provenance})
            return {**review_data(row), "candidates": candidates}

    def resolve(self, review_id: UUID, request: ReviewResolutionInput) -> dict[str, object]:
        with self.sessions() as session, session.begin():
            ingestion_lock(session)
            row, source = self._visible(session, review_id, lock=True)
            resolution = request.model_dump(mode="json")
            if row.status != "pending":
                if row.resolution != resolution:
                    raise ApiError(status_code=409, code="REVIEW_ALREADY_RESOLVED", message="The review already has a different immutable decision")
                return review_data(row)
            if request.decision == "approve":
                if str(request.candidate_id) not in row.candidate_ids or not row.snapshot.get("evidence_key"):
                    raise ApiError(status_code=422, code="REVIEW_CANDIDATE_INVALID", message="Select a proposed candidate with retained identity evidence")
                model = ListingAgent if row.snapshot.get("subject_type") == "agent" else ListingEntity
                candidate = session.get(model, request.candidate_id, with_for_update=True)
                if candidate is None or candidate.data_mode != permission(source).data_mode:
                    raise ApiError(status_code=409, code="REVIEW_CANDIDATE_UNAVAILABLE", message="The proposed candidate is unavailable")
                if model is ListingAgent:
                    agents = session.scalars(select(ListingAgent).where(ListingAgent.id.in_([UUID(value) for value in row.candidate_ids]))).all()
                    if any(agent.suppressed_at is not None for agent in agents):
                        raise ApiError(status_code=409, code="AGENT_SUPPRESSED", message="Review approval cannot override suppression")
            row.status = "approved" if request.decision == "approve" else "rejected"
            row.resolution, row.resolved_at = resolution, datetime.now(UTC)
            session.flush()
            for candidate_id in row.candidate_ids if row.snapshot.get("subject_type") == "agent" else []:
                agent = session.get(ListingAgent, UUID(candidate_id))
                if agent is not None:
                    unresolved = session.scalar(select(ListingReview.id).where(
                        ListingReview.candidate_ids.contains([candidate_id]),
                        ListingReview.status != "approved",
                    ).limit(1))
                    agent.review_required = unresolved is not None or request.decision != "approve"
            audit(session, source, "LISTING_REVIEW_RESOLVED", {
                "review_id": str(row.id), "actor": "authenticated_admin",
                "evidence_fingerprint": row.fingerprint, **resolution,
            })
            return review_data(row)
