# Services API Map

## Analytics (`services/analytics`)

- `GET /healthz`
- `GET /analytics/overview`
- `GET /analytics/calls/timeseries`
- `GET /analytics/funnel`
- `GET /analytics/customers/cohorts`
- `GET /analytics/calls/{execution_id}`

## Dashboard (`services/dashboard`)

- `GET /`
- `GET /healthz`
- `GET /api/workflow/status`
- `GET /api/executions/recent`
- `GET /api/appointments/summary`
- `GET /api/cases/queue`
- `POST /api/call`

## Webhooks (`services/webhooks`)

- `GET /healthz`
- `POST /bolna/execution`
