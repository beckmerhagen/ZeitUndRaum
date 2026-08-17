"""Nachvollziehbare Wikipedia-Portal-Recherche mit Artikel-Evidenz."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import PortalArticle, PortalScanRun, WikipediaPortal
from .tasks import ingest_page, resolve_entity
from .wikimedia import (
    wikipedia_article_pages,
    wikipedia_page_url,
    wikipedia_portal_links,
    wikipedia_portal_pages,
)


def discover_portals(languages=("de", "en", "fr"), *, limit_per_language=None):
    counts = {}
    for language in languages:
        count = 0
        for page in wikipedia_portal_pages(language, limit=limit_per_language):
            portal, created = WikipediaPortal.objects.get_or_create(
                language=language,
                title=page["title"],
                defaults={
                    "url": page.get("fullurl") or wikipedia_page_url(language, page["title"]),
                    "page_id": page.get("pageid"),
                    "metadata": {"discovery": "wikipedia-curated-portal-directory-v1"},
                },
            )
            if not created:
                portal.url = page.get("fullurl") or wikipedia_page_url(language, page["title"])
                portal.page_id = page.get("pageid") or portal.page_id
                portal.metadata = {
                    **portal.metadata,
                    "discovery": "wikipedia-curated-portal-directory-v1",
                }
                portal.save(update_fields=["url", "page_id", "metadata", "updated_at"])
            count += int(created)
        counts[language] = {
            "new": count,
            "total": WikipediaPortal.objects.filter(language=language).count(),
        }
    return counts


def resolve_portal_subject(portal):
    if portal.subject_entity_id:
        return portal.subject_entity
    topic = portal.title.split(":", 1)[-1].strip()
    if not topic:
        return None
    pages = wikipedia_article_pages(portal.language, [topic])
    if not pages:
        return None
    page = min(pages, key=lambda item: 0 if item.get("title", "").casefold() == topic.casefold() else 1)
    entity = resolve_entity(page, portal.language)
    portal.subject_entity = entity
    portal.save(update_fields=["subject_entity", "updated_at"])
    return entity


def scan_portal(portal, *, article_limit=250, max_assertions_per_article=24):
    """Scannt ein Portal; Verknüpfung ist Entdeckung, Artikel bleibt Evidenz."""

    portal.scan_status = WikipediaPortal.ScanStatus.RUNNING
    portal.last_error = ""
    portal.save(update_fields=["scan_status", "last_error", "updated_at"])
    run = PortalScanRun.objects.create(portal=portal)
    try:
        resolve_portal_subject(portal)
        payload = wikipedia_portal_links(
            portal.language,
            portal.title,
            limit=article_limit,
            continuation=portal.metadata.get("continuation", {}),
        )
        backlog = list(
            portal.articles.filter(active=True, source__isnull=True).order_by("position")[:20]
        )
        link_records = {article.title.casefold(): article for article in backlog}
        position_offset = portal.article_count
        for position, item in enumerate(payload["links"]):
            article, _ = PortalArticle.objects.update_or_create(
                portal=portal,
                title=item["title"],
                defaults={
                    "url": item.get("fullurl") or wikipedia_page_url(portal.language, item["title"]),
                    "position": position_offset + position,
                    "active": True,
                    "metadata": {
                        "discovered_via": portal.url,
                        "portal_revision_id": payload.get("revision_id"),
                        "relationship": "curated_portal_link",
                    },
                },
            )
            link_records[item["title"].casefold()] = article

        created_assertions = 0
        processed = 0
        article_titles = list(
            dict.fromkeys(
                [article.title for article in backlog]
                + [item["title"] for item in payload["links"]]
            )
        )
        pages = wikipedia_article_pages(portal.language, article_titles)
        for page in pages:
            page_title = page.get("title", "")
            if not page_title:
                continue
            article = link_records.get(page_title.casefold())
            if article is None:
                article, _ = PortalArticle.objects.update_or_create(
                    portal=portal,
                    title=page_title,
                    defaults={
                        "url": page.get("fullurl") or wikipedia_page_url(portal.language, page_title),
                        "page_id": page.get("pageid"),
                        "revision_id": page.get("lastrevid"),
                        "position": len(link_records),
                        "active": True,
                        "metadata": {
                            "discovered_via": portal.url,
                            "portal_revision_id": payload.get("revision_id"),
                            "relationship": "curated_portal_link_redirect",
                        },
                    },
                )
            with transaction.atomic():
                created_assertions += ingest_page(
                    page,
                    portal.language,
                    None,
                    max_assertions=max_assertions_per_article,
                    extraction_method="wikipedia-portal-article-v1",
                    locator_prefix=f"Über {portal.title} gefundener Artikelsatz zum Jahr",
                    coordinate_confidence=Decimal("0.56"),
                    portal_article=article,
                )
            processed += 1

        now = timezone.now()
        status = (
            WikipediaPortal.ScanStatus.COMPLETE
            if payload.get("complete")
            else WikipediaPortal.ScanStatus.PARTIAL
        )
        portal.revision_id = payload.get("revision_id")
        portal.scan_status = status
        portal.article_count = portal.articles.filter(active=True).count()
        portal.assertion_count = portal.articles.values("assertions").exclude(assertions=None).distinct().count()
        portal.last_scanned_at = now
        portal.last_error = ""
        portal.metadata = {
            **portal.metadata,
            "scan_method": "portal-links-to-article-assertions-v1",
            "complete_link_scan": bool(payload.get("complete")),
            "continuation": payload.get("continuation", {}),
        }
        portal.save(
            update_fields=[
                "revision_id",
                "scan_status",
                "article_count",
                "assertion_count",
                "last_scanned_at",
                "last_error",
                "metadata",
                "updated_at",
            ]
        )
        run.status = status
        run.portal_revision_id = portal.revision_id
        run.discovered_articles = len(payload["links"])
        run.processed_articles = processed
        run.discovered_assertions = created_assertions
        run.continuation = payload.get("continuation", {})
        run.completed_at = now
        run.save()
        return {
            "portal": portal.title,
            "language": portal.language,
            "status": status,
            "articles": processed,
            "new_assertions": created_assertions,
            "assertions": portal.assertion_count,
        }
    except Exception as error:
        now = timezone.now()
        message = f"{error.__class__.__name__}: {error}"
        portal.scan_status = WikipediaPortal.ScanStatus.FAILED
        portal.last_error = message
        portal.last_scanned_at = now
        portal.save(update_fields=["scan_status", "last_error", "last_scanned_at", "updated_at"])
        run.status = WikipediaPortal.ScanStatus.FAILED
        run.error_message = message
        run.completed_at = now
        run.save(update_fields=["status", "error_message", "completed_at"])
        raise
