# Data Flow

```mermaid
sequenceDiagram
  participant W as Webhook/Sync
  participant U as frontdesk usecase
  participant C as customer store
  participant A as appointment connector
  participant N as notifier
  participant S as analytics store

  W->>U: execution payload
  U->>U: extract + rag backfill + policy + doctor assign
  U->>C: upsert customer
  U->>A: check/book appointment
  U->>N: send confirmation email
  U->>S: persist lifecycle + event
  U-->>W: processing result
```

## Output contract highlights

- `patient_facing_summary`: concise confirmation-safe summary.
- `internal_ops_summary`: operational context for dashboard and triage.
- `rag_backfill`: metadata showing whether memory fallback was used.
