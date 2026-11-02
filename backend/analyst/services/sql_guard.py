"""First safety layer: only a single read-only SELECT statement may pass.

This check is deliberately strict and cheap. It is not the only defense: the
warehouse connection itself is read-only and has an authorizer (see warehouse.py),
so even SQL that slipped past this parser could not modify data.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlparse

MAX_SQL_LENGTH = 5000


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    sql: str = ""
    reason: str = ""


def check_sql(sql: str | None) -> GuardResult:
    if not sql or not sql.strip():
        return GuardResult(False, reason="The query is empty.")
    if len(sql) > MAX_SQL_LENGTH:
        return GuardResult(False, reason=f"The query is longer than {MAX_SQL_LENGTH} characters.")

    statements = [s for s in sqlparse.split(sql) if s.strip().rstrip(";").strip()]
    if len(statements) != 1:
        return GuardResult(False, reason="Only one SQL statement can run at a time.")

    statement = statements[0].strip().rstrip(";").strip()
    kind = sqlparse.parse(statement)[0].get_type()
    if kind != "SELECT":
        label = kind if kind != "UNKNOWN" else "that statement type"
        return GuardResult(False, reason=f"Only read-only SELECT queries are allowed ({label} was blocked).")
    return GuardResult(True, sql=statement)
