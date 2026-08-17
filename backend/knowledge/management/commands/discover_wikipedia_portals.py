from django.core.management.base import BaseCommand

from knowledge.portal_ingest import discover_portals
from knowledge.tasks import scan_wikipedia_portal_batch


class Command(BaseCommand):
    help = "Erstellt den paginierten Katalog der Wikipedia-Portale."

    def add_arguments(self, parser):
        parser.add_argument("--languages", nargs="+", default=["de", "en", "fr"])
        parser.add_argument("--limit-per-language", type=int)
        parser.add_argument("--queue-scan", action="store_true")
        parser.add_argument("--article-limit", type=int, default=50)

    def handle(self, *args, **options):
        languages = list(dict.fromkeys(language.casefold() for language in options["languages"]))
        result = discover_portals(languages, limit_per_language=options["limit_per_language"])
        self.stdout.write(self.style.SUCCESS(str(result)))
        if options["queue_scan"]:
            task = scan_wikipedia_portal_batch.delay(
                languages=languages,
                batch_size=1,
                article_limit=options["article_limit"],
            )
            self.stdout.write(self.style.SUCCESS(f"Portal-Scan vorgemerkt: {task.id}"))
