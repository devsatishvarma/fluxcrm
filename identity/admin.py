from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from identity.models import AuthThrottle, CompanySettings, Role, User


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "scope_policy")
    readonly_fields = ("key",)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "GlideCRM",
            {
                "fields": (
                    "display_name",
                    "phone",
                    "timezone",
                    "manager",
                    "role",
                    "last_seen_at",
                )
            },
        ),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (None, {"fields": ("email", "display_name", "timezone", "role")}),
    )
    list_display = ("username", "display_name", "email", "role", "is_active")
    readonly_fields = ("last_seen_at",)


@admin.register(CompanySettings)
class CompanySettingsAdmin(admin.ModelAdmin):
    readonly_fields = ("singleton",)


@admin.register(AuthThrottle)
class AuthThrottleAdmin(admin.ModelAdmin):
    list_display = ("scope", "attempted_at")
    readonly_fields = ("scope", "subject_hash", "attempted_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
