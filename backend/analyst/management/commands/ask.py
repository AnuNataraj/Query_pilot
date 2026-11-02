"""Ask the AI analyst a question from the terminal, with no frontend.

    python manage.py ask What is the refund rate by sales channel?
    python manage.py ask "Who are our top 10 customers by lifetime revenue?" --rows 5
"""
from django.core.management.base import BaseCommand, CommandError

from analyst.services.pipeline import run_pipeline

MAX_CELL = 32


def format_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    text = str(value)
    return text if len(text) <= MAX_CELL else text[: MAX_CELL - 3] + "..."


def text_table(columns: list[str], rows: list[list]) -> str:
    """A plain-text table, numbers aligned right."""
    cells = [[format_cell(v) for v in row] for row in rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(columns)]
    numeric = [any(isinstance(r[i], (int, float)) for r in rows) for i in range(len(columns))]

    def line(values):
        parts = [v.rjust(w) if numeric[i] else v.ljust(w) for i, (v, w) in enumerate(zip(values, widths))]
        return "| " + " | ".join(parts) + " |"

    border = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    return "\n".join([border, line(columns), border, *(line(r) for r in cells), border])


class Command(BaseCommand):
    help = "Ask the AI analyst a question from the terminal and print each step, the SQL and the result."

    def add_arguments(self, parser):
        parser.add_argument("question", nargs="+", help="The question, with or without quotes.")
        parser.add_argument("--rows", type=int, default=15, help="How many result rows to print (default 15).")

    def handle(self, *args, **options):
        question = " ".join(options["question"]).strip()
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nQuestion: {question}\n"))

        for event in run_pipeline(question):
            if event["type"] == "step":
                if event["status"] != "running":
                    self.print_step(event)
            elif event["type"] == "result":
                self.print_result(event, options["rows"])
            else:
                raise CommandError(event["message"])

    def print_step(self, step):
        ok = step["status"] == "done"
        mark = self.style.SUCCESS("[ok]    ") if ok else self.style.ERROR("[failed]")
        ms = f" ({step['ms']} ms)" if step["ms"] is not None else ""
        self.stdout.write(f"{mark} {step['label']}{ms}")

        detail = step["detail"]
        for doc in detail.get("docs") or []:
            self.stdout.write(f"           - {doc['title']}  (score {doc['score']:.2f})")
        if detail.get("reasoning"):
            self.stdout.write(f"           {detail['reasoning']}")
        if detail.get("sql"):
            for sql_line in detail["sql"].splitlines():
                self.stdout.write(self.style.SQL_FIELD(f"           {sql_line}"))
        if step["kind"] == "execute" and ok:
            self.stdout.write(f"           {detail.get('rows', 0)} rows")
        if detail.get("error"):
            self.stdout.write(self.style.ERROR(f"           {detail['error']}"))

    def print_result(self, result, max_rows):
        self.stdout.write("")
        if result["status"] != "answered":
            self.stdout.write(self.style.WARNING(f"No answer ({result['status']}): {result['error']}"))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Answer"))
        self.stdout.write(result["insight"] + "\n")
        for assumption in result["assumptions"]:
            self.stdout.write(self.style.WARNING(f"Assumed: {assumption}"))

        rows = result["rows"]
        if rows:
            self.stdout.write(text_table(result["columns"], rows[:max_rows]))
            if len(rows) > max_rows:
                self.stdout.write(f"... {len(rows) - max_rows} more rows (use --rows to show more)")

        if result["follow_ups"]:
            self.stdout.write(self.style.MIGRATE_HEADING("\nYou could ask next"))
            for q in result["follow_ups"]:
                self.stdout.write(f"  - {q}")
        self.stdout.write(f"\nModel: {result['provider']}   Total time: {result['latency_ms']} ms\n")
