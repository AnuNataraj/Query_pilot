from django.contrib import admin

from .models import KnowledgeDoc, QueryRun


@admin.register(KnowledgeDoc)
class KnowledgeDocAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "updated_at"]
    list_filter = ["kind"]
    search_fields = ["title", "content"]
    fields = ["title", "kind", "content"]


@admin.register(QueryRun)
class QueryRunAdmin(admin.ModelAdmin):
    """Read-only log of every question asked."""

    list_display = ["question", "status", "attempts", "row_count", "latency_ms", "provider", "created_at"]
    list_filter = ["status", "provider"]
    search_fields = ["question", "sql"]
    readonly_fields = [f.name for f in QueryRun._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
