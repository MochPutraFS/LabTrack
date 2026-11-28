from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "full_name",
        "email",
        "role",
        "identifier_number",
        "department",
        "is_active",
    )
    list_filter = ("role", "is_active", "is_staff", "department")
    search_fields = ("username", "full_name", "email", "identifier_number", "department")
    ordering = ("full_name", "username")

    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Informasi LabTrack",
            {
                "fields": (
                    "full_name",
                    "role",
                    "identifier_number",
                    "phone_number",
                    "department",
                )
            },
        ),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (
            "Informasi LabTrack",
            {
                "fields": (
                    "email",
                    "full_name",
                    "role",
                    "identifier_number",
                    "phone_number",
                    "department",
                )
            },
        ),
    )
