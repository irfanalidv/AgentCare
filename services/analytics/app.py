from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from agentcare.analytics import (
    get_call_detail,
    get_call_detail_fallback,
    get_calls_timeseries,
    get_calls_timeseries_fallback,
    get_customer_cohorts,
    get_customer_cohorts_fallback,
    get_funnel,
    get_funnel_fallback,
    get_overview,
    get_overview_fallback,
)
from agentcare.settings import settings


app = FastAPI(title="AgentCare Analytics", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _db_ready() -> bool:
    if not settings.database_url:
        return False
    bad = ("[YOUR-", "YOUR-PASSWORD")
    return not any(x in settings.database_url for x in bad)


def _run_with_timeout(fn, timeout_s: float, **kwargs: Any) -> Any:
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn, **kwargs)
    try:
        return fut.result(timeout=timeout_s)
    finally:
        # Do not block response path on slow DB calls.
        ex.shutdown(wait=False, cancel_futures=True)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    # Keep health checks non-blocking; avoid DB/customer-store initialization here.
    backend = str(settings.customer_store_backend or "auto")
    effective_store = {
        "postgres": "PostgresCustomerStore",
        "json": "JsonCustomerStore",
        "auto": "AutoCustomerStore",
    }.get(backend, "UnknownCustomerStore")
    return {
        "ok": True,
        "db_ready": _db_ready(),
        "backend": backend,
        "effective_customer_store": effective_store,
        "fallback_enabled": True,
    }


@app.get("/analytics/overview")
def analytics_overview(
    from_ts: str | None = Query(default=None),
    to_ts: str | None = Query(default=None),
) -> dict[str, Any]:
    if not _db_ready():
        return get_overview_fallback(from_ts=from_ts, to_ts=to_ts)
    try:
        return _run_with_timeout(get_overview, timeout_s=4.0, from_ts=from_ts, to_ts=to_ts)
    except FuturesTimeoutError:
        return get_overview_fallback(from_ts=from_ts, to_ts=to_ts)
    except Exception:
        return get_overview_fallback(from_ts=from_ts, to_ts=to_ts)


@app.get("/analytics/calls/timeseries")
def analytics_calls_timeseries(
    from_ts: str | None = Query(default=None),
    to_ts: str | None = Query(default=None),
    interval: str = Query(default="day"),
) -> dict[str, Any]:
    if not _db_ready():
        return {"rows": get_calls_timeseries_fallback(from_ts=from_ts, to_ts=to_ts, interval=interval)}
    try:
        rows = _run_with_timeout(
            get_calls_timeseries,
            timeout_s=4.0,
            from_ts=from_ts,
            to_ts=to_ts,
            interval=interval,
        )
        return {"rows": rows}
    except FuturesTimeoutError:
        return {"rows": get_calls_timeseries_fallback(from_ts=from_ts, to_ts=to_ts, interval=interval)}
    except Exception:
        return {"rows": get_calls_timeseries_fallback(from_ts=from_ts, to_ts=to_ts, interval=interval)}


@app.get("/analytics/funnel")
def analytics_funnel(
    from_ts: str | None = Query(default=None),
    to_ts: str | None = Query(default=None),
) -> dict[str, Any]:
    if not _db_ready():
        return get_funnel_fallback(from_ts=from_ts, to_ts=to_ts)
    try:
        return _run_with_timeout(get_funnel, timeout_s=4.0, from_ts=from_ts, to_ts=to_ts)
    except FuturesTimeoutError:
        return get_funnel_fallback(from_ts=from_ts, to_ts=to_ts)
    except Exception:
        return get_funnel_fallback(from_ts=from_ts, to_ts=to_ts)


@app.get("/analytics/customers/cohorts")
def analytics_customer_cohorts(
    from_ts: str | None = Query(default=None),
    to_ts: str | None = Query(default=None),
) -> dict[str, Any]:
    if not _db_ready():
        return get_customer_cohorts_fallback(from_ts=from_ts, to_ts=to_ts)
    try:
        return _run_with_timeout(get_customer_cohorts, timeout_s=4.0, from_ts=from_ts, to_ts=to_ts)
    except FuturesTimeoutError:
        return get_customer_cohorts_fallback(from_ts=from_ts, to_ts=to_ts)
    except Exception:
        return get_customer_cohorts_fallback(from_ts=from_ts, to_ts=to_ts)


@app.get("/analytics/calls/{execution_id}")
def analytics_call_detail(execution_id: str) -> dict[str, Any]:
    execution_id = str(execution_id or "").strip()
    if not execution_id:
        return {"ok": False, "error": "execution_id is required"}
    if not _db_ready():
        row = get_call_detail_fallback(execution_id)
        if not row:
            return {"ok": False, "error": "not_found", "execution_id": execution_id}
        return {"ok": True, "row": row}
    try:
        row = _run_with_timeout(get_call_detail, timeout_s=4.0, execution_id=execution_id)
        if not row:
            fallback = get_call_detail_fallback(execution_id)
            if fallback:
                return {"ok": True, "row": fallback}
            return {"ok": False, "error": "not_found", "execution_id": execution_id}
        return {"ok": True, "row": row}
    except FuturesTimeoutError:
        fallback = get_call_detail_fallback(execution_id)
        if fallback:
            return {"ok": True, "row": fallback}
        return {"ok": False, "error": "timeout", "execution_id": execution_id}
    except Exception:
        fallback = get_call_detail_fallback(execution_id)
        if fallback:
            return {"ok": True, "row": fallback}
        return {"ok": False, "error": "not_found", "execution_id": execution_id}

