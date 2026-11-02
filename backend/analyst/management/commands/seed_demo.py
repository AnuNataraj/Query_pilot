from django.conf import settings
from django.core.management.base import BaseCommand

from analyst.demo_data import build_warehouse
from analyst.knowledge_seed import SEED_DOCS
from analyst.models import KnowledgeDoc


class Command(BaseCommand):
    help = "Build the demo retail warehouse and load the starter knowledge base."

    def add_arguments(self, parser):
        parser.add_argument("--reset-knowledge", action="store_true",
                            help="Delete all knowledge-base entries and reload the starter set.")
        parser.add_argument("--seed", type=int, default=42, help="Random seed for the generated data.")

    def handle(self, *args, **options):
        counts = build_warehouse(settings.WAREHOUSE_PATH, seed=options["seed"])
        summary = ", ".join(f"{n:,} {table}" for table, n in counts.items())
        self.stdout.write(self.style.SUCCESS(f"Warehouse ready at {settings.WAREHOUSE_PATH}: {summary}"))

        if options["reset_knowledge"]:
            KnowledgeDoc.objects.all().delete()
        if KnowledgeDoc.objects.exists():
            self.stdout.write("Knowledge base already has entries; kept them (use --reset-knowledge to reload).")
            return
        KnowledgeDoc.objects.bulk_create(KnowledgeDoc(**doc) for doc in SEED_DOCS)
        self.stdout.write(self.style.SUCCESS(f"Loaded {len(SEED_DOCS)} knowledge-base entries."))
