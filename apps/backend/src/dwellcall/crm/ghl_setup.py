from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.crm.agent_mapping import AgentIneligible, export_snapshot
from dwellcall.crm.agent_schemas import ContactBinding, GhlSetupInput, LocationProvisionInput
from dwellcall.crm.agent_service import agent_audit, bind_verified_contact, destination_state
from dwellcall.crm.job_execution import job_budget, provider_client
from dwellcall.crm.jobs import JOB_LOCK_NAME
from dwellcall.crm.providers.gohighlevel import FIELD_DEFINITIONS, GhlFailure, GoHighLevelProvider, field_values, remote_id
from dwellcall.crm.settings import CrmSettings
from dwellcall.database.models import AgentCrmDestination
from dwellcall.errors import ApiError
from dwellcall.listings.service import ingestion_lock


class GhlConfigurationService:
    def __init__(self, sessions: sessionmaker[Session], settings: CrmSettings) -> None:
        self.sessions, self.settings = sessions, settings

    def status(self) -> dict[str, object]:
        settings = self.settings
        result: dict[str, object] = {
            "provider": "gohighlevel", "selected": settings.crm_provider == "gohighlevel",
            "api_enabled": settings.ghl_api_enabled, "dispatch_enabled": settings.dispatch_enabled,
            "credentials_configured": bool(settings.ghl_private_integration_token and settings.ghl_location_id),
            "configured": False, "required_fields": FIELD_DEFINITIONS,
            "declared_scopes": settings.ghl_declared_scopes,
            "write_scopes_verified": False, "provisioning_enabled": settings.ghl_provisioning_enabled,
            "location_id": settings.ghl_location_id, "opportunities_enabled": settings.ghl_opportunities_enabled,
            "pipeline_id": settings.ghl_pipeline_id, "pipeline_stage_id": settings.ghl_pipeline_stage_id,
            "optional_provider": settings.crm_provider,

        }
        if settings.crm_provider == "gohighlevel" and settings.ghl_location_id and settings.crm_hash_secret:
            with self.sessions() as session:
                state = session.get(AgentCrmDestination, settings.destination)
                if state:
                    result.update(configured=state.configured_at is not None, fields=state.fields,
                                  capabilities=state.capabilities, write_scopes_verified=state.capabilities.get("contacts.write") == "observed", paused=state.paused,
                                  next_attempt_at=state.next_attempt_at, configured_at=state.configured_at)
        return result

    def setup(self, request: GhlSetupInput, provider: GoHighLevelProvider | None = None) -> dict[str, object]:
        if self.settings.crm_provider != "gohighlevel" or not self.settings.ghl_api_enabled:
            raise ApiError(status_code=409, code="GHL_API_DISABLED", message="Enable configured GHL API access before inspecting the connection")
        error: GhlFailure | None = None
        with job_budget(20), self.sessions() as session, session.begin():
            ingestion_lock(session)
            state = destination_state(session, self.settings)
            if state.next_attempt_at > datetime.now(UTC):
                raise ApiError(status_code=429, code="GHL_BACKOFF_ACTIVE", message="Respect persisted GHL backoff")
            adapter = provider or GoHighLevelProvider(self.settings, provider_client())
            try:
                location = adapter.request("GET", "/locations/" + str(self.settings.ghl_location_id)).get("location", {})
                if location.get("id") != self.settings.ghl_location_id:
                    raise GhlFailure("failed", "GHL_LOCATION_INVALID")
                adapter.request("POST", "/contacts/search", body={"locationId": self.settings.ghl_location_id, "page": 1, "pageLimit": 1})
                fields = adapter.request("GET", "/locations/" + str(self.settings.ghl_location_id) + "/customFields", params={"model": "contact"}).get("customFields", [])
                if not isinstance(fields, list):
                    raise GhlFailure("failed", "GHL_FIELD_DISCOVERY_INVALID")
                mapping: dict[str, str] = {}
                for key, (name, kind) in FIELD_DEFINITIONS.items():
                    configured = (request.custom_fields if request.custom_fields is not None else self.settings.ghl_custom_fields).get(key)
                    matches = [field for field in fields if isinstance(field, dict) and (
                        field.get("id") == configured if configured else field.get("name") == name
                    ) and field.get("model", "contact") == "contact" and field.get("dataType") == kind]
                    if len(matches) == 1:
                        mapping[key] = remote_id(matches[0].get("id"))
                if len(set(mapping.values())) != len(mapping):
                    raise GhlFailure("failed", "GHL_FIELD_MAPPING_CONFLICT")
                if self.settings.ghl_opportunities_enabled:
                    pipelines = adapter.request("GET", "/opportunities/pipelines", params={"locationId": self.settings.ghl_location_id}).get("pipelines", [])
                    if not any(item.get("id") == self.settings.ghl_pipeline_id and any(stage.get("id") == self.settings.ghl_pipeline_stage_id for stage in item.get("stages", [])) for item in pipelines):
                        raise GhlFailure("failed", "GHL_PIPELINE_STAGE_INVALID")
                state.fields = mapping
                state.configured_at = datetime.now(UTC) if len(mapping) == len(FIELD_DEFINITIONS) else None
                state.capabilities = {
                    "locations.readonly": "observed", "contacts.readonly": "observed",
                    "locations/customFields.readonly": "observed",
                    "opportunities.readonly": "observed" if self.settings.ghl_opportunities_enabled else "not_probed",
                    "write_scopes": "not_probed_no_resource_written",
                    "duplicate_contacts_allowed": location.get("settings", {}).get("allowDuplicateContact"),
                    "missing_fields": sorted(set(FIELD_DEFINITIONS) - mapping.keys()),
                }
                state.paused = False
                agent_audit(session, state.destination, "GHL_CONFIGURATION_INSPECTED", reference=request.evidence_reference)
            except GhlFailure as failure:
                error = failure
                if failure.code == "GHL_RATE_LIMITED":
                    state.next_attempt_at = datetime.now(UTC) + timedelta(seconds=failure.delay)
                if failure.code in {"GHL_REJECTED_401", "GHL_REJECTED_403"}:
                    state.paused = True
                state.configured_at = None
                agent_audit(session, state.destination, failure.code, reference=request.evidence_reference)
            finally:
                if provider is None:
                    adapter.close()
        if error:
            raise ApiError(status_code=503, code=error.code, message="GHL configuration inspection failed; no response payload or credential is exposed")
        return self.status()

    def bind(self, agent_id: UUID, request: ContactBinding, provider: GoHighLevelProvider | None = None) -> dict[str, object]:
        if self.settings.crm_provider != "gohighlevel" or not self.settings.ghl_api_enabled:
            raise ApiError(status_code=409, code="GHL_API_DISABLED", message="Enable GHL API inspection first")
        with job_budget(20), self.sessions() as session, session.begin():
            ingestion_lock(session)
            state = destination_state(session, self.settings)
            if not state.configured_at or state.next_attempt_at > datetime.now(UTC):
                raise ApiError(status_code=409, code="GHL_SETUP_OR_BACKOFF", message="Complete setup and respect provider backoff")
            try:
                snapshot = export_snapshot(session, agent_id)
            except AgentIneligible as error:
                raise ApiError(status_code=409, code=str(error), message="Only eligible identities can bind an existing contact") from None
            adapter = provider or GoHighLevelProvider(self.settings, provider_client())
            try:
                contact = adapter.get_contact(request.contact_id)
            except GhlFailure as error:
                raise ApiError(status_code=409, code=error.code, message="The GHL contact could not be inspected") from None
            finally:
                if provider is None:
                    adapter.close()
            marker = field_values(contact).get(state.fields["agent_id"])
            if marker not in (None, "", str(agent_id)):
                raise ApiError(status_code=409, code="GHL_IDENTITY_MARKER_CONFLICT", message="Contact belongs to another DwellCall identity")
            if not ((snapshot.email and str(contact.get("email", "")).casefold() == snapshot.email.casefold())
                    or (snapshot.phone and contact.get("phone") == snapshot.phone)):
                raise ApiError(status_code=409, code="GHL_CONTACT_EVIDENCE_MISMATCH", message="A verified direct email or phone must match the selected contact")
            return bind_verified_contact(session, self.settings, agent_id, request.contact_id, request.evidence_reference)

    def provision(self, request: LocationProvisionInput, provider: GoHighLevelProvider | None = None) -> dict[str, object]:
        settings = self.settings
        if not (settings.crm_provider == "gohighlevel" and settings.ghl_api_enabled and settings.ghl_provisioning_enabled
                and settings.ghl_agency_token and settings.ghl_company_id and settings.crm_owner_approved
                and "locations.write" in settings.ghl_declared_scopes):
            raise ApiError(status_code=403, code="GHL_PROVISIONING_NOT_APPROVED", message="Provisioning requires a scoped agency token, company, owner approval and explicit eligible-plan evidence")
        digest = settings.fingerprint("provision", request.model_dump_json(exclude={"evidence_reference", "plan_evidence_reference"}))
        scope = settings.fingerprint("agency", str(settings.ghl_company_id))
        with job_budget(20), self.sessions() as guard, guard.begin():
            if not guard.scalar(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": JOB_LOCK_NAME}):
                raise ApiError(status_code=429, code="GHL_BUSY", message="Another bounded CRM operation is running")
            with self.sessions() as session, session.begin():
                ingestion_lock(session)
                state = session.get(AgentCrmDestination, scope, with_for_update=True)
                if state is None:
                    state = AgentCrmDestination(destination=scope, fields={}, capabilities={}, paused=False, next_attempt_at=datetime.now(UTC))
                    session.add(state)
                previous = state.capabilities.get(digest)
                if previous:
                    return {"operation": previous, "replayed": True}
                state.capabilities = {**state.capabilities, digest: {"status": "unknown", "code": "GHL_PROVISION_RESERVED"}}
                agent_audit(session, scope, "GHL_PROVISION_RESERVED", reference=request.evidence_reference)
                agent_audit(session, scope, "GHL_PROVISION_PLAN_ATTESTED", reference=request.plan_evidence_reference)
            adapter = provider or GoHighLevelProvider(settings, provider_client())
            try:
                data = adapter.request("POST", "/locations/", body={
                    "companyId": settings.ghl_company_id, "name": request.name,
                    "address": request.address, "city": request.city, "state": request.state,
                    "country": request.country, "postalCode": request.postal_code, "timezone": request.timezone,
                    "settings": {"allowDuplicateContact": False, "allowDuplicateOpportunity": False, "allowFacebookNameMerge": False},
                }, write=True, agency=True)
                operation = {"status": "sent", "location_id": remote_id(data.get("id")), "code": "GHL_LOCATION_CREATED"}
            except GhlFailure as error:
                operation = {"status": error.status, "code": error.code}
            finally:
                if provider is None:
                    adapter.close()
            with self.sessions() as session, session.begin():
                ingestion_lock(session)
                state = session.get(AgentCrmDestination, scope, with_for_update=True)
                if state is None:
                    raise RuntimeError("Provisioning reservation is unavailable")
                state.capabilities = {**state.capabilities, digest: operation}
                agent_audit(session, scope, operation["code"], reference=request.evidence_reference)
            return {"operation": operation, "replayed": False}
