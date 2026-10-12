from django.contrib import admin

from audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "action", "object_type", "object_id", "actor")
    list_filter = ("action", "object_type")
    readonly_fields = (
        "actor",
        "occurred_at",
        "action",
        "object_type",
        "object_id",
        "before_json",
        "after_json",
        "request_id",
        "source",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
