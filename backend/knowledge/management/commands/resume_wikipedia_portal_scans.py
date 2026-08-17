from django.core.management.base import BaseCommand

from knowledge.portal_recovery import recover_interrupted_portal_scans
from knowledge.tasks import scan_wikipedia_portal_batch


class Command(BaseCommand):
    help = "Setzt unterbrochene Wikipedia-Portal-Scans sicher zurück und nimmt den Kataloglauf wieder auf."

    def add_arguments(self, parser):
        parser.add_argument("--languages", nargs="+", default=["de", "en", "fr"])
        parser.add_argument("--batch-size", type=int, default=1)
        parser.add_argument("--article-limit", type=int, default=50)
        parser.add_argument(
            "--no-queue",
            action="store_true",
            help="Bereinigt nur die Zustände, ohne einen neuen Celery-Auftrag einzureihen.",
        )

    def handle(self, *args, **options):
        result = recover_interrupted_portal_scans(languages=options["languages"])
        self.stdout.write(
            self.style.SUCCESS(
                "Unterbrochene Portal-Scans bereinigt: "
                f"{result['recovered_portals']} Portale, {result['recovered_runs']} Läufe; "
                f"{result['resumable_portals']} Portale verbleiben."
            )
        )

        if options["no_queue"] or result["resumable_portals"] == 0:
            return

        task = scan_wikipedia_portal_batch.delay(
            languages=result["languages"],
            batch_size=max(1, min(int(options["batch_size"]), 3)),
            article_limit=max(20, min(int(options["article_limit"]), 250)),
        )
        self.stdout.write(self.style.SUCCESS(f"Portal-Scan wieder aufgenommen: {task.id}"))
