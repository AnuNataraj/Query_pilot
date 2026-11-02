"""Prompt templates and robust parsing of model replies."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

SQL_SYSTEM = """You are QueryPilot, a senior analytics engineer. You turn business questions into one SQLite query against the company's retail data warehouse.

Rules:
- Write exactly ONE read-only SELECT statement (CTEs are fine). SQLite dialect: use strftime() and date(); there is no DATE_TRUNC, ILIKE or EXTRACT.
- Use only the tables and columns in SCHEMA.
- Business definitions in CONTEXT are the company's official rules. Follow them exactly, even when they differ from common usage.
- Today's date is {today}. Interpret relative dates ("last 12 months", "this year") relative to today.
- Give every computed column a readable snake_case alias. Round money to 2 decimals.
- Put the label column first, then the metric that answers the question, then any supporting metrics.
- Trends: sort by the time column ascending. Rankings: sort descending and LIMIT 10 unless told otherwise.
- If the question cannot be answered from this data, or asks to change data, set "sql" to null and explain why in "reasoning".
- If you had to assume the meaning of a term that CONTEXT does not define, list the assumption in "assumptions".

Reply with JSON only, no markdown fences:
{{"sql": "SELECT ...", "reasoning": "one short sentence on the approach", "assumptions": []}}"""

REPAIR_PROMPT = """That SQL failed when it ran against the database:
{error}

Fix the query and reply again with the same JSON format."""

UNPARSEABLE_PROMPT = """Your reply could not be parsed. Reply with JSON only, exactly in this shape:
{"sql": "SELECT ...", "reasoning": "...", "assumptions": []}"""

INSIGHT_SYSTEM = """You are a sharp business analyst presenting query results to a manager.
Write a 1-2 sentence insight that directly answers the question and calls out the most important number or pattern. Use only numbers that appear in the result (simple differences or percentages computed from them are fine). Format money like $1,234.
Then suggest 3 short follow-up questions that the same warehouse (customers, products, orders, order_items) could answer.
Reply with JSON only, no markdown fences:
{"insight": "...", "follow_ups": ["...", "...", "..."]}"""


@dataclass
class SqlDraft:
    sql: str | None
    reasoning: str = ""
    assumptions: list[str] = field(default_factory=list)


def sql_system(today: str) -> str:
    return SQL_SYSTEM.format(today=today)


def build_sql_prompt(question: str, schema: str, hits: list, previous: dict | None = None) -> str:
    if hits:
        context = "\n\n".join(f"[{i}] {h.title}\n{h.content}" for i, h in enumerate(hits, start=1))
    else:
        context = "(no relevant entries found)"
    parts = [f"SCHEMA:\n{schema}", f"CONTEXT (from the company knowledge base):\n{context}"]
    if previous and previous.get("question"):
        parts.append(
            "PREVIOUS QUESTION (use it only if the new question is a follow-up to it):\n"
            f"{previous['question']}\nPREVIOUS SQL:\n{previous.get('sql', '')}"
        )
    parts.append(f"QUESTION: {question}")
    return "\n\n".join(parts)


def build_insight_prompt(question: str, sql: str, columns: list[str], rows: list[list], truncated: bool) -> str:
    payload = {"columns": columns, "rows": rows[:40], "total_rows": len(rows), "truncated": truncated}
    return f"QUESTION: {question}\n\nSQL:\n{sql}\n\nRESULT_JSON:\n{json.dumps(payload, default=str)}"


def parse_json_reply(text: str) -> dict | None:
    """Pull a JSON object out of a model reply, tolerating markdown fences and chatter."""
    text = (text or "").strip()
    candidates = [m.group(1) for m in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.S)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def parse_sql_reply(text: str) -> SqlDraft:
    data = parse_json_reply(text)
    if data is not None and "sql" in data:
        sql = data.get("sql")
        sql = sql.strip() if isinstance(sql, str) and sql.strip() else None
        assumptions = data.get("assumptions") or []
        if isinstance(assumptions, str):
            assumptions = [assumptions]
        return SqlDraft(sql, str(data.get("reasoning") or ""), [str(a) for a in assumptions if a])

    # Fallbacks for models that ignore the JSON instruction.
    match = re.search(r"```sql\s*(.*?)```", text or "", re.S | re.I)
    if match:
        return SqlDraft(match.group(1).strip())
    match = re.search(r"\b(WITH|SELECT)\b.*", text or "", re.S | re.I)
    if match:
        return SqlDraft(match.group(0).strip())
    raise ValueError("The model's reply did not contain SQL.")
