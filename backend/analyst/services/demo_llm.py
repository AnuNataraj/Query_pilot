"""Offline demo provider: canned answers to the sample questions, no API key.

This is a safety net for demos without internet. The UI labels it clearly as
"Offline demo". Set LLM_PROVIDER in backend/.env to use a real model, which
can answer any question.
"""
from __future__ import annotations

import json
import re

from .charting import describe_result
from .llm import LLMClient
from .prompts import parse_json_reply
from .retriever import tokenize

SUGGESTED_QUESTIONS = [
    "What was our monthly revenue over the last 12 months?",
    "Which product categories have the best gross margin %?",
    "Who are our top 10 customers by lifetime revenue?",
    "What is the refund rate by sales channel?",
    "How many active customers do we have?",
    "What was revenue by fiscal quarter in FY2025?",
]

LINE_REVENUE = "oi.quantity * oi.unit_price * (1 - oi.discount)"

CANNED = [
    (("month", "revenue"), "Sum completed line revenue per calendar month for the last 12 full months.", f"""
SELECT strftime('%Y-%m', o.order_date) AS month,
       ROUND(SUM({LINE_REVENUE}), 2) AS revenue
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed'
  AND o.order_date >= date('now', 'start of month', '-12 months')
  AND o.order_date <  date('now', 'start of month')
GROUP BY month
ORDER BY month"""),
    (("categor", "margin"), "Compute revenue minus unit cost per category, as a % of revenue.", f"""
SELECT p.category,
       ROUND(100.0 * (SUM({LINE_REVENUE}) - SUM(oi.quantity * p.unit_cost)) / SUM({LINE_REVENUE}), 1) AS gross_margin_pct,
       ROUND(SUM({LINE_REVENUE}) - SUM(oi.quantity * p.unit_cost), 2) AS gross_margin,
       ROUND(SUM({LINE_REVENUE}), 2) AS revenue
FROM order_items oi
JOIN orders o   ON o.order_id = oi.order_id
JOIN products p ON p.product_id = oi.product_id
WHERE o.status = 'completed'
GROUP BY p.category
ORDER BY gross_margin_pct DESC"""),
    (("top", "customer"), "Rank customers by total completed revenue.", f"""
SELECT c.name AS customer,
       ROUND(SUM({LINE_REVENUE}), 2) AS lifetime_revenue,
       COUNT(DISTINCT o.order_id) AS orders,
       c.segment,
       c.region
FROM customers c
JOIN orders o       ON o.customer_id = c.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed'
GROUP BY c.customer_id
ORDER BY lifetime_revenue DESC
LIMIT 10"""),
    (("refund", "channel"), "Refunded / (completed + refunded) orders per channel.", """
SELECT channel,
       ROUND(100.0 * SUM(status = 'refunded') / SUM(status IN ('completed', 'refunded')), 1) AS refund_rate_pct,
       SUM(status = 'refunded') AS refunded_orders,
       SUM(status IN ('completed', 'refunded')) AS shipped_orders
FROM orders
GROUP BY channel
ORDER BY refund_rate_pct DESC"""),
    (("active", "customer"), "Count distinct customers with a completed order in the last 90 days.", """
SELECT COUNT(DISTINCT customer_id) AS active_customers
FROM orders
WHERE status = 'completed'
  AND order_date >= date('now', '-90 days')"""),
    (("fiscal", "quarter"), "Map order dates to the Feb-1 fiscal calendar, then sum revenue per quarter of FY2025.", f"""
WITH fiscal_orders AS (
    SELECT order_id,
           CAST(strftime('%Y', order_date, 'start of month', '-1 month') AS INTEGER) AS fiscal_year,
           (CAST(strftime('%m', order_date, 'start of month', '-1 month') AS INTEGER) + 2) / 3 AS fiscal_quarter
    FROM orders
    WHERE status = 'completed'
)
SELECT 'Q' || f.fiscal_quarter AS fiscal_quarter,
       ROUND(SUM({LINE_REVENUE}), 2) AS revenue
FROM fiscal_orders f
JOIN order_items oi ON oi.order_id = f.order_id
WHERE f.fiscal_year = 2025
GROUP BY f.fiscal_quarter
ORDER BY f.fiscal_quarter"""),
]

VIP_SQL = f"""
WITH lifetime AS (
    SELECT o.customer_id, SUM({LINE_REVENUE}) AS revenue
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.order_id
    WHERE o.status = 'completed'
    GROUP BY o.customer_id
)
SELECT c.region,
       COUNT(*) AS vip_customers,
       ROUND(SUM(l.revenue), 2) AS vip_revenue
FROM lifetime l
JOIN customers c ON c.customer_id = l.customer_id
WHERE l.revenue >= {{threshold}}
GROUP BY c.region
ORDER BY vip_customers DESC"""


def _question_from(prompt: str) -> str:
    match = re.search(r"QUESTION:\s*(.*)", prompt)
    return match.group(1).strip() if match else prompt


class DemoClient(LLMClient):
    provider = "demo"

    def __init__(self):
        super().__init__("offline-demo")

    def complete(self, system: str, messages: list[dict], *, purpose: str = "") -> str:
        if purpose == "insight":
            return self._insight(messages[0]["content"])
        return json.dumps(self._sql(messages[0]["content"]))

    def _sql(self, prompt: str) -> dict:
        question = _question_from(prompt)
        tokens = tokenize(question)
        if any(t.startswith("vip") for t in tokens):
            context = prompt.split("CONTEXT", 1)[-1].split("QUESTION:", 1)[0]
            entry = next((e for e in re.split(r"\n\[\d+\] ", context) if "vip" in e.lower()), "")
            amount = re.search(r"\$\s?([\d,]+(?:\.\d+)?)\s*(k\b)?", entry, re.I)
            if not amount:
                return {"sql": None, "reasoning": "The knowledge base has no definition of a VIP customer, so I can't tell who qualifies. Add one and ask again.", "assumptions": []}
            threshold = float(amount.group(1).replace(",", "")) * (1000 if amount.group(2) else 1)
            return {"sql": VIP_SQL.format(threshold=f"{threshold:g}").strip(),
                    "reasoning": f"Uses the knowledge-base rule: VIP = lifetime revenue of at least ${threshold:,.0f}.",
                    "assumptions": []}
        for keywords, reasoning, sql in CANNED:
            if all(any(t.startswith(k) for t in tokens) for k in keywords):
                return {"sql": sql.strip(), "reasoning": reasoning, "assumptions": []}
        return {"sql": None, "assumptions": [],
                "reasoning": "Offline demo mode only knows the sample questions. Connect a real LLM in backend/.env to ask anything."}

    def _insight(self, prompt: str) -> str:
        question = _question_from(prompt.split("\n\nSQL:", 1)[0])
        data = parse_json_reply(prompt.split("RESULT_JSON:", 1)[-1]) or {}
        insight = describe_result(data.get("columns", []), data.get("rows", []))
        follow_ups = [q for q in SUGGESTED_QUESTIONS if q != question][:3]
        return json.dumps({"insight": insight, "follow_ups": follow_ups})
