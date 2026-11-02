from rest_framework import serializers

from .models import KnowledgeDoc, QueryRun


class KnowledgeDocSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeDoc
        fields = ["id", "title", "kind", "content", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class QueryRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = QueryRun
        fields = ["id", "question", "sql", "status", "attempts", "row_count", "insight",
                  "error", "provider", "latency_ms", "created_at"]


class PreviousTurnSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=500)
    sql = serializers.CharField(max_length=5000, allow_blank=True, required=False, default="")


class QuestionSerializer(serializers.Serializer):
    """Just the question; used for the form on the browsable API page."""

    question = serializers.CharField(max_length=500, trim_whitespace=True)


class AskSerializer(QuestionSerializer):
    previous = PreviousTurnSerializer(required=False, allow_null=True)


class SqlSerializer(serializers.Serializer):
    sql = serializers.CharField(max_length=5000, trim_whitespace=True, style={"base_template": "textarea.html", "rows": 8})
