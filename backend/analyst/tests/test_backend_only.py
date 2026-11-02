"""The ways to use the backend without the Angular frontend."""
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from analyst.management.commands.ask import text_table


@pytest.fixture
def api():
    return APIClient()


# ---- One JSON response instead of a stream ----------------------------------------

@pytest.mark.django_db
def test_ask_with_get_q_returns_one_json_response(api, knowledge):
    data = api.get("/api/ask/", {"q": "How many active customers do we have?"}).json()
    assert data["status"] == "answered"
    assert data["columns"] == ["active_customers"]
    assert [s["kind"] for s in data["steps"]] == ["retrieve", "generate", "guard", "execute", "insight"]
    assert all(s["status"] == "done" for s in data["steps"])
    assert "type" not in data


def test_ask_get_without_question_explains_usage(api):
    response = api.get("/api/ask/")
    assert response.status_code == 400 and "?q=" in response.json()["detail"]


@pytest.mark.django_db
def test_ask_post_stream_false_returns_one_json_response(api, knowledge):
    response = api.post("/api/ask/?stream=false", {"question": "What is the refund rate by sales channel?"}, format="json")
    assert response["Content-Type"] == "application/json"
    assert response.json()["chart"]["type"] == "bar"


@pytest.mark.django_db
def test_ask_reports_llm_outage_as_502(api, knowledge, settings):
    settings.LLM_PROVIDER = "anthropic"
    settings.LLM_API_KEY = ""
    response = api.get("/api/ask/", {"q": "anything"})
    assert response.status_code == 502 and "LLM_API_KEY" in response.json()["error"]


# ---- Browsable API pages (what you see in a browser) ---------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize("url", ["/api/", "/api/health/", "/api/schema/", "/api/knowledge/",
                                 "/api/history/", "/api/tables/orders/", "/api/sql/run/"])
def test_pages_render_as_html_in_a_browser(api, knowledge, url):
    response = api.get(url, HTTP_ACCEPT="text/html")
    assert response.status_code in (200, 405)  # sql/run only allows POST but still shows its form
    assert b"<html" in response.content


@pytest.mark.django_db
def test_browser_form_post_to_ask_returns_html_not_a_stream(api, knowledge):
    response = api.post("/api/ask/", {"question": "How many active customers do we have?"}, HTTP_ACCEPT="text/html")
    assert response.status_code == 200
    assert b"active_customers" in response.content


def test_root_redirects_to_api(api):
    assert api.get("/")["Location"] == "/api/"


def test_api_root_links_every_table(api):
    data = api.get("/api/").json()
    assert set(data["tables"]) == {"customers", "products", "orders", "order_items"}
    assert "/api/ask/?q=" in data["ask"]


# ---- Table preview ------------------------------------------------------------------

def test_table_preview_returns_rows_as_objects(api):
    data = api.get("/api/tables/products/", {"limit": 3}).json()
    assert data["showing"] == 3
    assert set(data["rows"][0]) == {"product_id", "name", "category", "unit_price", "unit_cost"}


def test_table_preview_rejects_unknown_names(api):
    response = api.get('/api/tables/orders"; DROP TABLE orders; --/')
    assert response.status_code == 404


def test_table_preview_caps_limit(api, settings):
    settings.MAX_ROWS = 5
    assert api.get("/api/tables/orders/", {"limit": 9999}).json()["showing"] == 5
    assert api.get("/api/tables/orders/", {"limit": "abc"}).json()["showing"] == 5


# ---- Django admin -------------------------------------------------------------------

@pytest.mark.django_db
def test_admin_lists_knowledge_and_history(knowledge):
    User.objects.create_superuser("admin", "admin@example.com", "pass12345")
    client = APIClient()
    client.login(username="admin", password="pass12345")
    assert client.get("/admin/analyst/knowledgedoc/").status_code == 200
    assert client.get("/admin/analyst/queryrun/").status_code == 200
    assert client.get("/admin/analyst/queryrun/add/").status_code == 403  # history is read-only


# ---- Terminal command ---------------------------------------------------------------

@pytest.mark.django_db
def test_ask_command_prints_steps_sql_and_table(knowledge):
    out = StringIO()
    call_command("ask", "What", "is", "the", "refund", "rate", "by", "sales", "channel?", stdout=out, no_color=True)
    text = out.getvalue()
    assert "[ok]     Search knowledge base" in text
    assert "SELECT channel" in text
    assert "| mobile" in text and "refund_rate_pct" in text
    assert "Model: demo:offline-demo" in text


@pytest.mark.django_db
def test_ask_command_reports_unanswerable(knowledge):
    out = StringIO()
    call_command("ask", "How many VIP customers do we have?", stdout=out, no_color=True)
    assert "No answer (unanswerable)" in out.getvalue()


@pytest.mark.django_db
def test_ask_command_fails_cleanly_when_llm_missing(knowledge, settings):
    settings.LLM_PROVIDER = "nope"
    with pytest.raises(CommandError, match="Unknown LLM_PROVIDER"):
        call_command("ask", "anything", stdout=StringIO())


def test_text_table_aligns_numbers_right():
    table = text_table(["name", "n"], [["a", 5], ["bbb", 1234]])
    assert "| a    |     5 |" in table
    assert "| bbb  | 1,234 |" in table
