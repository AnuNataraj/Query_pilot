import pytest

from analyst.models import KnowledgeDoc
from analyst.services import charting, retriever


def test_tokenize_normalizes_plurals_and_drops_stopwords():
    assert retriever.tokenize("What are the categories of our customers?") == ["category", "customer"]


@pytest.mark.parametrize("question, expected_title", [
    ("What was revenue by fiscal quarter in FY2025?", "Fiscal calendar"),
    ("Which categories have the best gross margin?", "Gross margin"),
    ("How many active customers do we have?", "Active and churned customers"),
    ("refund rate by channel", "Refund rate"),
])
def test_search_ranks_the_relevant_rule_first(knowledge, question, expected_title):
    hits = retriever.search(question)
    assert hits[0].title.startswith(expected_title)
    assert hits == sorted(hits, key=lambda h: h.score, reverse=True)


def test_new_knowledge_is_searchable_immediately(knowledge):
    assert not any("VIP" in h.title for h in retriever.search("How many VIP customers?"))
    KnowledgeDoc.objects.create(title="VIP customer", kind="glossary",
                                content="A VIP customer has lifetime revenue of at least $10,000.")
    assert retriever.search("How many VIP customers?")[0].title == "VIP customer"


def test_provider_embeddings_are_cached_per_content(knowledge, settings, monkeypatch):
    settings.EMBEDDINGS_BACKEND = "openai"
    calls = []

    def fake_embed(texts):
        calls.append(len(texts))
        return [[1.0 if "fiscal" in t.lower() else 0.1, 0.5] for t in texts]

    monkeypatch.setattr(retriever, "_embed_remote", fake_embed)
    retriever.search("fiscal quarter")
    retriever.search("fiscal quarter")
    assert calls == [knowledge.count(), 1, 1]  # docs embedded once, then only the query


def test_chart_line_for_time_series():
    rows = [[f"2026-{m:02d}", m * 100.0] for m in range(1, 10)]
    assert charting.suggest_chart(["month", "revenue"], rows) == {
        "type": "line", "label_column": "month", "value_columns": ["revenue"]}


def test_chart_bar_for_categories_and_ignores_id_columns():
    chart = charting.suggest_chart(["customer_id", "name", "revenue"], [[1, "A", 10.0], [2, "B", 5.0]])
    assert chart == {"type": "bar", "label_column": "name", "value_columns": ["revenue"]}


def test_chart_kpi_for_single_value():
    assert charting.suggest_chart(["active_customers"], [[522]])["type"] == "kpi"


def test_chart_none_for_text_only_results():
    assert charting.suggest_chart(["name", "email"], [["a", "b"], ["c", "d"]])["type"] == "none"


def test_describe_result_formats_money_and_percent():
    text = charting.describe_result(["channel", "refund_rate_pct"], [["mobile", 10.0], ["store", 3.0]])
    assert "mobile" in text and "10.0%" in text and "3.0%" in text
