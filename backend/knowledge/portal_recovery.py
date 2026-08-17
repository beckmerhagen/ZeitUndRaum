"""Recovery helpers for interrupted Wikipedia portal catalog scans."""

from django.db import transaction
from django.utils import timezone

from .models import PortalScanRun, WikipediaPortal


DEFAULT_RECOVERY_REASON = (
    "Der Portal-Scan wurde durch einen Worker- oder Serverneustart unterbrochen "
    "und automatisch zur Wiederaufnahme vorgemerkt."
)


def recover_interrupted_portal_scans(*, languages=None, reason=DEFAULT_RECOVERY_REASON):
    """Turn orphaned RUNNING records back into resumable, audited partial scans."""

    normalized_languages = list(
        dict.fromkeys(language.casefold() for language in (languages or ["de", "en", "fr"]))
    )
    now = timezone.now()

    with transaction.atomic():
        interrupted_portals = list(
            WikipediaPortal.objects.select_for_update()
            .filter(
                language__in=normalized_languages,
                scan_status=WikipediaPortal.ScanStatus.RUNNING,
            )
            .values_list("id", flat=True)
        )
        recovered_portals = 0
        if interrupted_portals:
            recovered_portals = WikipediaPortal.objects.filter(id__in=interrupted_portals).update(
                scan_status=WikipediaPortal.ScanStatus.PARTIAL,
                last_error=reason,
                updated_at=now,
            )

        interrupted_runs = PortalScanRun.objects.select_for_update().filter(
            portal__language__in=normalized_languages,
            status=WikipediaPortal.ScanStatus.RUNNING,
        )
        recovered_runs = interrupted_runs.update(
            status=WikipediaPortal.ScanStatus.PARTIAL,
            error_message=reason,
            completed_at=now,
        )

    resumable_portals = WikipediaPortal.objects.filter(
        language__in=normalized_languages,
        scan_status__in=[WikipediaPortal.ScanStatus.PENDING, WikipediaPortal.ScanStatus.PARTIAL],
    ).count()
    return {
        "languages": normalized_languages,
        "recovered_portals": recovered_portals,
        "recovered_runs": recovered_runs,
        "resumable_portals": resumable_portals,
    }
