"use client";

import { useState } from "react";
import { requestApi, useResource } from "./api";
import type { HubSpotStatus } from "./contracts";
import { date, Empty, State, Status, Table, useAction } from "./ui";

export function HubSpotConnection({ status, onSaved }: { status: HubSpotStatus; onSaved: () => void }) {
  const action = useAction(onSaved);
  const [schemaResult, setSchemaResult] = useState<Record<string, string> | null>(null);
  const missing = status.capabilities?.missing_fields;
  return <>{action.feedback}<div className="detail-grid">
    <section className="ops-card"><div className="card-heading"><h2>HubSpot connection</h2><Status value={status.configured ? "configured" : "not configured"}/></div>
      <dl className="facts">
        <div><dt>Selected provider</dt><dd>{status.selected ? "HubSpot" : "Another provider or none"}</dd></div>
        <div><dt>Credentials</dt><dd>{status.credentials_configured ? "Configured on backend" : "Not configured"}</dd></div>
        <div><dt>Authentication</dt><dd>{status.token_type === "service_key" ? "Account Service Key" : "Existing private app token"}</dd></div>
        <div><dt>HubSpot account</dt><dd>{status.portal_id ?? "Not configured"}</dd></div>
        <div><dt>API version</dt><dd>{status.api_version}</dd></div>
        <div><dt>API access</dt><dd><Status value={status.api_enabled}/></dd></div>
        <div><dt>Dispatch</dt><dd><Status value={status.dispatch_enabled}/></dd></div>
        <div><dt>Last successful sync</dt><dd>{date(status.last_successful_sync)}</dd></div>
        <div><dt>Last connection validation</dt><dd>{date(status.configured_at)}</dd></div>
        <div><dt>Minimum batch interval</dt><dd>{status.sync_interval_seconds} seconds</dd></div>
        <div><dt>Request ceiling</dt><dd>{status.requests_per_second} per second</dd></div>
      </dl>
      <p className="muted">The owner configures HUBSPOT_ACCESS_TOKEN and HUBSPOT_PORTAL_ID on the backend. Tokens never enter this page. A Service Key is the default for this account-level data integration.</p>
      {status.paused && <p className="notice warning">HubSpot dispatch is paused. Inspect the failure, correct the backend configuration and validate before an audited retry.</p>}
      <details><summary>Permissions and observed access</summary><p className="muted">Declared scopes describe owner configuration. Read validation observes API access; write scopes are only marked observed after an actual authorized write.</p><Table label="HubSpot scopes" headers={["Required scope", "Owner declaration"]}>{status.required_scopes.map(scope => <tr key={scope}><td>{scope}</td><td>{status.declared_scopes.includes(scope) ? "Declared" : "Not declared"}</td></tr>)}</Table><p className="muted">Contact writes: {status.write_scopes_verified ? "Observed" : "Not probed"}. Custom property creation also requires the relevant crm.schemas.*.write scopes and account permissions.</p></details>
    </section>
    <section className="ops-card"><h2>DwellCall property mapping</h2>
      <p className="muted">Only DwellCall-owned custom properties can be mapped. Unique agent and company markers protect identity; listing history stays in Neon.</p>
      {Array.isArray(missing) && missing.length > 0 && <p className="notice warning">Missing or incompatible: {missing.filter(value => typeof value === "string").join(", ")}</p>}
      <form key={status.configured_at ?? "hubspot-initial"} onSubmit={event => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const submitter = (event.nativeEvent as SubmitEvent).submitter;
        const create = submitter instanceof HTMLButtonElement && submitter.value === "create";
        const custom_fields = Object.fromEntries(Object.entries(status.required_fields).map(([key, spec]) => [key, String(form.get(key) ?? spec.name).trim()]));
        const body = { evidence_reference: String(form.get("evidence")), custom_fields, ...(create ? { approve_external_creation: true } : {}) };
        action.confirm(create ? "Create missing HubSpot properties?" : "Validate HubSpot connection?", create ? "This creates missing DwellCall-specific properties in the configured HubSpot account, subject to schema permissions. Existing properties are inspected and never modified. Uncertain creates remain reserved for investigation." : "Inspect the configured account, read permissions, existing property types and optional deal pipeline. This action makes no remote resource changes.", async () => {
          if (create) { const result = await requestApi<{ properties: Record<string, string> }>("crm/hubspot/properties/create", "POST", body); setSchemaResult(result.properties); }
          else { await requestApi("crm/hubspot/setup", "POST", body); setSchemaResult(null); }
        }, create ? "Authorize property creation" : "Validate and save mapping");
      }}>
        <div className="mapping-fields">{Object.entries(status.required_fields).map(([key, spec]) => <label key={key}>{spec.label}<small>{spec.object_type} · {spec.type}{spec.unique ? " · unique identifier" : ""}</small><input required name={key} pattern="dwellcall_[a-z0-9_]{1,80}" maxLength={89} defaultValue={status.fields?.[key] ?? spec.name}/></label>)}</div>
        <label>Evidence reference<input required name="evidence" pattern="[A-Za-z0-9_-]{1,160}" placeholder="Opaque operator reference"/></label>
        <div className="actions"><button className="primary" type="submit" value="validate" disabled={action.busy || !status.api_enabled || !status.selected}>Validate connection & properties</button><button type="submit" value="create" disabled={action.busy || !status.api_enabled || !status.selected || !status.schema_creation_enabled}>Create missing DwellCall properties</button></div>
      </form>
      {!status.schema_creation_enabled && <p className="muted">Property creation is disabled by the backend owner gate.</p>}
      {schemaResult && <div className="notice" role="status"><p>Inspect the results, then run connection validation before synchronization.</p><ul>{Object.entries(schemaResult).map(([key, value]) => <li key={key}>{key.replaceAll("_", " ")}: {value.replaceAll("_", " ")}</li>)}</ul></div>}
    </section>
  </div><div className="detail-grid">
    <section className="ops-card"><h2>Brokerage companies</h2><p className="muted">DwellCall reuses its own unique company marker. Existing companies matched only by name require an explicit backend HUBSPOT_COMPANY_MAPPINGS entry. Existing company names and associations are preserved.</p>{Object.keys(status.company_mappings).length ? <Table label="Explicit brokerage company mappings" headers={["Brokerage", "HubSpot company ID"]}>{Object.entries(status.company_mappings).map(([name, id]) => <tr key={name}><td>{name}</td><td>{id}</td></tr>)}</Table> : <p className="muted">No explicit mappings configured. New DwellCall companies can be created during authorized synchronization when no existing name match requires review.</p>}</section>
    <section className="ops-card"><h2>Optional qualified deals</h2><dl className="facts"><div><dt>Deal creation</dt><dd><Status value={status.deals_enabled}/></dd></div><div><dt>Pipeline</dt><dd>{status.pipeline_id ?? "Not configured"}</dd></div><div><dt>Stage</dt><dd>{status.stage_id ?? "Not configured"}</dd></div></dl><p className="muted">Backend HUBSPOT_DEALS_ENABLED, HUBSPOT_PIPELINE_ID and HUBSPOT_STAGE_ID control qualified deals. Existing human-entered deal names, values and stages are preserved.</p></section>
  </div></>;
}

type FubDestination = { provider: string; sync_enabled: boolean; source: string; business_name: string };
type FubExport = { id: string; status: string; code: string | null; attempts: number; next_attempt_at: string };
export function FollowUpBossConnection({ selected }: { selected: boolean }) {
  const destination = useResource<FubDestination>(selected ? "crm/admin/destination" : null);
  const [exportId, setExportId] = useState("");
  const record = useResource<FubExport>(selected && exportId ? `crm/admin/exports/${exportId}` : null);
  return <section className="ops-card"><h1>Follow Up Boss</h1><p className="muted">The existing consented consultation export workflow remains available. GoHighLevel and HubSpot use the verified listing-agent workflow.</p>{!selected ? <p className="notice">Follow Up Boss is not the backend-selected CRM. Its credentials and activation remain owner-managed.</p> : <><State {...destination} retry={destination.refresh}>{destination.data && <dl className="facts"><div><dt>Provider</dt><dd>{destination.data.provider}</dd></div><div><dt>Dispatch</dt><dd><Status value={destination.data.sync_enabled}/></dd></div><div><dt>Source</dt><dd>{destination.data.source}</dd></div></dl>}</State><form className="filters" onSubmit={event => { event.preventDefault(); setExportId(String(new FormData(event.currentTarget).get("export"))); }}><label className="search-field">Existing export ID<input name="export" required pattern="[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}"/></label><button className="primary">Inspect export</button></form><State {...record} retry={record.refresh}>{record.data ? <dl className="facts"><div><dt>Export status</dt><dd><Status value={record.data.status}/></dd></div><div><dt>Last result</dt><dd>{record.data.code?.replaceAll("_", " ") ?? "No error recorded"}</dd></div></dl> : !exportId && <Empty>Enter an existing consultation export ID to inspect its persisted state.</Empty>}</State></>}</section>;
}
