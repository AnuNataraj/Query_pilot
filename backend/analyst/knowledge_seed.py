"""Starter knowledge base: the business context an analyst would need to know.

None of this is guessable from the schema alone (e.g. the fiscal calendar or
what counts as revenue), which is exactly why the AI retrieves it (RAG).
"""

SEED_DOCS = [
    # ---- Table guides ---------------------------------------------------------
    {
        "kind": "table",
        "title": "Table guide: customers",
        "content": (
            "One row per customer (also called clients, buyers or accounts). "
            "region is one of West, Central, East, South. segment is one of Consumer, "
            "Small Business, Enterprise. signup_date is a YYYY-MM-DD text date. "
            "Use region and segment for customer breakdowns."
        ),
    },
    {
        "kind": "table",
        "title": "Table guide: products",
        "content": (
            "One row per product (item, SKU). category is one of Audio, Smart Home, Computing, "
            "Wearables, Gaming, Accessories. unit_price is the current list price; unit_cost is "
            "what we pay the supplier per unit and is used for margin and profit."
        ),
    },
    {
        "kind": "table",
        "title": "Table guide: orders",
        "content": (
            "One row per order (purchase, transaction, checkout). order_date is a YYYY-MM-DD text date. "
            "channel is web, mobile or store. status is completed, refunded or cancelled. "
            "Only completed orders count toward revenue, sales and margin."
        ),
    },
    {
        "kind": "table",
        "title": "Table guide: order_items",
        "content": (
            "Line items: one row per product in an order. quantity is units bought, unit_price is the "
            "price charged per unit before discount, discount is a fraction between 0 and 1 "
            "(0.15 means 15% off). Line revenue = quantity * unit_price * (1 - discount)."
        ),
    },
    # ---- Business rules ---------------------------------------------------------
    {
        "kind": "glossary",
        "title": "Revenue (sales)",
        "content": (
            "Revenue, also called sales or net sales, is "
            "SUM(order_items.quantity * order_items.unit_price * (1 - order_items.discount)) "
            "over orders with status = 'completed'. Refunded and cancelled orders are never revenue."
        ),
    },
    {
        "kind": "glossary",
        "title": "Gross margin (profit)",
        "content": (
            "Gross margin, or gross profit, is revenue minus cost of goods: "
            "revenue - SUM(order_items.quantity * products.unit_cost), completed orders only. "
            "Gross margin % = gross margin / revenue * 100, rounded to 1 decimal."
        ),
    },
    {
        "kind": "glossary",
        "title": "Average order value (AOV)",
        "content": "Average order value (AOV) = revenue / COUNT(DISTINCT order_id), completed orders only.",
    },
    {
        "kind": "glossary",
        "title": "Active and churned customers",
        "content": (
            "An active customer placed at least one completed order in the last 90 days "
            "(order_date >= date(today, '-90 days')). A churned customer has completed orders "
            "but none in the last 180 days."
        ),
    },
    {
        "kind": "glossary",
        "title": "Refund rate",
        "content": (
            "Refund rate = refunded orders / (completed orders + refunded orders), as a percentage. "
            "Cancelled orders are excluded because they never shipped."
        ),
    },
    {
        "kind": "glossary",
        "title": "Fiscal calendar (fiscal year, fiscal quarter)",
        "content": (
            "Our fiscal year starts on February 1. FY2025 runs Feb 1, 2025 to Jan 31, 2026 "
            "(a fiscal year is named for the calendar year it starts in). Fiscal quarters: "
            "Q1 = Feb-Apr, Q2 = May-Jul, Q3 = Aug-Oct, Q4 = Nov-Jan. In SQLite: "
            "fiscal_year = CAST(strftime('%Y', order_date, 'start of month', '-1 month') AS INTEGER); "
            "fiscal_quarter = (CAST(strftime('%m', order_date, 'start of month', '-1 month') AS INTEGER) + 2) / 3."
        ),
    },
    {
        "kind": "glossary",
        "title": "Reporting conventions for trends",
        "content": (
            "Monthly trends group by strftime('%Y-%m', order_date) AS month, sorted ascending. "
            "Exclude the current, incomplete month. 'Last 12 months' means the 12 full calendar "
            "months before the current month. Round money to 2 decimals."
        ),
    },
    # ---- Worked examples (few-shot) ----------------------------------------------
    {
        "kind": "example",
        "title": "Example: revenue by product category",
        "content": (
            "Question: What is revenue by product category?\n"
            "SQL:\n"
            "SELECT p.category,\n"
            "       ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS revenue\n"
            "FROM order_items oi\n"
            "JOIN orders o   ON o.order_id = oi.order_id\n"
            "JOIN products p ON p.product_id = oi.product_id\n"
            "WHERE o.status = 'completed'\n"
            "GROUP BY p.category\n"
            "ORDER BY revenue DESC;"
        ),
    },
    {
        "kind": "example",
        "title": "Example: monthly completed orders",
        "content": (
            "Question: How many orders did we complete each month?\n"
            "SQL:\n"
            "SELECT strftime('%Y-%m', order_date) AS month, COUNT(*) AS completed_orders\n"
            "FROM orders\n"
            "WHERE status = 'completed'\n"
            "  AND order_date < date('now', 'start of month')\n"
            "GROUP BY month\n"
            "ORDER BY month;"
        ),
    },
]
