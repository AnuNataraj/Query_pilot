"""The analyst pipeline: retrieve context -> write SQL -> safety check -> run -> explain.

run_pipeline() is a generator of events, so the API can stream every step to
the browser as it happens. If a query fails, the database error is sent back to
the model so it can fix its own SQL (up to MAX_SQL_ATTEMPTS tries).
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Iterator

from django.conf import settings

from ..models import QueryRun
from . import charting, prompts, retriever, sql_guard, warehouse
from .llm import LLMClient, LLMError, get_llm

logger = logging.getLogger(__name__)


def _ms(since: float) -> int:
    return round((time.perf_counter() - since) * 1000)


def _step(step_id: str, kind: str, status: str, label: str, ms: int | None = None, **detail) -> dict:
    return {"type": "step", "id": step_id, "kind": kind, "status": status, "label": label, "ms": ms, "detail": detail}


def _explain(llm: LLMClient, question: str, sql: str, result: warehouse.QueryResult) -> tuple[str, list[str], bool]:
    """Ask the model for a plain-English insight. Falls back to a rule-based summary."""
    fallback = charting.describe_result(result.columns, result.rows)
    if not result.rows:
        return fallback, [], True
    try:
        prompt = prompts.build_insight_prompt(question, sql, result.columns, result.rows, result.truncated)
        reply = llm.complete(prompts.INSIGHT_SYSTEM, [{"role": "user", "content": prompt}], purpose="insight")
    except LLMError as exc:
        logger.warning("Insight generation failed, using fallback: %s", exc)
        return fallback, [], True
    data = prompts.parse_json_reply(reply) or {}
    insight = str(data.get("insight") or "").strip()
    follow_ups = [str(q).strip() for q in (data.get("follow_ups") or []) if str(q).strip()][:3]
    return (insight or fallback), follow_ups, not insight


def run_pipeline(question: str, previous: dict | None = None, llm: LLMClient | None = None) -> Iterator[dict]:
    started = time.perf_counter()
    run = QueryRun(question=question, status=QueryRun.Status.FAILED)
    try:
        llm = llm or get_llm()
        run.provider = llm.label
        schema = warehouse.schema_for_prompt()

        # 1. Retrieval (RAG) ---------------------------------------------------------
        yield _step("retrieve", "retrieve", "running", "Search knowledge base")
        t = time.perf_counter()
        search_text = f"{previous['question']} {question}" if previous and previous.get("question") else question
        hits = retriever.search(search_text)
        yield _step("retrieve", "retrieve", "done", "Search knowledge base", _ms(t),
                    docs=[h.as_dict() for h in hits])

        # 2-4. Generate SQL -> guard -> execute, with self-correction ---------------------
        system = prompts.sql_system(date.today().isoformat())
        messages = [{"role": "user", "content": prompts.build_sql_prompt(question, schema, hits, previous)}]
        draft, result = None, None
        for attempt in range(1, settings.MAX_SQL_ATTEMPTS + 1):
            label = "Write SQL" if attempt == 1 else f"Fix SQL (attempt {attempt})"
            step_id = f"generate-{attempt}"
            run.attempts = attempt
            yield _step(step_id, "generate", "running", label)
            t = time.perf_counter()
            reply = llm.complete(system, messages, purpose="sql")
            try:
                draft = prompts.parse_sql_reply(reply)
            except ValueError as exc:
                run.error = str(exc)
                yield _step(step_id, "generate", "error", label, _ms(t), error=str(exc))
                messages += [{"role": "assistant", "content": reply},
                             {"role": "user", "content": prompts.UNPARSEABLE_PROMPT}]
                continue
            yield _step(step_id, "generate", "done", label, _ms(t),
                        sql=draft.sql, reasoning=draft.reasoning, assumptions=draft.assumptions)

            if draft.sql is None:
                run.status = QueryRun.Status.UNANSWERABLE
                run.error = draft.reasoning or "The question can't be answered from this data."
                break

            run.sql = draft.sql
            guard = sql_guard.check_sql(draft.sql)
            if not guard.ok:
                yield _step(f"guard-{attempt}", "guard", "error", "Safety check", 0, error=guard.reason)
                run.status, run.error = QueryRun.Status.BLOCKED, guard.reason
                break
            yield _step(f"guard-{attempt}", "guard", "done", "Safety check", 0, checks=[
                "Single statement", "SELECT only", "Read-only connection",
                f"{settings.QUERY_TIMEOUT_S:g}s time limit", f"Max {settings.MAX_ROWS} rows",
            ])

            step_id = f"execute-{attempt}"
            yield _step(step_id, "execute", "running", "Run query")
            t = time.perf_counter()
            try:
                result = warehouse.execute(guard.sql)
            except warehouse.QueryError as exc:
                run.error = str(exc)
                yield _step(step_id, "execute", "error", "Run query", _ms(t), error=str(exc))
                messages += [{"role": "assistant", "content": reply},
                             {"role": "user", "content": prompts.REPAIR_PROMPT.format(error=exc)}]
                continue
            yield _step(step_id, "execute", "done", "Run query", result.elapsed_ms,
                        rows=result.row_count, truncated=result.truncated)
            run.sql, run.row_count, run.error = guard.sql, result.row_count, ""
            run.status = QueryRun.Status.ANSWERED
            break
        else:
            run.error = f"No working query after {settings.MAX_SQL_ATTEMPTS} attempts. Last error: {run.error}"

        # 5. Explain the result ---------------------------------------------------------
        chart, follow_ups = {"type": "none"}, []
        if run.status == QueryRun.Status.ANSWERED:
            chart = charting.suggest_chart(result.columns, result.rows)
            yield _step("insight", "insight", "running", "Explain result")
            t = time.perf_counter()
            run.insight, follow_ups, fallback = _explain(llm, question, run.sql, result)
            yield _step("insight", "insight", "done", "Explain result", _ms(t), fallback=fallback)

        run.latency_ms = _ms(started)
        _save(run)
        yield {
            "type": "result",
            "id": run.id,
            "status": run.status,
            "question": question,
            "sql": run.sql,
            "reasoning": draft.reasoning if draft else "",
            "assumptions": draft.assumptions if draft else [],
            "attempts": run.attempts,
            "insight": run.insight,
            "follow_ups": follow_ups,
            "chart": chart,
            "context": [h.as_dict(with_content=True) for h in hits],
            "error": run.error,
            "provider": run.provider,
            "latency_ms": run.latency_ms,
            **(result.as_dict() if run.status == QueryRun.Status.ANSWERED else
               {"columns": [], "rows": [], "row_count": 0, "truncated": False, "elapsed_ms": 0}),
        }
    except (LLMError, warehouse.WarehouseError) as exc:
        logger.warning("Pipeline stopped: %s", exc)
        run.error, run.latency_ms = str(exc), _ms(started)
        _save(run)
        yield {"type": "error", "message": str(exc)}
    except Exception:  # never leave the browser with a half-finished stream
        logger.exception("Unexpected pipeline failure")
        run.error, run.latency_ms = "Unexpected server error", _ms(started)
        _save(run)
        yield {"type": "error", "message": "Unexpected server error. See the backend console for details."}


def _save(run: QueryRun) -> None:
    try:
        run.save()
    except Exception:
        logger.exception("Could not save query history")
