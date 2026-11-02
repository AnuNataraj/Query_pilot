import pytest

from analyst.services import warehouse


def test_execute_returns_columns_and_rows():
    result = warehouse.execute("SELECT region, COUNT(*) AS n FROM customers GROUP BY region ORDER BY region")
    assert result.columns == ["region", "n"]
    assert [r[0] for r in result.rows] == ["Central", "East", "South", "West"]
    assert not result.truncated


@pytest.mark.parametrize("sql", [
    "DELETE FROM customers",
    "UPDATE products SET unit_price = 0",
    "CREATE TABLE hacked (x INTEGER)",
    "PRAGMA writable_schema = 1",
])
def test_database_layer_blocks_writes_even_without_the_guard(sql):
    # Defense in depth: these bypass sql_guard entirely and still cannot run.
    with pytest.raises(warehouse.QueryError):
        warehouse.execute(sql)
    assert warehouse.execute("SELECT COUNT(*) FROM customers").rows[0][0] == 150


def test_row_cap_marks_result_truncated(settings):
    result = warehouse.execute("SELECT * FROM orders", max_rows=10)
    assert result.row_count == 10
    assert result.truncated


def test_runaway_query_is_stopped():
    sql = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT MAX(x) FROM n"
    with pytest.raises(warehouse.QueryError, match="limit"):
        warehouse.execute(sql, timeout_s=0.3)


def test_explain_shows_index_usage():
    plan = warehouse.explain("SELECT * FROM orders WHERE order_date >= '2026-10-01'")
    assert any("idx_orders_date" in step["detail"] for step in plan)


def test_schema_prompt_lists_tables_and_categorical_values():
    text = warehouse.schema_for_prompt()
    for table in ("customers", "products", "orders", "order_items"):
        assert f"{table}(" in text
    assert "'completed'" in text and "'refunded'" in text
    assert "-> customers.customer_id" in text


def test_missing_warehouse_gives_clear_error(settings, tmp_path):
    settings.WAREHOUSE_PATH = tmp_path / "nope.db"
    with pytest.raises(warehouse.WarehouseNotReady, match="seed_demo"):
        warehouse.execute("SELECT 1")
