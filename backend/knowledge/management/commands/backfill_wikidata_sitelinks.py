import requests
from django.core.management.base import BaseCommand, CommandError

from knowledge.models import ExternalIdentifier
from knowledge.wikidata import fetch_wikipedia_sitelinks, store_wikipedia_sitelinks


class Command(BaseCommand):
    help = "Ergänzt bestätigte Wikipedia-Sitelinks zu bereits importierten Wikidata-Objekten."

    def add_arguments(self, parser):
        parser.add_argument("--qid", action="append", dest="qids")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--batch-size", type=int, default=50)

    def handle(self, *args, **options):
        queryset = ExternalIdentifier.objects.filter(provider="wikidata").select_related("entity").order_by("id")
        if options["qids"]:
            queryset = queryset.filter(external_id__in=options["qids"])
        identifiers = list(queryset[: options["limit"]] if options["limit"] > 0 else queryset)
        if not identifiers:
            self.stdout.write(self.style.WARNING("Keine passenden Wikidata-Objekte gefunden."))
            return

        by_qid = {item.external_id: item for item in identifiers}
        batch_size = max(1, min(int(options["batch_size"]), 50))
        stored = 0
        processed = 0
        for offset in range(0, len(by_qid), batch_size):
            qids = list(by_qid)[offset : offset + batch_size]
            try:
                entities = fetch_wikipedia_sitelinks(qids)
            except requests.RequestException as error:
                raise CommandError(f"Wikidata-Sitelinks konnten nicht geladen werden: {error}") from error

            for qid in qids:
                item = by_qid[qid]
                stored += store_wikipedia_sitelinks(
                    item.entity,
                    qid,
                    entities.get(qid, {}),
                )
                processed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"{processed} Wikidata-Objekte geprüft; {stored} bestätigte Wikipedia-Sitelinks ergänzt."
            )
        )
