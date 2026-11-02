from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=True)
router.register("knowledge", views.KnowledgeDocViewSet, basename="knowledge")

urlpatterns = [
    path("", views.ApiRootView.as_view(), name="api-root"),
    path("health/", views.HealthView.as_view()),
    path("schema/", views.SchemaView.as_view()),
    path("tables/<str:name>/", views.TablePreviewView.as_view()),
    path("ask/", views.AskView.as_view()),
    path("sql/run/", views.RunSqlView.as_view()),
    path("sql/explain/", views.ExplainSqlView.as_view()),
    path("history/", views.HistoryView.as_view()),
    *router.urls,
]
