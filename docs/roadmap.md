# DwellCall roadmap — focused outbound agent

This roadmap supersedes the broader listing-intelligence and SaaS roadmap.
The product is a small, end-to-end real-estate callback showcase for Upwork clients.
Its success criterion is a repeatable useful phone conversation with an accurate
transcript and qualification result that an owner can demonstrate and explain.
Feature count, subscription plans and listing coverage are not acceptance criteria.

## Product boundary

The active flow is:

1. An approved operator deliberately requests one consented call.
2. The AI identifies itself, explains transcript processing when enabled and asks
   permission before discussing renting, buying or luxury-property needs.
3. It gathers useful stated requirements and timing, handles interruptions and
   corrections, asks about further-contact permission and ends promptly.
4. The workspace shows provider-backed status/history and, when enabled, the
   encrypted transcript and OpenAI summary with recipient evidence and unknowns.

The homepage offers the existing SMS-verified fictional phone demonstration.
It does not present made-up listings as live data or qualify demos as real leads.
ElevenLabs/Telnyx is primary; Retell is an optional provider adapter. Existing MFA,
Neon, shared admission, cost reservations, suppression and recovery remain core.
US-only destinations, one shared audio slot, current quotas, no automatic redial
and permanent AI-only operation remain unchanged.

## Milestone 1 — finish the focused source

Source delivered, **UNVERIFIED**:

- Homepage and metadata explain the voice agent and one requested call workflow.
- `/calls` holds the call form, progress, results and history; operational controls
  are grouped under recovery. `/dashboard` is a compatibility redirect to `/calls`.
- Qualification asks about the recipient's property needs, not a DwellCall
  subscription purchase. Follow-up suggestions require recipient evidence and
  explicit permission. Missing information stays unknown.
- The default API/bridge does not expose the parked platform modules. These have
  an explicit extensions opt-in and retain their own activation/authentication gates.
- No dependency installation, verification, migrations, provider configuration,
  live calls or deployment executed. No new migration is needed for this trim.

Owner check commands: [core acceptance](outbound-agent.md).

## Milestone 2 — accept one complete live workflow

**Next priority. Not yet accepted.** Do this before expanding scope:

- Configure the existing account/MFA/database, dedicated voice agent, authorized
  caller/recipient and signed final webhook. Publish the current exact agent prompt.
- Exercise simulation first, then separately authorize one paid call with a
  consenting recipient. Check first disclosure, interruptions, corrections,
  silence, voicemail, wrong number, hangup/DNC and the duration ceiling.
- Verify final webhook identity, transcript capture, encryption, analysis quotes,
  explicit permission and unknown fields. Check empty transcripts and API failures.
- Replay the request and final events: no duplicate dial or successful analysis.
  Refresh mid-request and recover unknown outcomes without redialing.
- Check provider/carrier duration and spending controls, actual costs and final
  carrier completion. Confirm no recording or unapproved follow-up occurs.
- Resolve any defects the owner reports. A configured UI is not evidence of a
  successful phone call, transcript or useful conversation.

Known operator limitation: ElevenLabs stop currently marks the local request and
requires ending the SIP call in Telnyx. Emergency pause blocks new calling; it
cannot remotely silence an existing ElevenLabs conversation. Native stop/hangup
and the configured provider duration limit require actual acceptance. Do not claim
an application-controlled carrier hangup until it is implemented and accepted.

## Milestone 3 — package the portfolio demonstration

After acceptance, record a short, explicitly consented walkthrough using fictional
personal details: call request, conversation, final transcript and summary. Show
one correction/interruption and the resulting useful qualification fields. Explain
provider boundaries, errors and any simulated actions honestly. Publish a concise
case study describing the problem, delivered behavior, architecture and actual
owner-observed results. Audio/video production and publication need separate work;
no recordings or performance claims have been fabricated.

## Milestone 4 — add one client-requested integration

Choose one concrete workflow only after a prospective/paying client identifies it:
for example, approved call summaries delivered to their CRM or an actually available
calendar slot booked after explicit permission. Reuse existing adapters when they
fit. Add durable action reservations, deduplication and recovery for that integration.
The acceptance example must show the external result. Do not expand into a general
CRM, listing discovery system or appointment SaaS to demonstrate one integration.

## Milestone 5 — increase capacity from measured demand

Retain the current single-slot budget and admission constraints until measured
usage justifies a change. Then:

- Move post-call analysis to a durable bounded job queue if webhook timing or
  concurrent traffic requires it; add retry/recovery evidence and acceptance first.
- Add account/client isolation, per-client provider settings, quotas and spending
  before serving independent customers. The current shared workspace is not SaaS
  tenancy, even though signup and subscription code exist.
- Increase concurrency only after provider/carrier limits, shared admission,
  unresolved-call handling and costs have been tested at that proposed capacity.
- Add operational metrics and alerts driven by real failure modes, and record
  measured latency/cost/reliability in the case study.

No background worker, scheduler, capacity increase or tenant system is introduced
by this roadmap change.

## Parked scope

Listing sources/MLS/portal/RentCast connectors, scraping, market discovery, agent
identity repair, enrichment, bulk campaigns, follow-up task management, browser
chat, multi-CRM administration, Stripe plans/paywalls and team management have no
active delivery milestone. Existing source is retained behind extensions where
applicable. Revisit a specific module only when it serves a demonstrated client
requirement and its data permissions and operating costs are established.
