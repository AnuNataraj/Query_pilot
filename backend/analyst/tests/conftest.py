from datetime import date

import pytest

from analyst.demo_data import build_warehouse
from analyst.knowledge_seed import SEED_DOCS
from analyst.models import KnowledgeDoc


@pytest.fixture(scope="session")
def warehouse_file(tmp_path_factory):
    """A small but complete warehouse, built once per test session."""
    path = tmp_path_factory.mktemp("data") / "warehouse.db"
    build_warehouse(path, today=date(2026, 11, 1), months=6, n_customers=150, base_daily_orders=4)
    return path


@pytest.fixture(autouse=True)
def test_settings(settings, warehouse_file):
    settings.WAREHOUSE_PATH = warehouse_file
    settings.LLM_PROVIDER = "demo"
    settings.EMBEDDINGS_BACKEND = "tfidf"
    settings.MAX_SQL_ATTEMPTS = 3
    settings.MAX_ROWS = 500
    settings.QUERY_TIMEOUT_S = 5
    return settings


@pytest.fixture
def knowledge(db):
    KnowledgeDoc.objects.bulk_create(KnowledgeDoc(**doc) for doc in SEED_DOCS)
    return KnowledgeDoc.objects.all()


class ScriptedLLM:
    """A fake LLM that returns pre-written replies, so tests are fast and deterministic."""

    provider = "fake"
    model = "scripted"
    label = "fake:scripted"

    def __init__(self, sql_replies, insight_reply='{"insight": "Looks good.", "follow_ups": ["a", "b"]}'):
        self.sql_replies = list(sql_replies)
        self.insight_reply = insight_reply
        self.calls = []

    def complete(self, system, messages, *, purpose=""):
        self.calls.append({"purpose": purpose, "messages": [dict(m) for m in messages]})
        if purpose == "insight":
            if isinstance(self.insight_reply, Exception):
                raise self.insight_reply
            return self.insight_reply
        return self.sql_replies.pop(0)
