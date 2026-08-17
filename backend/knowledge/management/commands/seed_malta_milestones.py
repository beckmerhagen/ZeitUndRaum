import hashlib
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.utils import timezone

from knowledge.models import Assertion, Entity, Evidence, ExternalIdentifier, PlaceGeometry, Source


MALTA_CENTER = Point(14.4477, 35.8880, srid=4326)
GRAND_HARBOUR = Point(14.5183, 35.8919, srid=4326)


def stable_fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def entity_for_qid(qid, canonical_name, kind, labels):
    identifier = ExternalIdentifier.objects.select_related("entity").filter(
        provider="wikidata", external_id=qid
    ).first()
    if identifier:
        entity = identifier.entity
        entity.labels = {**entity.labels, **labels}
        entity.save(update_fields=["labels", "updated_at"])
        return entity
    entity = Entity.objects.create(canonical_name=canonical_name, kind=kind, labels=labels)
    ExternalIdentifier.objects.create(
        entity=entity,
        provider="wikidata",
        external_id=qid,
        url=f"https://www.wikidata.org/wiki/{qid}",
    )
    return entity


class Command(BaseCommand):
    help = "Legt zentrale, amtlich belegte Malta-Meilensteine idempotent an."

    def handle(self, *args, **options):
        malta = entity_for_qid(
            "Q233",
            "Malta",
            Entity.Kind.PLACE,
            {"de": "Malta", "en": "Malta", "fr": "Malte"},
        )
        PlaceGeometry.objects.update_or_create(
            entity=malta,
            label="Landesbezug Malta",
            defaults={
                "geometry": MALTA_CENTER,
                "spatial_precision_meters": 30000,
                "is_reconstruction": False,
            },
        )
        european_union = entity_for_qid(
            "Q458",
            "Europäische Union",
            Entity.Kind.ORGANIZATION,
            {"de": "Europäische Union", "en": "European Union", "fr": "Union européenne"},
        )
        great_siege = entity_for_qid(
            "Q58732",
            "Große Belagerung von Malta",
            Entity.Kind.EVENT,
            {"de": "Große Belagerung von Malta", "en": "Great Siege of Malta", "fr": "Grand Siège de Malte"},
        )
        freedom_day, _ = Entity.objects.get_or_create(
            canonical_name="Abzug der letzten britischen Streitkräfte aus Malta",
            kind=Entity.Kind.EVENT,
            defaults={
                "labels": {
                    "de": "Abzug der letzten britischen Streitkräfte aus Malta",
                    "en": "Withdrawal of the last British forces from Malta",
                    "fr": "Départ des dernières forces britanniques de Malte",
                }
            },
        )

        sources = {
            "siege": Source.objects.update_or_create(
                provider="Government of Malta – Directorate for Learning and Assessment Programmes",
                record_id="history-year-9-great-siege-1565",
                url="https://curriculum.gov.mt/wp-content/uploads/2024/09/Yr-9-History-Gen-Notes-in-English-for-SEC-Starting-Sep-2021.pdf",
                defaults={
                    "title": "History for Year 9 – The Great Siege of 1565",
                    "source_type": Source.Type.INSTITUTION,
                    "language": "en",
                    "license_name": "© Government of Malta – Rechte und Wiederverwendung siehe Quelle",
                    "publisher": "Government of Malta",
                    "retrieved_at": timezone.now(),
                },
            )[0],
            "freedom": Source.objects.update_or_create(
                provider="Government of Malta – Department of Information",
                record_id="PR230470en",
                url="https://www.gov.mt/en/Government/DOI/Press%20Releases/Pages/2023/03/30/PR230470en.aspx",
                defaults={
                    "title": "Freedom Day – Friday, 31st March 2023",
                    "source_type": Source.Type.INSTITUTION,
                    "language": "en",
                    "license_name": "© Government of Malta – Rechte und Wiederverwendung siehe Quelle",
                    "publisher": "Government of Malta",
                    "retrieved_at": timezone.now(),
                },
            )[0],
            "eu": Source.objects.update_or_create(
                provider="European Commission – Representation in Malta",
                record_id="malta-in-the-eu",
                url="https://malta.representation.ec.europa.eu/about-us/malta-eu_en",
                defaults={
                    "title": "Malta in the EU",
                    "source_type": Source.Type.INSTITUTION,
                    "language": "en",
                    "license_name": "© European Union – Wiederverwendung gemäß Kommissionsbeschluss 2011/833/EU",
                    "license_url": "https://commission.europa.eu/legal-notice_en",
                    "publisher": "European Commission",
                    "retrieved_at": timezone.now(),
                },
            )[0],
        }

        milestones = [
            {
                "key": "malta-great-siege-1565",
                "subject": great_siege,
                "predicate": "military-event",
                "value_text": "Die Große Belagerung von Malta begann am 18. Mai 1565 und endete am 8. September 1565 mit dem Scheitern der osmanischen Eroberung.",
                "start": (1565, 5, 18),
                "end": (1565, 9, 8),
                "calendar": Assertion.CalendarModel.JULIAN,
                "location": GRAND_HARBOUR,
                "precision_m": 15000,
                "source": sources["siege"],
                "locator": "Abschnitt „The Great Siege of 1565“; Beginn am 18. Mai 1565 und Ende im September 1565.",
                "excerpt": "Amtliche maltesische Unterrichtsunterlage zur Großen Belagerung von 1565.",
                "confidence": Decimal("0.95"),
                "reason": "Der Zeitraum und der Schauplatz werden in einer amtlichen maltesischen Geschichtsunterlage behandelt.",
            },
            {
                "key": "malta-british-forces-left-1979",
                "subject": freedom_day,
                "predicate": "military-presence-ended",
                "value_text": "Am 31. März 1979 verließen die letzten britischen Schiffe Malta; die Insel wurde nicht länger als britischer Militärstützpunkt genutzt.",
                "start": (1979, 3, 31),
                "end": (1979, 3, 31),
                "calendar": Assertion.CalendarModel.GREGORIAN,
                "location": GRAND_HARBOUR,
                "precision_m": 10000,
                "source": sources["freedom"],
                "locator": "Haupttext des Government-of-Malta-Pressereleases PR230470en.",
                "excerpt": "Der Freedom Day erinnert an den Abzug der letzten britischen Schiffe am 31. März 1979.",
                "confidence": Decimal("0.99"),
                "reason": "Das Datum und das Ende der Nutzung als britischer Militärstützpunkt werden von der Regierung Maltas ausdrücklich genannt.",
            },
            {
                "key": "malta-eu-accession-2004",
                "subject": malta,
                "object_entity": european_union,
                "predicate": "joined-organization",
                "value_text": "Malta trat am 1. Mai 2004 der Europäischen Union bei.",
                "start": (2004, 5, 1),
                "end": (2004, 5, 1),
                "calendar": Assertion.CalendarModel.GREGORIAN,
                "location": MALTA_CENTER,
                "precision_m": 30000,
                "source": sources["eu"],
                "locator": "Abschnitt „Joining the European Union“.",
                "excerpt": "Malta joined the EU on 1 May 2004.",
                "confidence": Decimal("0.99"),
                "reason": "Das Beitrittsdatum wird von der Vertretung der Europäischen Kommission in Malta bestätigt.",
            },
        ]

        for item in milestones:
            start_year, start_month, start_day = item["start"]
            end_year, end_month, end_day = item["end"]
            assertion, _ = Assertion.objects.update_or_create(
                fingerprint=stable_fingerprint(item["key"]),
                defaults={
                    "subject": item["subject"],
                    "object_entity": item.get("object_entity"),
                    "predicate": item["predicate"],
                    "value_text": item["value_text"],
                    "time_start_year": start_year,
                    "time_start_month": start_month,
                    "time_start_day": start_day,
                    "time_end_year": end_year,
                    "time_end_month": end_month,
                    "time_end_day": end_day,
                    "time_precision": Assertion.Precision.DAY,
                    "temporal_scope": Assertion.TemporalScope.BOUNDED,
                    "calendar_model": item["calendar"],
                    "location": item["location"],
                    "location_entity": malta,
                    "spatial_scope": Assertion.SpatialScope.REGION,
                    "spatial_precision_meters": item["precision_m"],
                    "status": Assertion.Status.VERIFIED,
                    "knowledge_type": Assertion.KnowledgeType.DOCUMENTED,
                    "confidence": item["confidence"],
                    "confidence_reason": item["reason"],
                    "extraction_method": "curated-official-source-v1",
                },
            )
            Evidence.objects.update_or_create(
                assertion=assertion,
                source=item["source"],
                relation=Evidence.Relation.SUPPORTS,
                defaults={
                    "locator": item["locator"],
                    "excerpt": item["excerpt"],
                    "confidence": item["confidence"],
                },
            )

        self.stdout.write(self.style.SUCCESS("3 belegte Malta-Meilensteine sind vorhanden."))
