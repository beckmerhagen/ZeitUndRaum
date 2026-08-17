from django.contrib import admin

from .models import (
    Assertion,
    AssertionRelation,
    Coverage,
    Entity,
    EnvironmentalDataset,
    EnvironmentalEvent,
    EnvironmentalObservation,
    EnvironmentalRelation,
    Evidence,
    ExplorationContext,
    ExternalIdentifier,
    PlaceGeometry,
    PortalArticle,
    PortalScanRun,
    ResearchRequest,
    Source,
    WikipediaPortal,
)


class EvidenceInline(admin.TabularInline):
    model = Evidence
    extra = 0


@admin.register(Assertion)
class AssertionAdmin(admin.ModelAdmin):
    list_display = ("subject", "predicate", "time_start_year", "time_end_year", "knowledge_type", "status", "confidence")
    list_filter = ("status", "knowledge_type", "temporal_scope", "spatial_scope", "time_precision", "predicate")
    search_fields = ("subject__canonical_name", "value_text", "fingerprint")
    inlines = (EvidenceInline,)


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = ("canonical_name", "kind", "updated_at")
    list_filter = ("kind",)
    search_fields = ("canonical_name",)


admin.site.register(Source)
admin.site.register(ResearchRequest)
admin.site.register(ExplorationContext)
admin.site.register(Coverage)
admin.site.register(ExternalIdentifier)
admin.site.register(PlaceGeometry)
admin.site.register(EnvironmentalDataset)
admin.site.register(EnvironmentalEvent)
admin.site.register(EnvironmentalObservation)
admin.site.register(EnvironmentalRelation)
admin.site.register(AssertionRelation)
admin.site.register(WikipediaPortal)
admin.site.register(PortalArticle)
admin.site.register(PortalScanRun)
