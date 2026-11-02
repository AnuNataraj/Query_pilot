import json

import pytest

from analyst.models import QueryRun
from analyst.services import prompts
from analyst.services.llm import LLMError
from analyst.services.pipeline import run_pipeline

from .conftest import ScriptedLLM

GOOD_SQL = "SELECT region, COUNT(*) AS customers FROM customers GROUP BY region ORDER BY customers DESC"


def reply(sql, reasoning="Count by region.", assumptions=()):
    return json.dumps({"sql": sql, "reasoning": reasoning, "assumptions": list(assumptions)})


def run(llm, question="Customers by region?", previous=None):
    events = list(run_pipeline(question, previous=previous, llm=llm))
    return events, events[-1]


@pytest.mark.django_db
def test_happy_path_streams_every_step(knowledge):
    events, result = run(ScriptedLLM([reply(GOOD_SQL)]))
    kinds = [e["kind"] for e in events if e["type"] == "step" and e["status"] == "done"]
    assert kinds == ["retrieve", "generate", "guard", "execute", "insight"]
    assert result["status"] == "answered"
    assert result["columns"] == ["region", "customers"]
    assert result["chart"]["type"] == "bar"
    assert result["insight"] == "Looks good."
    assert QueryRun.objects.get().status == "answered"


@pytest.mark.django_db
def test_model_fixes_its_own_sql_after_a_database_error(knowledge):
    llm = ScriptedLLM([reply("SELECT regionn FROM customers"), reply(GOOD_SQL)])
    events, result = run(llm)
    errors = [e for e in events if e["type"] == "step" and e["status"] == "error"]
    assert errors[0]["kind"] == "execute" and "regionn" in errors[0]["detail"]["error"]
    assert result["status"] == "answered" and result["attempts"] == 2
    # The database error was fed back to the model on the second attempt.
    repair_msg = llm.calls[1]["messages"][-1]["content"]
    assert "no such column: regionn" in repair_msg


@pytest.mark.django_db
def test_gives_up_after_max_attempts(knowledge, settings):
    settings.MAX_SQL_ATTEMPTS = 2
    _, result = run(ScriptedLLM([reply("SELECT nope FROM customers")] * 2))
    assert result["status"] == "failed"
    assert "2 attempts" in result["error"]


@pytest.mark.django_db
def test_write_query_from_model_is_blocked_not_retried(knowledge):
    llm = ScriptedLLM([reply("DELETE FROM customers")])
    events, result = run(llm, "Delete all customers")
    assert result["status"] == "blocked"
    assert any(e.get("kind") == "guard" and e["status"] == "error" for e in events)
    assert len([c for c in llm.calls if c["purpose"] == "sql"]) == 1


@pytest.mark.django_db
def test_unanswerable_question_is_reported(knowledge):
    _, result = run(ScriptedLLM([reply(None, "We don't store weather data.")]), "Will it rain?")
    assert result["status"] == "unanswerable"
    assert "weather" in result["error"]


@pytest.mark.django_db
def test_insight_falls_back_when_llm_fails(knowledge):
    llm = ScriptedLLM([reply(GOOD_SQL)], insight_reply=LLMError("rate limited"))
    events, result = run(llm)
    assert result["status"] == "answered"
    assert "leads on customers" in result["insight"]
    assert events[-2]["detail"]["fallback"] is True


@pytest.mark.django_db
def test_follow_up_includes_previous_turn_in_prompt(knowledge):
    llm = ScriptedLLM([reply(GOOD_SQL)])
    run(llm, "Now by segment", previous={"question": "Customers by region?", "sql": GOOD_SQL})
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "PREVIOUS QUESTION" in prompt and GOOD_SQL in prompt


@pytest.mark.django_db
def test_llm_outage_ends_stream_with_error_event(knowledge):
    class DownLLM(ScriptedLLM):
        def complete(self, *args, **kwargs):
            raise LLMError("could not reach model")

    _, last = run(DownLLM([]))
    assert last == {"type": "error", "message": "could not reach model"}


def test_parse_sql_reply_handles_fences_and_plain_sql():
    fenced = '```json\n{"sql": "SELECT 1", "reasoning": "r", "assumptions": "a"}\n```'
    assert prompts.parse_sql_reply(fenced).sql == "SELECT 1"
    assert prompts.parse_sql_reply(fenced).assumptions == ["a"]
    assert prompts.parse_sql_reply("Here you go:\n```sql\nSELECT 2\n```").sql == "SELECT 2"
    assert prompts.parse_sql_reply('{"sql": null, "reasoning": "no"}').sql is None
    with pytest.raises(ValueError):
        prompts.parse_sql_reply("I am not sure.")
