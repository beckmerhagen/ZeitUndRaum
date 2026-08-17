from django.core.management.base import BaseCommand

from knowledge.noaa_earthquake import download_and_import_noaa_earthquakes


class Command(BaseCommand):
    help = "Importiert bedeutende historische Erdbeben aus der globalen NOAA/NCEI-Datenbank."

    def add_arguments(self, parser):
        parser.add_argument("--country", default="", help="Optional auf ein Land begrenzen, z. B. NEPAL")
        parser.add_argument("--limit", type=int, help="Optional nur die ersten N Ereignisse laden")

    def handle(self, *args, **options):
        result = download_and_import_noaa_earthquakes(
            country=options["country"],
            limit=options["limit"],
            stdout=self.stdout,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "NOAA-Erdbeben-Import abgeschlossen: "
                f"{result['created']} neu, {result['updated']} aktualisiert, "
                f"{result['skipped']} übersprungen; {result['events']} Ereignisse gelesen."
            )
        )
