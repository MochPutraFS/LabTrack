from django.contrib import admin

from apps.loans.models import Loan, LoanItem


class LoanItemInline(admin.TabularInline):
    model = LoanItem
    extra = 0
    autocomplete_fields = ("asset",)


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = (
        "loan_number",
        "loan_channel",
        "borrower_name",
        "borrower_identifier",
        "borrow_date",
        "due_date",
        "status",
        "processed_by",
    )
    list_filter = ("loan_channel", "status", "borrow_date", "due_date")
    search_fields = (
        "loan_number",
        "borrower_name",
        "borrower_identifier",
        "borrower_contact",
        "purpose",
    )
    date_hierarchy = "borrow_date"
    inlines = [LoanItemInline]


@admin.register(LoanItem)
class LoanItemAdmin(admin.ModelAdmin):
    list_display = (
        "loan",
        "asset",
        "condition_on_checkout",
        "condition_on_return",
    )
    list_filter = ("condition_on_checkout", "condition_on_return")
    search_fields = ("loan__loan_number", "asset__asset_code", "asset__name")
