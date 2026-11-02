import json

import httpx

from dwellcall.crm.contracts import CrmExportRequest, DeliveryResult
from dwellcall.crm.settings import CrmSettings

EVENTS_URL = "https://api.followupboss.com/v1/events"
FICTIONAL_LABEL = "FICTIONAL DEMONSTRATION — no real listing or availability."


def inquiry_payload(request: CrmExportRequest, settings: CrmSettings) -> dict[str, object]:
    snapshot = request.snapshot
    person: dict[str, object] = {}
    if snapshot.contact.first_name:
        person["firstName"] = snapshot.contact.first_name
    if snapshot.contact.last_name:
        person["lastName"] = snapshot.contact.last_name
    if snapshot.contact.email:
        person["emails"] = [{"value": str(snapshot.contact.email)}]
    if snapshot.contact.phone:
        person["phones"] = [{"value": snapshot.contact.phone}]
    details: dict[str, object] = {
        "export_reference": str(request.export_id),
        "scenario": snapshot.scenario,
        "requirements": list(snapshot.requirements),
    }
    if snapshot.budget is not None:
        details["budget"] = snapshot.budget.model_dump(mode="json")
    if snapshot.location is not None:
        details["location"] = snapshot.location
    return {
        "type": "General Inquiry",
        "source": settings.followupboss_lead_source,
        "system": settings.followupboss_system_name,
        "person": person,
        "message": f"{FICTIONAL_LABEL}\n{snapshot.summary}",
        "description": f"{FICTIONAL_LABEL}\n{json.dumps(details, sort_keys=True)}",
    }


class FollowUpBossProvider:
    def __init__(self, settings: CrmSettings, client: httpx.Client) -> None:
        self.settings = settings
        self.client = client

    def close(self) -> None:
        self.client.close()

    def send(self, request: CrmExportRequest) -> DeliveryResult:
        if not self.settings.dispatch_enabled:
            return DeliveryResult("disabled", "CRM_DISABLED")
        if request.destination != self.settings.destination:
            return DeliveryResult("failed", "CRM_DESTINATION_CHANGED")
        key = self.settings.followupboss_api_key
        system_key = self.settings.followupboss_system_key
        system_name = self.settings.followupboss_system_name
        if key is None or system_key is None or system_name is None:
            return DeliveryResult("failed", "CRM_CONFIGURATION_INVALID")
        try:
            with self.client.stream(
                "POST", EVENTS_URL,
                auth=httpx.BasicAuth(key.get_secret_value(), ""),
                headers={
                    "X-System": system_name,
                    "X-System-Key": system_key.get_secret_value(),
                    "Accept": "application/json",
                },
                json=inquiry_payload(request, self.settings),
                timeout=10, follow_redirects=False,
            ) as response:
                if response.status_code == 429:
                    value = response.headers.get("Retry-After", "")
                    delay = int(value) if value.isascii() and value.isdigit() and len(value) <= 8 else 60
                    return DeliveryResult("retry_wait", "CRM_RATE_LIMITED", retry_after_seconds=max(1, delay))
                if response.status_code == 204:
                    return DeliveryResult("ignored", "CRM_SOURCE_ARCHIVED")
                if response.status_code in {400, 401, 403, 404, 422}:
                    return DeliveryResult("failed", f"CRM_REJECTED_{response.status_code}")
                if response.status_code not in {200, 201}:
                    return DeliveryResult("unknown", "CRM_RESPONSE_UNCERTAIN")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 65536:
                        return DeliveryResult("unknown", "CRM_RECEIPT_INVALID")
                result = json.loads(body)
                person_id = result.get("id") if isinstance(result, dict) else None
                if type(person_id) is not int or not 0 < person_id <= 2_147_483_647:
                    return DeliveryResult("unknown", "CRM_RECEIPT_INVALID")
                return DeliveryResult("sent", "CRM_DELIVERED", person_id=person_id)
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout):
            return DeliveryResult("retry_wait", "CRM_NOT_SUBMITTED", retry_after_seconds=60)
        except (httpx.HTTPError, ValueError, UnicodeError, RecursionError):
            return DeliveryResult("unknown", "CRM_OUTCOME_UNCERTAIN")
