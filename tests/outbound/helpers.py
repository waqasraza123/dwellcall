from datetime import UTC, datetime
from uuid import uuid4

from dwellcall.telephony.outbound.schemas import CallInput
from dwellcall.telephony.retell.schemas import RetellCall


def call_input(**updates: object) -> CallInput:
    return CallInput.model_validate({
        "request_id": str(uuid4()), "phone_number": "+12025550124", "scenario": "renting",
        "call_purpose": "demonstration", "consent": True, "consent_version": "dwellcall-ai-call-v1",
        "recipient_consent_confirmed": True, "do_not_call_checked": True, **updates,
    })


def phone_call(call_id: str, authorization: str, **updates: object) -> RetellCall:
    return RetellCall.model_validate({
        "call_id": "call_" + call_id.replace("-", ""), "agent_id": "agent_outbound",
        "agent_version": 3, "call_type": "phone_call", "direction": "outbound",
        "from_number": "+12025550123", "to_number": "+12025550124",
        "call_status": "registered", "metadata": {"dwellcall_outbound_id": call_id, "authorization": authorization},
        **updates,
    })


def response_data(**updates: object) -> dict[str, object]:
    return {
        "id": str(uuid4()), "request_id": str(uuid4()), "status": "dialing",
        "provider_call_id": "call_synthetic",
        "transfer_status": "not_requested", "scenario": "renting", "created_at": datetime.now(UTC).isoformat(),
        "started_at": None, "finalized_at": None, "duration_seconds": None,
        "terminal": False, "mock": False, "message": "Accepted, not answered", "error_code": None,
        **updates,
    }
