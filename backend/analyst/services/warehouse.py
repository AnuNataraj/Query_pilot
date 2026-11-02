"""Read-only access to the analytics warehouse (a separate SQLite database).

Safety is layered, so no single bug can let the AI change data:
  1. sql_guard: only one SELECT statement is accepted
  2. the connection is opened in SQLite read-only mode (mode=ro)
  3. an authorizer callback denies every operation except reading
  4. a progress handler stops queries that run longer than the time limit
  5. results are capped at MAX_ROWS rows
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings


class WarehouseError(Exception):
    """Base error for warehouse access."""


class WarehouseNotReady(WarehouseError):
    pass


class QueryError(WarehouseError):
    pass


_READ_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),  # recursive CTEs
}


def _read_only_authorizer(action: int, *_args) -> int:
    return sqlite3.SQLITE_OK if action in _READ_ACTIONS else sqlite3.SQLITE_DENY


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    truncated: bool
    elapsed_ms: int

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def as_dict(self) -> dict:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "elapsed_ms": self.elapsed_ms,
        }


def warehouse_path() -> Path:
    return Path(settings.WAREHOUSE_PATH)


def is_ready() -> bool:
    return warehouse_path().exists()


def _connect(*, guarded: bool = True) -> sqlite3.Connection:
    path = warehouse_path()
    if not path.exists():
        raise WarehouseNotReady("The demo warehouse is missing. Run: python manage.py seed_demo")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    if guarded:
        conn.set_authorizer(_read_only_authorizer)
    return conn


def _friendly(exc: sqlite3.Error, timeout_s: float) -> str:
    message = str(exc)
    if "interrupted" in message:
        return f"The query took longer than the {timeout_s:g}s limit and was stopped."
    if "not authorized" in message or "readonly" in message:
        return "The database refused the query because it was not read-only."
    return message


def execute(sql: str, *, max_rows: int | None = None, timeout_s: float | None = None) -> QueryResult:
    max_rows = max_rows or settings.MAX_ROWS
    timeout_s = timeout_s or settings.QUERY_TIMEOUT_S
    conn = _connect()
    deadline = time.monotonic() + timeout_s
    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
    started = time.perf_counter()
    try:
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description or []]
        fetched = cursor.fetchmany(max_rows + 1)
    except sqlite3.Error as exc:
        raise QueryError(_friendly(exc, timeout_s)) from exc
    finally:
        conn.close()
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    return QueryResult(
        columns=columns,
        rows=[list(r) for r in fetched[:max_rows]],
        truncated=len(fetched) > max_rows,
        elapsed_ms=elapsed_ms,
    )


def explain(sql: str) -> list[dict]:
    """Return SQLite's query plan, e.g. whether an index is used or a table is scanned."""
    conn = _connect()
    try:
        rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
    except sqlite3.Error as exc:
        raise QueryError(_friendly(exc, settings.QUERY_TIMEOUT_S)) from exc
    finally:
        conn.close()
    return [{"id": r[0], "parent": r[1], "detail": r[3]} for r in rows]


@lru_cache(maxsize=4)
def _describe(path: str, mtime: float) -> dict:
    conn = _connect(guarded=False)  # trusted, internal introspection only
    try:
        tables = []
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        )]
        for name in names:
            fks = {r[3]: f"{r[2]}.{r[4]}" for r in conn.execute(f'PRAGMA foreign_key_list("{name}")')}
            columns = []
            for _cid, col, col_type, _notnull, _default, pk in conn.execute(f'PRAGMA table_info("{name}")'):
                values = None
                if col_type.upper() == "TEXT" and not col.endswith(("_date", "name", "email")):
                    distinct = conn.execute(
                        f'SELECT DISTINCT "{col}" FROM "{name}" ORDER BY 1 LIMIT 9'
                    ).fetchall()
                    if len(distinct) <= 8:
                        values = [d[0] for d in distinct]
                columns.append({
                    "name": col,
                    "type": col_type,
                    "primary_key": bool(pk),
                    "references": fks.get(col),
                    "values": values,
                })
            count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            tables.append({"name": name, "row_count": count, "columns": columns})
        data_from, data_to = conn.execute("SELECT MIN(order_date), MAX(order_date) FROM orders").fetchone()
    finally:
        conn.close()
    return {"tables": tables, "data_from": data_from, "data_to": data_to}


def describe() -> dict:
    path = warehouse_path()
    if not path.exists():
        raise WarehouseNotReady("The demo warehouse is missing. Run: python manage.py seed_demo")
    return _describe(str(path), path.stat().st_mtime)


def schema_for_prompt() -> str:
    """Compact schema text for the LLM, including allowed values for categorical columns."""
    info = describe()
    lines = []
    for table in info["tables"]:
        cols = []
        for c in table["columns"]:
            text = f"{c['name']} {c['type']}"
            if c["primary_key"]:
                text += " PK"
            if c["references"]:
                text += f" -> {c['references']}"
            if c["values"]:
                text += " in (" + ", ".join(repr(v) for v in c["values"]) + ")"
            cols.append(text)
        lines.append(f"{table['name']}({', '.join(cols)})  -- {table['row_count']:,} rows")
    lines.append(f"-- orders cover {info['data_from']} to {info['data_to']}")
    return "\n".join(lines)
