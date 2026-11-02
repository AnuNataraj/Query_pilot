# Author: Anu
from django.db import models


class KnowledgeDoc(models.Model):
    """A piece of business knowledge the AI retrieves before writing SQL (RAG)."""

    class Kind(models.TextChoices):
        TABLE = "table", "Table guide"
        GLOSSARY = "glossary", "Business rule"
        EXAMPLE = "example", "Example query"

    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.GLOSSARY)
    content = models.TextField()
    # Cached embedding vector for the provider-embeddings backend. `embedding_key`
    # records which model + content produced it, so edits invalidate the cache.
    embedding = models.JSONField(null=True, blank=True)
    embedding_key = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "title"]

    def __str__(self) -> str:
        return f"[{self.kind}] {self.title}"

    @property
    def search_text(self) -> str:
        return f"{self.title}\n{self.content}"


class QueryRun(models.Model):
    """One question asked of the analyst, kept for history and auditing."""

    class Status(models.TextChoices):
        ANSWERED = "answered"
        UNANSWERABLE = "unanswerable"
        BLOCKED = "blocked"
        FAILED = "failed"

    question = models.TextField()
    sql = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices)
    attempts = models.PositiveSmallIntegerField(default=0)
    row_count = models.PositiveIntegerField(null=True, blank=True)
    insight = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")
    provider = models.CharField(max_length=100, blank=True, default="")
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.status}: {self.question[:60]}"
