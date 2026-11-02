"""Deterministic result analysis: pick a chart and write a fallback summary.

Chart choice is plain code, not an LLM call: it is instant, free and predictable.
"""
from __future__ import annotations

import re

TIME_VALUE = re.compile(r"^(\d{4}(-\d{2}){0,2}|\d{4}-?Q[1-4]|Q[1-4]|FY\d{4}.*)$")
TIME_NAME = re.compile(r"(date|day|week|month|quarter|year|period)", re.I)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_columns(columns: list[str], rows: list[list]) -> list[int]:
    numeric = []
    for i, _ in enumerate(columns):
        values = [r[i] for r in rows if r[i] is not None]
        if values and all(_is_number(v) for v in values):
            numeric.append(i)
    return numeric


def _is_id(name: str) -> bool:
    return name.lower() == "id" or name.lower().endswith("_id")


def suggest_chart(columns: list[str], rows: list[list]) -> dict:
    if not rows or not columns:
        return {"type": "none"}
    numeric = _numeric_columns(columns, rows)
    values = [i for i in numeric if not _is_id(columns[i])]

    if len(rows) == 1 and values:
        return {"type": "kpi", "items": [{"label": columns[i], "value": rows[0][i]} for i in values[:4]]}

    labels = [i for i in range(len(columns)) if i not in numeric]
    if labels:
        label = labels[0]
    elif len(values) >= 2 and TIME_NAME.search(columns[values[0]]):
        label = values[0]  # e.g. a numeric "year" column
    else:
        return {"type": "none"}
    values = [i for i in values if i != label]
    if not values or len(rows) > 60:
        return {"type": "none"}

    is_time = TIME_NAME.search(columns[label]) or all(TIME_VALUE.match(str(r[label])) for r in rows)
    chart_type = "line" if is_time and len(rows) >= 6 else "bar"
    return {"type": chart_type, "label_column": columns[label], "value_columns": [columns[i] for i in values]}


def _fmt(name: str, value) -> str:
    if not _is_number(value):
        return str(value)
    lowered = name.lower()
    if any(w in lowered for w in ("pct", "percent", "rate")):
        return f"{value:,.1f}%"
    if any(w in lowered for w in ("revenue", "sales", "margin", "profit", "value", "spend", "cost", "price", "aov")):
        return f"${value:,.0f}"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def describe_result(columns: list[str], rows: list[list]) -> str:
    """Rule-based one-line summary, used offline or if the LLM insight call fails."""
    if not rows:
        return "The query ran successfully but returned no rows."
    chart = suggest_chart(columns, rows)
    if chart["type"] == "kpi":
        return " · ".join(f"{i['label'].replace('_', ' ')}: {_fmt(i['label'], i['value'])}" for i in chart["items"])
    if chart["type"] in ("bar", "line"):
        li, vi = columns.index(chart["label_column"]), columns.index(chart["value_columns"][0])
        metric = columns[vi]
        nice = re.sub(r"_?(pct|percent)$", "", metric).replace("_", " ")
        if chart["type"] == "line":
            first, last = rows[0], rows[-1]
            if _is_number(first[vi]) and first[vi]:
                change = (last[vi] - first[vi]) / abs(first[vi]) * 100
                peak = max((r for r in rows if _is_number(r[vi])), key=lambda r: r[vi])
                return (f"{nice.capitalize()} went from {_fmt(metric, first[vi])} in {first[li]} to "
                        f"{_fmt(metric, last[vi])} in {last[li]} ({change:+.0f}%), "
                        f"peaking at {_fmt(metric, peak[vi])} in {peak[li]}.")
        ranked = sorted((r for r in rows if _is_number(r[vi])), key=lambda r: r[vi], reverse=True)
        if ranked:
            top, bottom = ranked[0], ranked[-1]
            return (f"{top[li]} leads on {nice} at {_fmt(metric, top[vi])}; "
                    f"{bottom[li]} is lowest at {_fmt(metric, bottom[vi])}.")
    return f"The query returned {len(rows):,} rows."
