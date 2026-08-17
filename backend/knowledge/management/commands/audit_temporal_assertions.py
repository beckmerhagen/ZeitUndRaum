from django.core.management.base import BaseCommand

from knowledge.tasks import audit_imported_assertions


class Command(BaseCommand):
    help = "Prüft automatisch importierte Zeitangaben und verwirft oder korrigiert Fehlzuordnungen."

    def handle(self, *args, **options):
        result = audit_imported_assertions()
        self.stdout.write(
            self.style.SUCCESS(
                "Zeitangaben geprüft: "
                f"{result['corrected']} korrigiert, "
                f"{result['upgraded']} bestätigt, "
                f"{result['rejected']} verworfen."
            )
        )
