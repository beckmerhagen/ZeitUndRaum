from django.core.management.base import BaseCommand

from knowledge.hanze import download_and_import_hanze, import_hanze_vector


class Command(BaseCommand):
    help = "Importiert historische europäische Hochwasser und Sturmfluten aus HANZE v2.1."

    def add_arguments(self, parser):
        parser.add_argument("--vector", help="Lokale HANZE-Shapefile statt Download verwenden")
        parser.add_argument("--limit", type=int, help="Nur die ersten N Ereignisse importieren")

    def handle(self, *args, **options):
        if options["vector"]:
            result = import_hanze_vector(options["vector"], limit=options["limit"], stdout=self.stdout)
        else:
            result = download_and_import_hanze(limit=options["limit"], stdout=self.stdout)
        self.stdout.write(
            self.style.SUCCESS(
                "HANZE-Import abgeschlossen: "
                f"{result['created']} neu, {result['updated']} aktualisiert, {result['skipped']} übersprungen."
            )
        )
