import pytest

from analyst.services.sql_guard import check_sql


@pytest.mark.parametrize("sql", [
    "SELECT * FROM customers",
    "select count(*) from orders;",
    "WITH t AS (SELECT 1 AS x) SELECT x FROM t",
    "-- top customers\nSELECT name FROM customers LIMIT 5",
    "SELECT 1 UNION ALL SELECT 2",
])
def test_allows_single_select(sql):
    result = check_sql(sql)
    assert result.ok, result.reason
    assert not result.sql.endswith(";")


@pytest.mark.parametrize("sql, reason_part", [
    ("DELETE FROM customers", "DELETE"),
    ("DROP TABLE orders", "DROP"),
    ("UPDATE products SET unit_price = 0", "UPDATE"),
    ("INSERT INTO customers (name) VALUES ('x')", "INSERT"),
    ("WITH t AS (SELECT 1) DELETE FROM orders", "DELETE"),
    ("PRAGMA table_info(customers)", "statement type"),
    ("ATTACH DATABASE 'other.db' AS other", "statement type"),
    ("SELECT 1; DROP TABLE orders", "one SQL statement"),
    ("", "empty"),
    ("   ", "empty"),
])
def test_blocks_everything_else(sql, reason_part):
    result = check_sql(sql)
    assert not result.ok
    assert reason_part.lower() in result.reason.lower()


def test_comment_cannot_hide_second_statement():
    assert check_sql("SELECT 1 -- ; DROP TABLE orders").ok  # the DROP is only a comment
    assert not check_sql("SELECT 1 /* x */; DROP TABLE orders").ok


def test_rejects_huge_queries():
    assert not check_sql("SELECT " + "1 + " * 3000 + "1").ok
