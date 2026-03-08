from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psycopg
except Exception:  # pragma: no cover - optional dependency path
    psycopg = None  # type: ignore[assignment]

from agentcare.settings import settings

logger = logging.getLogger(__name__)


def _rag_vector_lookup(rows: list[dict[str, Any]], query: str) -> dict[str, Any]:
    """
    Robust ragfallback-based lookup using vector retrieval only.
    We avoid the package's LLM-based fallback chain because it is brittle across HF client versions.
    """
    try:
        from langchain.docstore.document import Document  # type: ignore
        from ragfallback.utils import create_faiss_vector_store, create_open_source_embeddings  # type: ignore

        if not rows:
            return {"found": False, "engine": "ragfallback_vector", "reason": "empty_store"}

        docs: list[Document] = []
        by_customer_id: dict[str, dict[str, Any]] = {}
        for r in rows:
            cid = str(r.get("customer_id") or "")
            if not cid:
                continue
            by_customer_id[cid] = r
            docs.append(
                Document(
                    page_content=(
                        f"customer_id={cid} "
                        f"name={r.get('name')} "
                        f"email={r.get('email')} "
                        f"phone={r.get('phone_e164')} "
                        f"summary={r.get('last_summary')} "
                        f"notes={' | '.join(r.get('notes', []))}"
                    ),
                    metadata={"customer_id": cid},
                )
            )
        if not docs:
            return {"found": False, "engine": "ragfallback_vector", "reason": "no_indexable_docs"}

        embeddings = create_open_source_embeddings()
        vector_store = create_faiss_vector_store(docs, embeddings)
        hits = vector_store.similarity_search(query, k=min(3, len(docs)))

        matches: list[dict[str, Any]] = []
        for hit in hits:
            cid = str((hit.metadata or {}).get("customer_id") or "")
            row = by_customer_id.get(cid)
            if row:
                matches.append({"customer_id": cid, "customer": row})
        if not matches:
            return {"found": False, "engine": "ragfallback_vector", "reason": "no_match"}
        return {
            "found": True,
            "engine": "ragfallback_vector",
            "customer": matches[0]["customer"],
            "matches": matches,
        }
    except Exception as e:
        return {"found": False, "engine": "ragfallback_vector", "reason": "error", "error": str(e)}


def _lexical_lookup(rows: list[dict[str, Any]], query: str) -> dict[str, Any]:
    if not rows:
        return {"found": False, "reason": "empty_store"}
    q = query.lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for r in rows:
        text = (
            f"{r.get('name','')} {r.get('email','')} {r.get('phone_e164','')} "
            f"{r.get('last_summary','')} {' '.join(r.get('notes', []))}"
        ).lower()
        score = sum(1 for tok in q.split() if tok and tok in text)
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    if best_score <= 0:
        return {"found": False, "engine": "lexical_fallback", "reason": "no_match"}
    return {"found": True, "engine": "lexical_fallback", "score": best_score, "customer": best}


def _database_url_with_ssl(database_url: str) -> str:
    if "sslmode=" in database_url:
        return database_url
    sep = "&" if "?" in database_url else "?"
    return f"{database_url}{sep}sslmode=require"


def _can_connect_postgres(database_url: str) -> bool:
    if psycopg is None:
        return False
    try:
        with psycopg.connect(_database_url_with_ssl(database_url), connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception as e:
        logger.warning("Postgres reachability check failed, falling back to JSON store: %s", e)
        return False

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CustomerProfile:
    customer_id: str
    name: str | None = None
    email: str | None = None
    phone_e164: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    interaction_count: int = 0
    last_summary: str | None = None
    last_status: str | None = None
    last_appointment_id: str | None = None
    last_slot_start: str | None = None
    notes: list[str] = field(default_factory=list)


class CustomerMemoryStore:
    """
    Hybrid customer memory:
    1) deterministic match on email/phone for exact customer identity
    2) optional semantic lookup with ragfallback for free-text retrieval
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([])

    def _read(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.path.read_text("utf-8"))
        except Exception:
            return []

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(rows, indent=2), "utf-8")

    def _next_id(self, rows: list[dict[str, Any]]) -> str:
        return f"cust_{len(rows) + 1:06d}"

    def get_all(self) -> list[CustomerProfile]:
        return [CustomerProfile(**r) for r in self._read()]

    def find_exact(self, *, email: str | None = None, phone_e164: str | None = None) -> CustomerProfile | None:
        rows = self._read()
        for r in rows:
            if email and r.get("email") and r.get("email").lower() == email.lower():
                return CustomerProfile(**r)
            if phone_e164 and r.get("phone_e164") == phone_e164:
                return CustomerProfile(**r)
        return None

    def upsert_from_interaction(
        self,
        *,
        name: str | None = None,
        email: str | None = None,
        phone_e164: str | None = None,
        summary: str | None = None,
        status: str | None = None,
        appointment_id: str | None = None,
        slot_start: str | None = None,
        note: str | None = None,
    ) -> CustomerProfile:
        rows = self._read()

        idx = None
        for i, r in enumerate(rows):
            if email and r.get("email") and r.get("email").lower() == email.lower():
                idx = i
                break
            if phone_e164 and r.get("phone_e164") == phone_e164:
                idx = i
                break

        if idx is None:
            p = CustomerProfile(
                customer_id=self._next_id(rows),
                name=name,
                email=email,
                phone_e164=phone_e164,
                interaction_count=1,
                last_summary=summary,
                last_status=status,
                last_appointment_id=appointment_id,
                last_slot_start=slot_start,
                notes=[note] if note else [],
            )
            rows.append(asdict(p))
            self._write(rows)
            return p

        existing = CustomerProfile(**rows[idx])
        existing.name = name or existing.name
        existing.email = email or existing.email
        existing.phone_e164 = phone_e164 or existing.phone_e164
        existing.interaction_count += 1
        existing.updated_at = _utc_now()
        existing.last_summary = summary or existing.last_summary
        existing.last_status = status or existing.last_status
        existing.last_appointment_id = appointment_id or existing.last_appointment_id
        existing.last_slot_start = slot_start or existing.last_slot_start
        if note:
            existing.notes.append(note)

        rows[idx] = asdict(existing)
        self._write(rows)
        return existing

    def semantic_lookup(self, query: str) -> dict[str, Any]:
        """
        Optional semantic lookup using ragfallback.
        Falls back to a simple lexical scoring strategy if ragfallback is unavailable.
        """
        rows = self._read()
        rag = _rag_vector_lookup(rows, query)
        if rag.get("found"):
            return rag
        lexical = _lexical_lookup(rows, query)
        if not lexical.get("found"):
            lexical["rag_error"] = rag.get("error") or rag.get("reason")
        return lexical


class PostgresCustomerMemoryStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _conn(self):
        if psycopg is None:
            raise RuntimeError("Postgres extras not installed. Install with: pip install 'agentcare[postgres]'")
        return psycopg.connect(self.database_url)

    def get_all(self) -> list[CustomerProfile]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT customer_id, name, email, phone_e164, created_at, updated_at,
                           interaction_count, last_summary, last_status, last_appointment_id, last_slot_start, notes
                    FROM customer_profiles
                    ORDER BY created_at ASC
                    """
                )
                rows = cur.fetchall()
        out: list[CustomerProfile] = []
        for r in rows:
            out.append(
                CustomerProfile(
                    customer_id=r[0],
                    name=r[1],
                    email=r[2],
                    phone_e164=r[3],
                    created_at=str(r[4]),
                    updated_at=str(r[5]),
                    interaction_count=r[6],
                    last_summary=r[7],
                    last_status=r[8],
                    last_appointment_id=r[9],
                    last_slot_start=r[10],
                    notes=r[11] or [],
                )
            )
        return out

    def find_exact(self, *, email: str | None = None, phone_e164: str | None = None) -> CustomerProfile | None:
        if not email and not phone_e164:
            return None
        with self._conn() as conn:
            with conn.cursor() as cur:
                if email and phone_e164:
                    cur.execute(
                        """
                        SELECT customer_id, name, email, phone_e164, created_at, updated_at,
                               interaction_count, last_summary, last_status, last_appointment_id, last_slot_start, notes
                        FROM customer_profiles
                        WHERE lower(email) = lower(%s) OR phone_e164 = %s
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (email, phone_e164),
                    )
                elif email:
                    cur.execute(
                        """
                        SELECT customer_id, name, email, phone_e164, created_at, updated_at,
                               interaction_count, last_summary, last_status, last_appointment_id, last_slot_start, notes
                        FROM customer_profiles
                        WHERE lower(email) = lower(%s)
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (email,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT customer_id, name, email, phone_e164, created_at, updated_at,
                               interaction_count, last_summary, last_status, last_appointment_id, last_slot_start, notes
                        FROM customer_profiles
                        WHERE phone_e164 = %s
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (phone_e164,),
                    )
                row = cur.fetchone()
        if not row:
            return None
        return CustomerProfile(
            customer_id=row[0],
            name=row[1],
            email=row[2],
            phone_e164=row[3],
            created_at=str(row[4]),
            updated_at=str(row[5]),
            interaction_count=row[6],
            last_summary=row[7],
            last_status=row[8],
            last_appointment_id=row[9],
            last_slot_start=row[10],
            notes=row[11] or [],
        )

    def upsert_from_interaction(
        self,
        *,
        name: str | None = None,
        email: str | None = None,
        phone_e164: str | None = None,
        summary: str | None = None,
        status: str | None = None,
        appointment_id: str | None = None,
        slot_start: str | None = None,
        note: str | None = None,
    ) -> CustomerProfile:
        existing = self.find_exact(email=email, phone_e164=phone_e164)
        with self._conn() as conn:
            with conn.cursor() as cur:
                if existing is None:
                    cur.execute("SELECT nextval('customer_id_seq')")
                    n = cur.fetchone()[0]
                    cid = f"cust_{n:06d}"
                    notes = [note] if note else []
                    cur.execute(
                        """
                        INSERT INTO customer_profiles (
                            customer_id, name, email, phone_e164, created_at, updated_at, interaction_count,
                            last_summary, last_status, last_appointment_id, last_slot_start, notes
                        ) VALUES (%s,%s,%s,%s,now(),now(),1,%s,%s,%s,%s,%s)
                        """,
                        (cid, name, email, phone_e164, summary, status, appointment_id, slot_start, notes),
                    )
                    conn.commit()
                    return CustomerProfile(
                        customer_id=cid,
                        name=name,
                        email=email,
                        phone_e164=phone_e164,
                        interaction_count=1,
                        last_summary=summary,
                        last_status=status,
                        last_appointment_id=appointment_id,
                        last_slot_start=slot_start,
                        notes=notes,
                    )

                notes = list(existing.notes)
                if note:
                    notes.append(note)
                cur.execute(
                    """
                    UPDATE customer_profiles
                    SET name = COALESCE(%s, name),
                        email = COALESCE(%s, email),
                        phone_e164 = COALESCE(%s, phone_e164),
                        updated_at = now(),
                        interaction_count = interaction_count + 1,
                        last_summary = COALESCE(%s, last_summary),
                        last_status = COALESCE(%s, last_status),
                        last_appointment_id = COALESCE(%s, last_appointment_id),
                        last_slot_start = COALESCE(%s, last_slot_start),
                        notes = %s
                    WHERE customer_id = %s
                    """,
                    (
                        name,
                        email,
                        phone_e164,
                        summary,
                        status,
                        appointment_id,
                        slot_start,
                        notes,
                        existing.customer_id,
                    ),
                )
                conn.commit()
                existing.name = name or existing.name
                existing.email = email or existing.email
                existing.phone_e164 = phone_e164 or existing.phone_e164
                existing.interaction_count += 1
                existing.updated_at = _utc_now()
                existing.last_summary = summary or existing.last_summary
                existing.last_status = status or existing.last_status
                existing.last_appointment_id = appointment_id or existing.last_appointment_id
                existing.last_slot_start = slot_start or existing.last_slot_start
                existing.notes = notes
                return existing

    def semantic_lookup(self, query: str) -> dict[str, Any]:
        rows = [asdict(p) for p in self.get_all()]
        rag = _rag_vector_lookup(rows, query)
        if rag.get("found"):
            return rag
        lexical = _lexical_lookup(rows, query)
        if not lexical.get("found"):
            lexical["rag_error"] = rag.get("error") or rag.get("reason")
        return lexical

    def is_execution_processed(self, execution_id: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM processed_executions WHERE execution_id = %s LIMIT 1", (execution_id,))
                return cur.fetchone() is not None

    def mark_execution_processed(self, execution_id: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO processed_executions (execution_id, created_at) VALUES (%s, now()) ON CONFLICT DO NOTHING",
                    (execution_id,),
                )
                conn.commit()


def init_postgres_schema(database_url: str) -> None:
    if psycopg is None:
        raise RuntimeError("Postgres extras not installed. Install with: pip install 'agentcare[postgres]'")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE SEQUENCE IF NOT EXISTS customer_id_seq START 1;
                CREATE TABLE IF NOT EXISTS customer_profiles (
                    customer_id TEXT PRIMARY KEY,
                    name TEXT NULL,
                    email TEXT NULL,
                    phone_e164 TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    interaction_count INTEGER NOT NULL DEFAULT 0,
                    last_summary TEXT NULL,
                    last_status TEXT NULL,
                    last_appointment_id TEXT NULL,
                    last_slot_start TEXT NULL,
                    notes TEXT[] NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_customer_profiles_email ON customer_profiles (lower(email));
                CREATE INDEX IF NOT EXISTS idx_customer_profiles_phone ON customer_profiles (phone_e164);
                CREATE TABLE IF NOT EXISTS processed_executions (
                    execution_id TEXT PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS call_executions (
                    execution_id TEXT PRIMARY KEY,
                    customer_id TEXT NULL REFERENCES customer_profiles(customer_id) ON DELETE SET NULL,
                    status TEXT NULL,
                    transcript TEXT NULL,
                    conversation_time DOUBLE PRECISION NULL,
                    total_cost DOUBLE PRECISION NULL,
                    source_phone TEXT NULL,
                    target_phone TEXT NULL,
                    appointment_id TEXT NULL,
                    slot_start TEXT NULL,
                    intent TEXT NULL,
                    follow_up_required BOOLEAN NULL,
                    patient_facing_summary TEXT NULL,
                    internal_ops_summary TEXT NULL,
                    extracted_data JSONB NOT NULL DEFAULT '{}'::jsonb,
                    context_details JSONB NOT NULL DEFAULT '{}'::jsonb,
                    telephony_data JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                ALTER TABLE IF EXISTS call_executions
                    ADD COLUMN IF NOT EXISTS patient_facing_summary TEXT NULL;
                ALTER TABLE IF EXISTS call_executions
                    ADD COLUMN IF NOT EXISTS internal_ops_summary TEXT NULL;
                CREATE INDEX IF NOT EXISTS idx_call_executions_created_at ON call_executions (created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_call_executions_status ON call_executions (status);
                CREATE INDEX IF NOT EXISTS idx_call_executions_customer_id ON call_executions (customer_id);
                CREATE INDEX IF NOT EXISTS idx_call_executions_target_phone ON call_executions (target_phone);

                CREATE TABLE IF NOT EXISTS appointments (
                    appointment_id TEXT PRIMARY KEY,
                    customer_id TEXT NULL REFERENCES customer_profiles(customer_id) ON DELETE SET NULL,
                    slot_start TEXT NULL,
                    status TEXT NULL,
                    source_execution_id TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_appointments_customer_id ON appointments (customer_id);
                CREATE INDEX IF NOT EXISTS idx_appointments_created_at ON appointments (created_at DESC);

                CREATE TABLE IF NOT EXISTS call_lifecycle_events (
                    event_id BIGSERIAL PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    status TEXT NULL,
                    state TEXT NOT NULL,
                    source TEXT NOT NULL,
                    details JSONB NOT NULL DEFAULT '{}'::jsonb,
                    ts TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_call_lifecycle_exec_ts
                    ON call_lifecycle_events (execution_id, ts DESC);

                CREATE OR REPLACE VIEW analytics_calls_daily AS
                SELECT
                  date_trunc('day', created_at) AS day,
                  COUNT(*) AS total_calls,
                  COUNT(*) FILTER (WHERE status = 'completed') AS completed_calls,
                  COALESCE(AVG(conversation_time),0) AS avg_conversation_time,
                  COALESCE(SUM(total_cost),0) AS total_cost
                FROM call_executions
                GROUP BY 1
                ORDER BY 1 DESC;
                """
            )
            conn.commit()


def get_customer_store():
    backend = settings.customer_store_backend.strip().lower()
    if backend in {"postgres", "auto"}:
        if not settings.database_url or "[YOUR-" in settings.database_url or "YOUR-PASSWORD" in settings.database_url:
            # Gracefully fall back during local setup when placeholder env values are present.
            logger.warning("Postgres backend selected but DATABASE_URL is missing/placeholder; falling back to JSON store.")
            return CustomerMemoryStore(Path(settings.customer_store_path))
        if _can_connect_postgres(settings.database_url):
            return PostgresCustomerMemoryStore(_database_url_with_ssl(settings.database_url))
        return CustomerMemoryStore(Path(settings.customer_store_path))
    return CustomerMemoryStore(Path(settings.customer_store_path))

