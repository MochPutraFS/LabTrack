"""Views for Category, Location, Asset Master, QR Download/Print, and Public QR Scan."""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.permissions import STAFF_ROLES, role_required
from apps.inventory import services
from apps.inventory.forms import (
    AssetForm,
    AssetMoveForm,
    AssetRetireForm,
    CategoryForm,
    LocationForm,
)
from apps.inventory.models import Asset, Category, Location


def _base_url(request) -> str:
    return request.build_absolute_uri("/").rstrip("/")


# --- Categories (FR-03) ---


@login_required
def category_list_view(request):
    form = CategoryForm(request.POST or None)
    if request.method == "POST":
        if not request.user.is_staff_lab:
            raise PermissionDenied("Hanya Admin dan Laboran yang dapat mengelola kategori.")
        if form.is_valid():
            cat = form.save()
            messages.success(request, f"Kategori '{cat.name}' ({cat.code}) berhasil ditambahkan.")
            return redirect("inventory:category_list")

    categories = Category.objects.annotate(
        asset_count=Count("assets"),
        total_value=Coalesce(Sum("assets__acquisition_cost"), Decimal("0.00")),
    ).order_by("code")

    return render(
        request,
        "inventory/category_list.html",
        {"categories": categories, "form": form},
    )


@role_required(*STAFF_ROLES)
def category_edit_view(request, pk: int):
    category = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Kategori '{category.name}' berhasil diperbarui.")
        return redirect("inventory:category_list")
    return render(request, "inventory/category_form.html", {"form": form, "category": category})


@role_required(*STAFF_ROLES)
@require_POST
def category_delete_view(request, pk: int):
    category = get_object_or_404(Category, pk=pk)
    try:
        services.delete_category(category, actor=request.user)
        messages.success(request, f"Kategori '{category.name}' berhasil dihapus.")
    except ValidationError as exc:
        messages.error(request, exc.message)
    return redirect("inventory:category_list")


# --- Locations (FR-04) ---


@login_required
def location_list_view(request):
    form = LocationForm(request.POST or None)
    if request.method == "POST":
        if not request.user.is_staff_lab:
            raise PermissionDenied("Hanya Admin dan Laboran yang dapat mengelola lokasi.")
        if form.is_valid():
            loc = form.save()
            messages.success(request, f"Lokasi '{loc.name}' ({loc.code}) berhasil ditambahkan.")
            return redirect("inventory:location_list")

    locations = Location.objects.annotate(asset_count=Count("assets")).order_by("code")
    return render(
        request,
        "inventory/location_list.html",
        {"locations": locations, "form": form},
    )


@role_required(*STAFF_ROLES)
def location_edit_view(request, pk: int):
    location = get_object_or_404(Location, pk=pk)
    form = LocationForm(request.POST or None, instance=location)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Lokasi '{location.name}' berhasil diperbarui.")
        return redirect("inventory:location_list")
    return render(request, "inventory/location_form.html", {"form": form, "location": location})


@role_required(*STAFF_ROLES)
@require_POST
def location_delete_view(request, pk: int):
    location = get_object_or_404(Location, pk=pk)
    try:
        services.delete_location(location, actor=request.user)
        messages.success(request, f"Lokasi '{location.name}' berhasil dihapus.")
    except ValidationError as exc:
        messages.error(request, exc.message)
    return redirect("inventory:location_list")


# --- Assets Master (FR-02, FR-04, FR-06) ---


@login_required
def asset_list_view(request):
    q = (request.GET.get("q") or "").strip()
    category_id = (request.GET.get("category") or "").strip()
    location_id = (request.GET.get("location") or "").strip()
    status = (request.GET.get("status") or "").strip()
    condition = (request.GET.get("condition") or "").strip()

    qs = Asset.objects.select_related("category", "location")
    if not request.user.is_staff_lab:
        qs = qs.filter(is_active=True).exclude(status=Asset.Status.RETIRED)

    if q:
        qs = qs.filter(
            Q(asset_code__icontains=q)
            | Q(name__icontains=q)
            | Q(serial_number__icontains=q)
            | Q(brand__icontains=q)
            | Q(model_name__icontains=q)
        )
    if category_id.isdigit():
        qs = qs.filter(category_id=int(category_id))
    if location_id.isdigit():
        qs = qs.filter(location_id=int(location_id))
    if status in Asset.Status.values:
        qs = qs.filter(status=status)
    if condition in Asset.Condition.values:
        qs = qs.filter(condition=condition)

    page_obj = Paginator(qs, 12).get_page(request.GET.get("page"))

    return render(
        request,
        "inventory/asset_list.html",
        {
            "page_obj": page_obj,
            "categories": Category.objects.all(),
            "locations": Location.objects.filter(is_active=True),
            "statuses": Asset.Status.choices,
            "conditions": Asset.Condition.choices,
            "filters": {
                "q": q,
                "category": category_id,
                "location": location_id,
                "status": status,
                "condition": condition,
            },
        },
    )


@role_required(*STAFF_ROLES)
def asset_create_view(request):
    form = AssetForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        asset = form.save(commit=False)
        services.create_asset(asset, actor=request.user, base_url=_base_url(request))
        messages.success(request, f"Aset '{asset.name}' ({asset.asset_code}) berhasil ditambahkan beserta QR Code.")
        return redirect("inventory:asset_detail", pk=asset.pk)

    return render(request, "inventory/asset_form.html", {"form": form, "is_edit": False})


@login_required
def asset_detail_view(request, pk: int):
    asset = get_object_or_404(Asset.objects.select_related("category", "location"), pk=pk)
    if not request.user.is_staff_lab and (not asset.is_active or asset.status == Asset.Status.RETIRED):
        raise PermissionDenied("Aset ini telah dihapusbukukan.")

    services.ensure_asset_qr(asset, base_url=_base_url(request))

    location_histories = asset.location_histories.select_related("from_location", "to_location", "moved_by")
    damage_reports = asset.damage_reports.select_related("reported_by", "handled_by")
    maintenance_logs = asset.maintenance_logs.select_related("performed_by", "schedule")

    if request.user.is_staff_lab:
        loan_items = asset.loan_items.select_related("loan", "loan__borrower_user").order_by("-loan__created_at")
        valuation = services.calculate_asset_book_value(asset)
    else:
        loan_items = asset.loan_items.filter(loan__borrower_user=request.user).select_related("loan").order_by(
            "-loan__created_at"
        )
        valuation = None

    return render(
        request,
        "inventory/asset_detail.html",
        {
            "asset": asset,
            "location_histories": location_histories,
            "loan_items": loan_items,
            "damage_reports": damage_reports,
            "maintenance_logs": maintenance_logs,
            "valuation": valuation,
            "move_form": AssetMoveForm(current_location=asset.location) if request.user.is_staff_lab else None,
            "retire_form": AssetRetireForm() if request.user.is_admin else None,
        },
    )


@role_required(*STAFF_ROLES)
def asset_edit_view(request, pk: int):
    asset = get_object_or_404(Asset.objects.select_related("category", "location"), pk=pk)
    previous_location = asset.location
    form = AssetForm(request.POST or None, request.FILES or None, instance=asset)
    if request.method == "POST" and form.is_valid():
        updated = form.save(commit=False)
        services.update_asset(updated, actor=request.user, previous_location=previous_location)
        messages.success(request, f"Data aset '{updated.name}' berhasil diperbarui.")
        return redirect("inventory:asset_detail", pk=updated.pk)

    return render(request, "inventory/asset_form.html", {"form": form, "is_edit": True, "asset": asset})


@role_required(*STAFF_ROLES)
@require_POST
def asset_move_view(request, pk: int):
    asset = get_object_or_404(Asset.objects.select_related("location"), pk=pk)
    form = AssetMoveForm(request.POST, current_location=asset.location)
    if form.is_valid():
        try:
            history = services.move_asset_location(
                asset=asset,
                to_location=form.cleaned_data["to_location"],
                actor=request.user,
                reason=form.cleaned_data["reason"],
            )
            messages.success(
                request,
                f"Aset {asset.asset_code} berhasil dimutasi ke {history.to_location.name}.",
            )
        except ValidationError as exc:
            messages.error(request, exc.message)
    else:
        messages.error(request, "Gagal mutasi lokasi. Pastikan lokasi tujuan dan alasan terisi dengan benar.")
    return redirect("inventory:asset_detail", pk=asset.pk)


@role_required("ADMIN")
@require_POST
def asset_retire_view(request, pk: int):
    asset = get_object_or_404(Asset, pk=pk)
    form = AssetRetireForm(request.POST)
    if form.is_valid():
        try:
            services.retire_asset(asset=asset, actor=request.user, reason=form.cleaned_data["reason"])
            messages.success(request, f"Aset {asset.asset_code} berhasil dihapusbukukan (RETIRED).")
        except ValidationError as exc:
            messages.error(request, exc.message)
    else:
        messages.error(request, "Alasan penghapusbukuan wajib diisi.")
    return redirect("inventory:asset_detail", pk=asset.pk)


# --- QR Code Download, Bulk Print & Public Scan (FR-06) ---


@role_required(*STAFF_ROLES)
def asset_qr_download_view(request, pk: int):
    asset = get_object_or_404(Asset, pk=pk)
    services.ensure_asset_qr(asset, base_url=_base_url(request))
    with asset.qr_code_image.open("rb") as qr_file:
        payload = qr_file.read()
    response = HttpResponse(payload, content_type="image/png")
    response["Content-Disposition"] = f'attachment; filename="QR-{asset.asset_code}.png"'
    return response


@role_required(*STAFF_ROLES)
def asset_qr_print_view(request):
    category_id = (request.GET.get("category") or "").strip()
    location_id = (request.GET.get("location") or "").strip()
    raw_ids = request.GET.getlist("ids")

    qs = Asset.objects.select_related("category", "location").filter(is_active=True)
    if category_id.isdigit():
        qs = qs.filter(category_id=int(category_id))
    if location_id.isdigit():
        qs = qs.filter(location_id=int(location_id))
    valid_ids = [int(i) for i in raw_ids if i.isdigit()]
    if valid_ids:
        qs = qs.filter(pk__in=valid_ids)

    assets = list(qs)
    base = _base_url(request)
    for item in assets:
        services.ensure_asset_qr(item, base_url=base)

    return render(
        request,
        "inventory/qr_print.html",
        {
            "assets": assets,
            "categories": Category.objects.all(),
            "locations": Location.objects.filter(is_active=True),
            "selected_category": category_id,
            "selected_location": location_id,
        },
    )


def asset_qr_scan_view(request, asset_code: str):
    """Public read-only QR identity card; reveals staff quick actions only to logged-in ADMIN/LABORAN."""
    asset = get_object_or_404(
        Asset.objects.select_related("category", "location"),
        asset_code__iexact=asset_code.strip(),
    )
    is_staff_viewer = bool(request.user.is_authenticated and request.user.is_staff_lab)
    return render(
        request,
        "inventory/qr_scan_public.html",
        {
            "asset": asset,
            "is_staff_viewer": is_staff_viewer,
        },
    )
