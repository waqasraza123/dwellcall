# DwellCall

**Requested outbound calls. Natural conversations. Clear results.**

DwellCall is a focused real-estate voice-agent showcase for prospective clients.
An approved operator requests one consented callback, the AI asks about property
needs and timing, and the workspace retains a transcript and evidence-based
qualification summary when analysis is enabled.

The core experience is a phone-demo homepage and `/calls`: request, progress,
transcript, summary, recipient suppression and call history. ElevenLabs with Telnyx
is the default voice path; Retell remains optional. OpenAI provides structured
post-call analysis. Existing Neon persistence, account MFA, admission limits,
idempotency and uncertain-call recovery support the workflow.

**Source implemented; runtime unverified.** Live calling and transcript analysis
remain disabled until owner configuration and acceptance. The demo uses fictional
property scenarios. There is no connected listing inventory or appointment booking.
Human transfers are permanently disabled. No autonomous dialing or follow-up occurs.
An active ElevenLabs SIP call currently requires carrier-side termination in Telnyx;
the workspace exposes that limitation and retains unresolved reservations.

Listing discovery, agent intelligence, CRM management, subscriptions, browser chat
and follow-up task management are parked extensions. Their source and migrations
remain available; their routes/UI are disabled by default. No stored data or
migration history is removed.

- [Focused roadmap](docs/roadmap.md)
- [Core setup and owner acceptance](docs/outbound-agent.md)
- [Authentication and Neon setup](docs/authentication.md)
- [Provider and transcript reference](docs/call-intelligence.md)

The next milestone is an accepted, repeatable phone demonstration and a short
portfolio case study. Add integrations and capacity only for demonstrated client needs.
