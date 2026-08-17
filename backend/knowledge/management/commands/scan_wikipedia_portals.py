from django.core.management.base import BaseCommand, CommandError

from knowledge.models import WikipediaPortal
from knowledge.portal_ingest import scan_portal


class Command(BaseCommand):
    help = "Scannt ausgewählte oder ausstehende Wikipedia-Portale."

    def add_arguments(self, parser):
        parser.add_argument("--languages", nargs="+", default=["de", "en", "fr"])
        parser.add_argument("--portal", action="append", dest="portals")
        parser.add_argument("--portal-limit", type=int, default=1)
        parser.add_argument("--article-limit", type=int, default=100)

    def handle(self, *args, **options):
        queryset = WikipediaPortal.objects.filter(language__in=options["languages"])
        if options["portals"]:
            queryset = queryset.filter(title__in=options["portals"])
        else:
            queryset = queryset.filter(
                scan_status__in=[WikipediaPortal.ScanStatus.PENDING, WikipediaPortal.ScanStatus.PARTIAL]
            )
        portals = list(queryset.order_by("last_scanned_at", "language", "title")[: options["portal_limit"]])
        if not portals:
            raise CommandError("Keine passenden Portale im Katalog gefunden.")
        for portal in portals:
            result = scan_portal(portal, article_limit=options["article_limit"])
            self.stdout.write(self.style.SUCCESS(str(result)))
