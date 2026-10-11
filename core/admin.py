from django.contrib import admin

from core.models import JobRun


@admin.register(JobRun)
class JobRunAdmin(admin.ModelAdmin):
    list_display = ("name", "run_key", "status", "started_at", "finished_at")
    list_filter = ("name", "status")
    search_fields = ("name", "run_key")
    readonly_fields = (
        "name",
        "run_key",
        "status",
        "started_at",
        "finished_at",
        "detail",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
