import hashlib
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.utils import timezone

from knowledge.models import Assertion, Entity, Evidence, ExternalIdentifier, PlaceGeometry, Source


def make_fingerprint(*parts):
    return hashlib.sha256("|".join(str(part).lower() for part in parts).encode()).hexdigest()


class Command(BaseCommand):
    help = "Legt einen kleinen, belegten Krempe-Demobestand an."

    def handle(self, *args, **options):
        center = Point(9.489, 53.836, srid=4326)
        krempe, _ = Entity.objects.get_or_create(
            canonical_name="Krempe",
            kind=Entity.Kind.PLACE,
            defaults={
                "labels": {"de": "Krempe", "en": "Krempe"},
                "descriptions": {"de": "Stadt im Kreis Steinburg in Schleswig-Holstein"},
            },
        )
        church, _ = Entity.objects.get_or_create(
            canonical_name="Kremper Kirche St. Peter",
            kind=Entity.Kind.BUILDING,
            defaults={"labels": {"de": "Kremper Kirche St. Peter"}},
        )
        town_hall, _ = Entity.objects.get_or_create(
            canonical_name="Kremper Rathaus",
            kind=Entity.Kind.BUILDING,
            defaults={"labels": {"de": "Kremper Rathaus"}},
        )

        ExternalIdentifier.objects.get_or_create(
            entity=krempe,
            provider="wikipedia-de",
            external_id="Krempe_(Steinburg)",
            defaults={"url": "https://de.wikipedia.org/wiki/Krempe_(Steinburg)"},
        )
        for entity in (krempe, church, town_hall):
            PlaceGeometry.objects.get_or_create(
                entity=entity,
                geometry=center,
                valid_from_year=None,
                valid_to_year=None,
                defaults={"spatial_precision_meters": 1000, "label": "Krempe (ungefähre Lage)"},
            )

        now = timezone.now()
        city_source, _ = Source.objects.update_or_create(
            provider="Stadt Krempe",
            record_id="tourismus",
            url="https://www.krempe.de/seite/502234/tourismus.html",
            defaults={
                "title": "Tourismus in Krempe",
                "source_type": Source.Type.INSTITUTION,
                "language": "de",
                "license_name": "Rechte beim Herausgeber; nur Verweis und Paraphrase gespeichert",
                "publisher": "Stadt Krempe",
                "retrieved_at": now,
            },
        )
        wiki_source, _ = Source.objects.update_or_create(
            provider="Wikipedia (de)",
            record_id="Krempe_(Steinburg)",
            url="https://de.wikipedia.org/wiki/Krempe_(Steinburg)",
            defaults={
                "title": "Krempe (Steinburg)",
                "source_type": Source.Type.ENCYCLOPEDIA,
                "language": "de",
                "license_name": "CC BY-SA – siehe Artikelseite",
                "license_url": "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use/de",
                "publisher": "Wikipedia community",
                "retrieved_at": now,
            },
        )
        fortress_source, _ = Source.objects.update_or_create(
            provider="Arbeitskreis Geschichte im Amt Breitenburg",
            record_id="festung-krempe-30jaehriger-krieg",
            url="https://www.steinburger-geschichte.de/themen/daenische-verwaltung/die-festung-krempe-im-30-jaehrigen-krieg",
            defaults={
                "title": "Die Festung Krempe im Dreißigjährigen Krieg",
                "source_type": Source.Type.INSTITUTION,
                "language": "de",
                "license_name": "Rechte beim Herausgeber; nur Verweis und Paraphrase gespeichert",
                "publisher": "Arbeitskreis Geschichte im Amt Breitenburg",
                "retrieved_at": now,
            },
        )

        claims = [
            (church, "first-mentioned", "Die Kirche ist erstmals 1239 erwähnt.", 1239, 1239, wiki_source, "Erste Erwähnung", "0.82"),
            (church, "tower-built", "Die Kirche erhielt 1506 einen neuen Turm.", 1506, 1506, wiki_source, "Neuer Kirchturm", "0.78"),
            (church, "tower-destroyed", "Der Turm fiel 1648 während eines Sturms.", 1648, 1648, wiki_source, "Sturmschaden", "0.78"),
            (church, "building-destroyed", "Der Nachfolgebau brannte 1814 aus.", 1814, 1814, wiki_source, "Kirchenbrand", "0.78"),
            (church, "constructed", "Die heutige Kirche wurde zwischen 1828 und 1832 neu errichtet.", 1828, 1832, city_source, "Neubau der heutigen Kirche", "0.90"),
            (town_hall, "constructed", "Das Kremper Rathaus wurde 1570 errichtet.", 1570, 1570, city_source, "Bau des Rathauses", "0.90"),
            (krempe, "military-event", "Krempe war im Dreißigjährigen Krieg eine umkämpfte Festung.", 1625, 1628, fortress_source, "Festung Krempe", "0.86"),
        ]

        for subject, predicate, text, start, end, source, locator, confidence in claims:
            assertion, _ = Assertion.objects.update_or_create(
                fingerprint=make_fingerprint(subject.id, predicate, text, start, end),
                defaults={
                    "subject": subject,
                    "predicate": predicate,
                    "value_text": text,
                    "time_start_year": start,
                    "time_end_year": end,
                    "time_precision": Assertion.Precision.YEAR if start == end else Assertion.Precision.RANGE,
                    "location": center,
                    "spatial_precision_meters": 1000,
                    "status": Assertion.Status.VERIFIED,
                    "confidence": Decimal(confidence),
                    "extraction_method": "curated-demo-v1",
                },
            )
            Evidence.objects.update_or_create(
                assertion=assertion,
                source=source,
                relation=Evidence.Relation.SUPPORTS,
                defaults={
                    "locator": locator,
                    "excerpt": text,
                    "confidence": Decimal(confidence),
                },
            )

        self.stdout.write(self.style.SUCCESS("Krempe-Demobestand ist bereit."))

