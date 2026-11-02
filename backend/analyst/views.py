import json
from urllib.parse import quote

from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import KnowledgeDoc, QueryRun
from .serializers import (
    AskSerializer, KnowledgeDocSerializer, QueryRunSerializer, QuestionSerializer, SqlSerializer,
)
from .services import charting, sql_guard, warehouse
from .services.demo_llm import SUGGESTED_QUESTIONS
from .services.llm import describe_provider
from .services.pipeline import run_pipeline


class ApiRootView(APIView):
    """
    QueryPilot API. Open any link below in the browser to try it.

    The "ask" link runs a sample question. Change the text after ?q= to ask your own.
    """

    def get(self, request):
        def url(path):
            return request.build_absolute_uri(path)

        tables = {}
        if warehouse.is_ready():
            tables = {t["name"]: url(f"/api/tables/{t['name']}/") for t in warehouse.describe()["tables"]}
        sample = SUGGESTED_QUESTIONS[3]
        return Response({
            "ask": url(f"/api/ask/?q={quote(sample)}"),
            "health": url("/api/health/"),
            "schema": url("/api/schema/"),
            "tables": tables,
            "knowledge": url("/api/knowledge/"),
            "history": url("/api/history/"),
            "run_sql": url("/api/sql/run/"),
            "explain_sql": url("/api/sql/explain/"),
            "admin": url("/admin/"),
        })


class HealthView(APIView):
    """Which LLM is connected, the date range of the data and the sample questions."""

    def get(self, request):
        ready = warehouse.is_ready()
        info = warehouse.describe() if ready else {}
        return Response({
            "llm": describe_provider(),
            "embeddings": settings.EMBEDDINGS_BACKEND,
            "warehouse_ready": ready,
            "data_from": info.get("data_from"),
            "data_to": info.get("data_to"),
            "knowledge_docs": KnowledgeDoc.objects.count(),
            "suggestions": SUGGESTED_QUESTIONS,
        })


class SchemaView(APIView):
    """Tables and columns in the warehouse, with row counts."""

    def get(self, request):
        try:
            return Response(warehouse.describe())
        except warehouse.WarehouseNotReady as exc:
            return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class TablePreviewView(APIView):
    """The first rows of a warehouse table. Add ?limit=50 to see more (up to 500)."""

    def get(self, request, name):
        try:
            names = [t["name"] for t in warehouse.describe()["tables"]]
        except warehouse.WarehouseNotReady as exc:
            return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if name not in names:  # whitelist: the name goes into SQL
            return Response({"error": f"Unknown table '{name}'. Tables: {', '.join(names)}"},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            limit = max(1, min(int(request.query_params.get("limit", 20)), settings.MAX_ROWS))
        except ValueError:
            limit = 20
        result = warehouse.execute(f'SELECT * FROM "{name}" LIMIT {limit}')
        return Response({
            "table": name,
            "showing": result.row_count,
            "rows": [dict(zip(result.columns, row)) for row in result.rows],
        })


class AskView(APIView):
    """
    Ask the AI analyst a question.

    In the browser: add ?q=your question to the URL, or use the form at the bottom of this page.

    From code: POST {"question": "..."}. The response streams one JSON event per line as each
    step finishes. Add ?stream=false to get a single JSON response instead.
    """

    def get_serializer(self, *args, **kwargs):  # draws the form on the browsable API page
        return QuestionSerializer(*args, **kwargs)

    def get(self, request):
        question = request.query_params.get("q", "").strip()
        if not question:
            return Response(
                {"detail": "Add ?q=your question to the URL, e.g. /api/ask/?q=How many active customers do we have?"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = AskSerializer(data={"question": question})
        serializer.is_valid(raise_exception=True)
        return self.collect(serializer.validated_data)

    def post(self, request):
        serializer = AskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        stream = request.query_params.get("stream", "true").lower() not in ("false", "0", "no")
        if not stream or request.accepted_renderer.format == "api":
            return self.collect(data)

        events = run_pipeline(data["question"], data.get("previous"))
        response = StreamingHttpResponse(
            (json.dumps(event, default=str) + "\n" for event in events),
            content_type="application/x-ndjson",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    @staticmethod
    def collect(data):
        """Run the whole pipeline, then return one response with the result and every step."""
        steps = {}
        for event in run_pipeline(data["question"], data.get("previous")):
            kind = event.pop("type")
            if kind == "step":
                steps[event["id"]] = event  # the "done" event replaces the "running" one
            elif kind == "result":
                return Response({**event, "steps": list(steps.values())})
            else:
                return Response({"error": event["message"], "steps": list(steps.values())},
                                status=status.HTTP_502_BAD_GATEWAY)
        return Response({"error": "The pipeline ended without a result."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class _GuardedSqlView(APIView):
    """Shared validation for SQL typed by a person: the same guard the AI's SQL goes through."""

    def get_serializer(self, *args, **kwargs):
        return SqlSerializer(*args, **kwargs)

    def guarded_sql(self, request):
        serializer = SqlSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return sql_guard.check_sql(serializer.validated_data["sql"])


class RunSqlView(_GuardedSqlView):
    """Run a read-only SQL query. POST {"sql": "SELECT ..."}. Anything except SELECT is blocked."""

    def post(self, request):
        guard = self.guarded_sql(request)
        if not guard.ok:
            return Response({"error": guard.reason, "blocked": True}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = warehouse.execute(guard.sql)
        except warehouse.WarehouseError as exc:
            return Response({"error": str(exc), "blocked": False}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            **result.as_dict(),
            "sql": guard.sql,
            "chart": charting.suggest_chart(result.columns, result.rows),
            "insight": charting.describe_result(result.columns, result.rows),
        })


class ExplainSqlView(_GuardedSqlView):
    """Show SQLite's query plan. SEARCH means an index is used; SCAN reads the whole table."""

    def post(self, request):
        guard = self.guarded_sql(request)
        if not guard.ok:
            return Response({"error": guard.reason, "blocked": True}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return Response({"plan": warehouse.explain(guard.sql)})
        except warehouse.WarehouseError as exc:
            return Response({"error": str(exc), "blocked": False}, status=status.HTTP_400_BAD_REQUEST)


class KnowledgeDocViewSet(viewsets.ModelViewSet):
    """Business rules, table guides and example queries the AI reads before writing SQL."""

    queryset = KnowledgeDoc.objects.all()
    serializer_class = KnowledgeDocSerializer


class HistoryView(APIView):
    """The last 30 questions asked, newest first."""

    def get(self, request):
        runs = QueryRun.objects.all()[:30]
        return Response(QueryRunSerializer(runs, many=True).data)
