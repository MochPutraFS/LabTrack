from django.contrib import admin

from apps.maintenance.models import DamageReport, MaintenanceLog, MaintenanceSchedule


@admin.register(DamageReport)
class DamageReportAdmin(admin.ModelAdmin):
    list_display = (
        "report_number",
        "asset",
        "severity",
        "status",
        "reported_by",
        "handled_by",
        "created_at",
    )
    list_filter = ("severity", "status", "created_at")
    search_fields = ("report_number", "asset__asset_code", "asset__name", "description")
    date_hierarchy = "created_at"


@admin.register(MaintenanceSchedule)
class MaintenanceScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "asset",
        "title",
        "frequency",
        "next_due_date",
        "assigned_to",
        "status",
    )
    list_filter = ("frequency", "status", "next_due_date")
    search_fields = ("title", "asset__asset_code", "asset__name")
    date_hierarchy = "next_due_date"


@admin.register(MaintenanceLog)
class MaintenanceLogAdmin(admin.ModelAdmin):
    list_display = (
        "asset",
        "performed_date",
        "performed_by",
        "cost",
        "result_condition",
        "schedule",
        "damage_report",
    )
    list_filter = ("result_condition", "performed_date")
    search_fields = ("asset__asset_code", "asset__name", "summary")
    date_hierarchy = "performed_date"
