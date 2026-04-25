from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Bolna (BOLNA_API_KEY or bolna_API)
    bolna_api_key: str | None = Field(default=None, validation_alias=AliasChoices("BOLNA_API_KEY", "bolna_API"))
    bolna_base_url: str = "https://api.bolna.ai"
    bolna_agent_id: str | None = Field(
        default=None, validation_alias=AliasChoices("BOLNA_AGENT_ID", "bolna_agent_id")
    )
    bolna_from_phone_number: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "BOLNA_FROM_PHONE_NUMBER",
            "BOLNA_FROM_NUMBER",
            "bolna_from_phone_number",
            "bolna_from_number",
        ),
    )

    # Mistral (MISTRAL_API_KEY or mistrail_API)
    mistral_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("MISTRAL_API_KEY", "mistrail_API")
    )
    mistral_model: str = "mistral-small-latest"

    agentcare_llm_gateway_url: str = "http://localhost:8010/v1"
    agentcare_mock_ehr_url: str = "http://localhost:8020"

    # Cal.com (CAL_API_KEY or cal_API)
    cal_api_key: str | None = Field(default=None, validation_alias=AliasChoices("CAL_API_KEY", "cal_API"))
    cal_event_type_id: str | None = Field(
        default=None, validation_alias=AliasChoices("CAL_EVENT_TYPE_ID", "cal_event_type_id")
    )
    cal_timezone: str = "Asia/Kolkata"
    appointment_connector_backend: str = "cal"  # cal | mock | fhir
    fhir_base_url: str | None = None
    fhir_auth_token: str | None = None
    fhir_schedule_id: str | None = None
    fhir_organization_id: str | None = None
    fhir_timeout_sec: float = 10.0
    fhir_slot_search_count: int = 20
    frontdesk_policy_path: str | None = None

    # Resend (RESEND_API_KEY or resent_API)
    resend_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("RESEND_API_KEY", "resent_API")
    )
    agentcare_email_from: str = "AgentCare <onboarding@resend.dev>"
    customer_store_backend: str = "auto"  # auto | json | postgres
    customer_store_path: str = "artifacts/customers.json"
    processed_executions_path: str = "artifacts/processed_executions.json"
    wellness_history_store_path: str = "artifacts/wellness_history.json"

    # Supabase / Postgres
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "DATABASE_URL",
            "SUPABASE_DB_URL",
            "DIRECT_CONNECTING_STRING",
            "direct_connecting_string",
        ),
    )
    supabase_url: str | None = Field(default=None, validation_alias=AliasChoices("SUPABASE_URL", "project_url"))
    supabase_publishable_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_PUBLISHABLE_KEY", "publishable_key"),
    )


settings = Settings()

