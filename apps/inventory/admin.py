from django.contrib import admin

from apps.inventory.models import Asset, AssetLocationHistory, Category, Location


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "default_useful_life_years", "created_at")
    search_fields = ("code", "name")
    ordering = ("code",)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "building", "floor", "pic_name", "is_active")
    list_filter = ("building", "floor", "is_active")
    search_fields = ("code", "name", "pic_name")
    ordering = ("code",)


class AssetLocationHistoryInline(admin.TabularInline):
    model = AssetLocationHistory
    extra = 0
    readonly_fields = ("from_location", "to_location", "moved_by", "moved_at", "reason")
    can_delete = False


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = (
        "asset_code",
        "name",
        "category",
        "location",
        "status",
        "condition",
        "acquisition_cost",
        "is_active",
    )
    list_filter = ("status", "condition", "category", "location", "is_active")
    search_fields = ("asset_code", "name", "brand", "model_name", "serial_number")
    ordering = ("asset_code",)
    inlines = [AssetLocationHistoryInline]


@admin.register(AssetLocationHistory)
class AssetLocationHistoryAdmin(admin.ModelAdmin):
    list_display = ("asset", "from_location", "to_location", "moved_by", "moved_at")
    list_filter = ("to_location", "moved_at")
    search_fields = ("asset__asset_code", "asset__name", "reason")
    date_hierarchy = "moved_at"
