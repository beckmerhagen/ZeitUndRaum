from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from knowledge.models import Assertion, Evidence, Source


class Command(BaseCommand):
    help = "Prüft den Aussagenbestand auf Pflichtwert, Zeit/Raum, Provenienz und Begründung."

    def add_arguments(self, parser):
        parser.add_argument(
            "--report-only",
            action="store_true",
            help="Mängel nur ausgeben und den Prozess nicht fehlschlagen lassen.",
        )

    def handle(self, *args, **options):
        checks = {
            "Aussage ohne Wert": Assertion.objects.filter(
                object_entity__isnull=True,
                value_text="",
                value_number__isnull=True,
            ).count(),
            "Aussage mit leerer Vertrauensbegründung": Assertion.objects.filter(
                Q(confidence_reason="") | Q(confidence_reason__isnull=True)
            ).count(),
            "Begrenzte Aussage ohne vollständigen Zeitraum": Assertion.objects.filter(
                temporal_scope=Assertion.TemporalScope.BOUNDED
            ).filter(Q(time_start_year__isnull=True) | Q(time_end_year__isnull=True)).count(),
            "Punktgenaue Aussage ohne Koordinaten": Assertion.objects.filter(
                spatial_scope=Assertion.SpatialScope.POINT,
                location__isnull=True,
            ).count(),
            "Aussage ohne Evidenz": Assertion.objects.filter(evidence__isnull=True).count(),
            "Evidenz ohne Fundstelle": Evidence.objects.filter(Q(locator="") | Q(locator__isnull=True)).count(),
            "Quelle ohne Lizenz": Source.objects.filter(Q(license_name="") | Q(license_name__isnull=True)).count(),
            "Quelle ohne Abrufdatum": Source.objects.filter(retrieved_at__isnull=True).count(),
        }
        total_issues = sum(checks.values())
        self.stdout.write(f"Aussagen geprüft: {Assertion.objects.count()}")
        for label, count in checks.items():
            self.stdout.write(f"{label}: {count}")
        if total_issues:
            message = f"Integritätsprüfung fehlgeschlagen: {total_issues} Pflichtangaben fehlen."
            if options["report_only"]:
                self.stdout.write(self.style.WARNING(message))
                return
            raise CommandError(message)
        self.stdout.write(self.style.SUCCESS("Integritätsprüfung bestanden."))
