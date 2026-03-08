# System Map

```mermaid
flowchart LR
  consumer[Framework Consumer] --> cli[agentcare CLI]
  cli --> usecase[Usecases]
  services[Service Adapters] --> usecase
  usecase --> ports[Ports]
  ports --> adapters[Adapters]
  adapters --> ext[Bolna/Mistral/Cal/FHIR/Resend/Postgres]
  dashboard[Dashboard] --> services
```

## Responsibility split

- Library (`src/agentcare`): orchestration, contracts, adapters, workflow registry.
- Services (`services/*`): HTTP transport and operational runtime.
- Scripts (`scripts/*`): local DX helpers.
