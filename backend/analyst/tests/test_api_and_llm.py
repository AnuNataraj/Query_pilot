import json

import pytest
import requests
from rest_framework.test import APIClient

from analyst.services import llm as llm_module


@pytest.fixture
def api():
    return APIClient()


def stream_events(response):
    return [json.loads(line) for line in b"".join(response.streaming_content).decode().splitlines()]


@pytest.mark.django_db
def test_health_reports_provider_and_data_range(api, knowledge):
    data = api.get("/api/health/").json()
    assert data["llm"]["provider"] == "demo" and data["warehouse_ready"]
    assert data["knowledge_docs"] == knowledge.count()
    assert len(data["suggestions"]) == 6


@pytest.mark.django_db
def test_ask_streams_ndjson_events(api, knowledge):
    response = api.post("/api/ask/", {"question": "How many active customers do we have?"}, format="json")
    assert response["Content-Type"] == "application/x-ndjson"
    events = stream_events(response)
    assert events[0] == {"type": "step", "id": "retrieve", "kind": "retrieve", "status": "running",
                         "label": "Search knowledge base", "ms": None, "detail": {}}
    assert events[-1]["type"] == "result" and events[-1]["chart"]["type"] == "kpi"
    assert api.get("/api/history/").json()[0]["status"] == "answered"


@pytest.mark.django_db
def test_rag_end_to_end_adding_a_definition_changes_the_answer(api, knowledge):
    question = {"question": "How many VIP customers do we have in each region?"}
    before = stream_events(api.post("/api/ask/", question, format="json"))[-1]
    assert before["status"] == "unanswerable"

    api.post("/api/knowledge/", {"title": "VIP customer", "kind": "glossary",
                                 "content": "A VIP customer has lifetime revenue of at least $10,000."}, format="json")
    after = stream_events(api.post("/api/ask/", question, format="json"))[-1]
    assert after["status"] == "answered"
    assert ">= 10000" in after["sql"]
    assert after["context"][0]["title"] == "VIP customer"


def test_ask_validates_input(api):
    assert api.post("/api/ask/", {"question": ""}, format="json").status_code == 400


@pytest.mark.django_db
def test_run_sql_endpoint_uses_the_same_guard(api):
    ok = api.post("/api/sql/run/", {"sql": "SELECT COUNT(*) AS n FROM products"}, format="json")
    assert ok.status_code == 200 and ok.json()["rows"] == [[44]]
    blocked = api.post("/api/sql/run/", {"sql": "DROP TABLE products"}, format="json")
    assert blocked.status_code == 400 and blocked.json()["blocked"] is True
    broken = api.post("/api/sql/run/", {"sql": "SELECT nope FROM products"}, format="json")
    assert broken.status_code == 400 and "no such column" in broken.json()["error"]


def test_explain_endpoint(api):
    data = api.post("/api/sql/explain/", {"sql": "SELECT * FROM orders WHERE customer_id = 7"}, format="json").json()
    assert any("idx_orders_customer" in step["detail"] for step in data["plan"])


@pytest.mark.django_db
def test_knowledge_crud(api, knowledge):
    created = api.post("/api/knowledge/", {"title": "Churn", "kind": "glossary", "content": "x"}, format="json").json()
    assert api.patch(f"/api/knowledge/{created['id']}/", {"content": "y"}, format="json").json()["content"] == "y"
    assert api.delete(f"/api/knowledge/{created['id']}/").status_code == 204
    assert api.post("/api/knowledge/", {"title": "Bad", "kind": "nope", "content": "x"}, format="json").status_code == 400


# ---- LLM HTTP client ---------------------------------------------------------------

class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.text = json.dumps(body)

    def json(self):
        return self._body


def test_post_json_retries_rate_limits_then_succeeds(monkeypatch):
    responses = [FakeResponse(429, {}, {"Retry-After": "0"}), FakeResponse(503, {}), FakeResponse(200, {"ok": 1})]
    monkeypatch.setattr(llm_module.requests, "post", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(llm_module.time, "sleep", lambda s: None)
    assert llm_module.post_json("https://x", {}, headers={}, timeout=1) == {"ok": 1}


def test_post_json_does_not_retry_bad_api_key(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_module.requests, "post", lambda *a, **k: calls.append(1) or FakeResponse(401, {}))
    with pytest.raises(llm_module.LLMError, match="API key"):
        llm_module.post_json("https://x", {}, headers={}, timeout=1)
    assert len(calls) == 1


def test_post_json_gives_up_on_network_errors(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(llm_module.requests, "post", boom)
    monkeypatch.setattr(llm_module.time, "sleep", lambda s: None)
    with pytest.raises(llm_module.LLMError, match="4 attempts"):
        llm_module.post_json("https://x", {}, headers={}, timeout=1)


def test_openai_and_anthropic_clients_parse_replies(monkeypatch):
    sent = []

    def fake_post(url, json, headers, timeout):
        sent.append((url, json, headers))
        if "anthropic" in url:
            return FakeResponse(200, {"content": [{"type": "text", "text": "hi from claude"}]})
        return FakeResponse(200, {"choices": [{"message": {"content": "hi from gpt"}}]})

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    gpt = llm_module.OpenAICompatibleClient("m", "key", "http://localhost:11434/v1/")
    claude = llm_module.AnthropicClient("c", "key")
    assert gpt.complete("sys", [{"role": "user", "content": "q"}]) == "hi from gpt"
    assert claude.complete("sys", [{"role": "user", "content": "q"}]) == "hi from claude"
    assert sent[0][0] == "http://localhost:11434/v1/chat/completions"
    assert sent[0][1]["messages"][0] == {"role": "system", "content": "sys"}
    assert sent[1][1]["system"] == "sys" and sent[1][2]["anthropic-version"] == "2023-06-01"


def test_get_llm_reports_misconfiguration(settings):
    settings.LLM_PROVIDER = "anthropic"
    settings.LLM_API_KEY = ""
    with pytest.raises(llm_module.LLMError, match="LLM_API_KEY"):
        llm_module.get_llm()
    settings.LLM_PROVIDER = "magic"
    assert llm_module.describe_provider()["ready"] is False
