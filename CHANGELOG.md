# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and this project follows Semantic Versioning.

## [0.1.0] - 2026-03-07

### Added
- Multi-workflow registry (`frontdesk_booking`, `care_navigation`, `followup_outreach`).
- Cal and FHIR connector paths under unified appointment connector abstraction.
- RAG-backed missing field recovery in frontdesk usecase.
- Doctor routing in core orchestration flow.
- Professionalized confirmation emails and richer calendar booking metadata.
- Dedicated summary columns in `call_executions`:
  - `patient_facing_summary`
  - `internal_ops_summary`
- Analytics endpoint for call detail:
  - `GET /analytics/calls/{execution_id}`

### Changed
- Dashboard UX and call-detail inspection panel.
- Packaging metadata and CLI entrypoint structure.
