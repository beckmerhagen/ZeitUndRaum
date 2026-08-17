from django.core.management.base import BaseCommand

from knowledge.noaa_tsunami import download_and_import_noaa_tsunamis


class Command(BaseCommand):
    help = "Importiert belegte Tsunami-Beobachtungsorte aus der globalen NOAA/NCEI-Datenbank."

    def add_arguments(self, parser):
        parser.add_argument("--country", default="", help="Optional auf ein Land begrenzen, z. B. THAILAND")
        parser.add_argument("--limit", type=int, help="Optional nur die ersten N Beobachtungen laden")

    def handle(self, *args, **options):
        result = download_and_import_noaa_tsunamis(
            country=options["country"],
            limit=options["limit"],
            stdout=self.stdout,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "NOAA-Tsunami-Import abgeschlossen: "
                f"{result['created']} neu, {result['updated']} aktualisiert, "
                f"{result['skipped']} übersprungen; {result['observations']} Beobachtungen gelesen."
            )
        )
