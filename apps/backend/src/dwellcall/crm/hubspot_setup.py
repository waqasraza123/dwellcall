from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.crm.agent_mapping import AgentIneligible, export_snapshot
from dwellcall.crm.agent_schemas import ContactBinding, OperatorEvidence
from dwellcall.crm.agent_service import agent_audit, bind_verified_contact, destination_state
from dwellcall.crm.hubspot_mapping import FIELDS, validate_fields
from dwellcall.crm.job_execution import job_budget, provider_client
from dwellcall.crm.jobs import JOB_LOCK_NAME
from dwellcall.crm.providers.hubspot import HubSpotFailure, HubSpotProvider, properties, same_phone
from dwellcall.crm.settings import CrmSettings
from dwellcall.database.models import AgentCrmDestination, AgentCrmLink
from dwellcall.errors import ApiError
from dwellcall.listings.service import ingestion_lock


class HubSpotSetupInput(OperatorEvidence):
    custom_fields: dict[str, str] | None = Field(default=None, max_length=32)

    @field_validator("custom_fields")
    @classmethod
    def validate_mapping(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return validate_fields(value) if value is not None else None


class HubSpotPropertyCreation(HubSpotSetupInput):
    approve_external_creation: Literal[True]

    @field_validator("approve_external_creation", mode="before")
    @classmethod
    def explicit_approval(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Explicit approval is required")
        return value


def compatible_property(value: dict[str, object], key: str) -> bool:
    spec = FIELDS[key]
    metadata = value.get("modificationMetadata")
    read_only = isinstance(metadata, dict) and metadata.get("readOnlyValue")
    return value.get("type") == spec.type and value.get("fieldType") == spec.field_type and (not spec.unique or value.get("hasUniqueValue") is True) and value.get("archived") is not True and not value.get("calculated", False) and not read_only


class HubSpotConfigurationService:
    def __init__(self, sessions: sessionmaker[Session], settings: CrmSettings) -> None:
        self.sessions, self.settings = sessions, settings

    def require_api(self) -> None:
        if self.settings.crm_provider != "hubspot" or not self.settings.hubspot_api_enabled or not self.settings.crm_owner_approved:
            raise ApiError(status_code=409, code="HUBSPOT_API_DISABLED", message="Enable owner-configured HubSpot API access first")

    def status(self) -> dict[str, object]:
        settings = self.settings
        required = settings.agent_fields if settings.crm_provider == "hubspot" else self.default_fields()
        result: dict[str, object] = {
            "provider": "hubspot", "selected": settings.crm_provider == "hubspot", "api_enabled": settings.hubspot_api_enabled,
            "dispatch_enabled": settings.crm_provider == "hubspot" and settings.dispatch_enabled,
            "credentials_configured": bool(settings.hubspot_access_token and settings.hubspot_portal_id),
            "token_type": settings.hubspot_token_type, "api_version": settings.hubspot_api_version,
            "portal_id": settings.hubspot_portal_id, "configured": False, "write_scopes_verified": False,
            "schema_creation_enabled": settings.hubspot_schema_creation_enabled,
            "declared_scopes": list(settings.hubspot_declared_scopes),
            "required_scopes": self.required_scopes(),
            "required_fields": {key: {"name": name, "object_type": FIELDS[key].object_type, "label": FIELDS[key].label,
                                      "type": FIELDS[key].type, "unique": FIELDS[key].unique} for key, name in required.items()},
            "deals_enabled": settings.hubspot_deals_enabled, "pipeline_id": settings.hubspot_pipeline_id,
            "stage_id": settings.hubspot_stage_id, "sync_interval_seconds": settings.hubspot_sync_interval_seconds,
            "requests_per_second": settings.hubspot_requests_per_second, "phone_calling_codes": settings.hubspot_phone_calling_codes, "company_mappings": settings.hubspot_company_mappings,
            "last_successful_sync": None,
        }
        if settings.crm_provider == "hubspot" and settings.agent_destination_configured:
            with self.sessions() as session:
                state = session.get(AgentCrmDestination, settings.destination)
                if state:
                    result.update(configured=state.configured_at is not None, fields=state.fields,
                                  capabilities=state.capabilities, paused=state.paused, configured_at=state.configured_at,
                                  next_attempt_at=state.next_attempt_at, write_scopes_verified=state.capabilities.get("contacts.write") == "observed")
                result["last_successful_sync"] = session.scalar(select(func.max(AgentCrmLink.synced_at)).where(AgentCrmLink.destination == settings.destination))
        return result

    def default_fields(self) -> dict[str, str]:
        from dwellcall.crm.hubspot_mapping import configured_fields
        return configured_fields(self.settings.hubspot_custom_fields, deals=self.settings.hubspot_deals_enabled)

    def required_scopes(self) -> list[str]:
        objects = ["contacts", "companies"] + (["deals"] if self.settings.hubspot_deals_enabled else [])
        return ["oauth"] + [f"crm.objects.{name}.{action}" for name in objects for action in ("read", "write")] + [f"crm.schemas.{name}.read" for name in objects]

    def setup(self, request: HubSpotSetupInput, provider: HubSpotProvider | None = None) -> dict[str, object]:
        self.require_api()
        error: HubSpotFailure | None = None
        with job_budget(20), self.sessions() as session, session.begin():
            ingestion_lock(session)
            state = destination_state(session, self.settings)
            if state.next_attempt_at > datetime.now(UTC):
                raise ApiError(status_code=429, code="HUBSPOT_BACKOFF_ACTIVE", message="Respect persisted HubSpot backoff")
            adapter = provider or HubSpotProvider(self.settings, provider_client())
            fields = self.default_fields()
            if request.custom_fields is not None:
                fields.update({key: name for key, name in request.custom_fields.items() if key in fields})
            try:
                adapter.ensure_portal()
                observed: dict[str, object] = {"account.read": "observed", "write_scopes": "not_probed_no_resource_written"}
                mapping: dict[str, str] = {}
                for object_type in sorted({FIELDS[key].object_type for key in fields}):
                    adapter.request("GET", adapter.objects_path(object_type), params={"limit": 1})
                    data = adapter.request("GET", adapter.properties_path(object_type)).get("results")
                    if not isinstance(data, list):
                        raise HubSpotFailure("failed", "HUBSPOT_PROPERTY_DISCOVERY_INVALID")
                    observed[f"{object_type}.read"] = "observed"
                    observed[f"{object_type}.schema.read"] = "observed"
                    for key, name in fields.items():
                        if FIELDS[key].object_type != object_type:
                            continue
                        matches = [row for row in data if isinstance(row, dict) and row.get("name") == name and compatible_property(row, key)]
                        if len(matches) == 1:
                            mapping[key] = name
                if self.settings.hubspot_deals_enabled:
                    pipeline = adapter.request("GET", f"/crm/pipelines/{self.settings.hubspot_api_version}/deals/{self.settings.hubspot_pipeline_id}")
                    if str(pipeline.get("id")) != self.settings.hubspot_pipeline_id or not any(str(stage.get("id")) == self.settings.hubspot_stage_id for stage in pipeline.get("stages", [])):
                        raise HubSpotFailure("failed", "HUBSPOT_PIPELINE_STAGE_INVALID")
                state.fields = mapping
                state.configured_at = datetime.now(UTC) if set(mapping) == set(fields) else None
                state.capabilities = {**state.capabilities, **observed, "missing_fields": sorted(set(fields)-mapping.keys()), "portal_validated": True}
                state.paused = False
                agent_audit(session, state.destination, "HUBSPOT_CONFIGURATION_INSPECTED", reference=request.evidence_reference)
            except HubSpotFailure as failure:
                error = failure
                state.configured_at = None
                if failure.code == "HUBSPOT_RATE_LIMITED":
                    state.next_attempt_at = datetime.now(UTC) + timedelta(seconds=failure.delay)
                if failure.code in {"HUBSPOT_REJECTED_401", "HUBSPOT_REJECTED_403"}:
                    state.paused = True
                agent_audit(session, state.destination, failure.code, reference=request.evidence_reference)
            finally:
                if provider is None:
                    adapter.close()
        if error:
            raise ApiError(status_code=503, code=error.code, message="HubSpot connection inspection failed; credentials and remote payloads are not exposed")
        return self.status()

    def create_properties(self, request: HubSpotPropertyCreation, provider: HubSpotProvider | None = None) -> dict[str, object]:
        self.require_api()
        if not self.settings.hubspot_schema_creation_enabled:
            raise ApiError(status_code=403, code="HUBSPOT_SCHEMA_CREATION_DISABLED", message="Owner-controlled schema creation must be enabled")
        results: dict[str, str] = {}
        fields = self.default_fields()
        if request.custom_fields is not None:
            fields.update({key: name for key, name in request.custom_fields.items() if key in fields})
        with job_budget(20), self.sessions() as guard, guard.begin():
            if not guard.scalar(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": JOB_LOCK_NAME}):
                raise ApiError(status_code=429, code="HUBSPOT_BUSY", message="Another CRM operation is active")
            adapter = provider or HubSpotProvider(self.settings, provider_client())
            try:
                for key, name in fields.items():
                    spec = FIELDS[key]
                    operation = "schema:" + spec.object_type + ":" + name
                    try:
                        current = adapter.request("GET", adapter.properties_path(spec.object_type) + "/" + name)
                    except HubSpotFailure as failure:
                        if failure.code != "HUBSPOT_REJECTED_404":
                            raise
                        current = None
                    with self.sessions() as session, session.begin():
                        ingestion_lock(session)
                        state = destination_state(session, self.settings)
                        if state.next_attempt_at > datetime.now(UTC):
                            raise ApiError(status_code=429, code="HUBSPOT_BACKOFF_ACTIVE", message="Respect persisted provider backoff")
                        previous = state.capabilities.get(operation)
                        if current is not None:
                            results[key] = "present" if compatible_property(current, key) else "incompatible_existing_property"
                            state.capabilities = {**state.capabilities, operation: results[key]}
                            continue
                        if previous in {"unknown", "created"}:
                            results[key] = "unknown_requires_investigation"
                            continue
                        state.capabilities = {**state.capabilities, operation: "unknown"}
                        state.configured_at = None
                        agent_audit(session, state.destination, "HUBSPOT_PROPERTY_CREATION_RESERVED", reference=request.evidence_reference)
                    try:
                        adapter.request("POST", adapter.properties_path(spec.object_type), body={
                            "name": name, "label": spec.label, "groupName": {"contacts": "contactinformation", "companies": "companyinformation", "deals": "dealinformation"}[spec.object_type],
                            "type": spec.type, "fieldType": spec.field_type, "hasUniqueValue": spec.unique,
                            "description": "Owned by DwellCall. Complete relationship history is retained in Neon.",
                        }, write=True, schema_write=True, step="PROPERTY_CREATE")
                        outcome = "created"
                    except HubSpotFailure as failure:
                        outcome = "unknown" if failure.status == "unknown" else "retry_wait" if failure.status == "retry_wait" else "rejected"
                        results[key] = outcome
                        with self.sessions() as session, session.begin():
                            state = destination_state(session, self.settings)
                            state.capabilities = {**state.capabilities, operation: outcome}
                            if failure.code == "HUBSPOT_RATE_LIMITED":
                                state.next_attempt_at = datetime.now(UTC) + timedelta(seconds=failure.delay)
                            agent_audit(session, state.destination, failure.code, reference=request.evidence_reference)
                        break
                    with self.sessions() as session, session.begin():
                        state = destination_state(session, self.settings)
                        state.capabilities = {**state.capabilities, operation: outcome}
                        agent_audit(session, state.destination, "HUBSPOT_PROPERTY_CREATED", reference=request.evidence_reference)
                    results[key] = outcome
            except HubSpotFailure as failure:
                raise ApiError(status_code=503, code=failure.code, message="HubSpot property inspection is unavailable; reserved uncertain writes remain blocked") from None
            finally:
                if provider is None:
                    adapter.close()
        return {"properties": results, "requires_connection_validation": True}

    def bind(self, agent_id: UUID, request: ContactBinding, provider: HubSpotProvider | None = None) -> dict[str, object]:
        self.require_api()
        with job_budget(20), self.sessions() as session, session.begin():
            ingestion_lock(session)
            state = destination_state(session, self.settings)
            if not state.configured_at or state.next_attempt_at > datetime.now(UTC):
                raise ApiError(status_code=409, code="HUBSPOT_SETUP_OR_BACKOFF", message="Complete setup and respect provider backoff")
            try:
                snapshot = export_snapshot(session, agent_id)
            except AgentIneligible as error:
                raise ApiError(status_code=409, code=str(error), message="Only eligible verified identities may bind an existing contact") from None
            adapter = provider or HubSpotProvider(self.settings, provider_client())
            try:
                adapter.ensure_portal()
                contact = adapter.get_contact(request.contact_id, state.fields)
                values = properties(contact)
                if values.get(state.fields["agent_id"]) not in (None, "", str(agent_id)):
                    raise HubSpotFailure("failed", "HUBSPOT_IDENTITY_MARKER_CONFLICT")
                if not ((snapshot.email and str(values.get("email", "")).casefold() == snapshot.email.casefold()) or same_phone(values.get("phone"), snapshot.phone) or same_phone(values.get("mobilephone"), snapshot.phone)):
                    raise HubSpotFailure("failed", "HUBSPOT_CONTACT_EVIDENCE_MISMATCH")
            except HubSpotFailure as error:
                raise ApiError(status_code=409, code=error.code, message="The existing HubSpot contact did not satisfy verified binding requirements") from None
            finally:
                if provider is None:
                    adapter.close()
            return bind_verified_contact(session, self.settings, agent_id, request.contact_id, request.evidence_reference)
