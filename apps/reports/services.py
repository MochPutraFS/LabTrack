"""Business logic for LabTrack dashboard analytics, Straight-Line depreciation, and CSV/PDF reports."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO, StringIO

from django.db.models import Count, Q, QuerySet
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.inventory.models import Asset, Category, Location
from apps.loans.models import Loan
from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule

TWO_DP = Decimal("0.01")
ONE_DP = Decimal("0.1")
ZERO = Decimal("0.00")
DAYS_PER_YEAR = Decimal("365.25")
HUNDRED = Decimal("100")

_ID_MONTHS = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "Mei",
    "Jun",
    "Jul",
    "Agu",
    "Sep",
    "Okt",
    "Nov",
    "Des",
)


def _q2(value: Decimal) -> Decimal:
    return value.quantize(TWO_DP, rounding=ROUND_HALF_UP)


def format_rupiah_plain(value: Decimal | int | float | None) -> str:
    """Format monetary Decimal into Indonesian Rupiah string for CSV/PDF exports."""
    if value is None:
        return "Rp 0"
    amount = Decimal(str(value))
    sign = "-" if amount < 0 else ""
    whole = int(abs(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"{sign}Rp {whole:,}".replace(",", ".")


# --- Straight-Line Depreciation (docs/04-Database-ERD-Schema.md Section 3) ---


@dataclass(frozen=True)
class AssetDepreciation:
    asset: Asset
    as_of_date: date
    acquisition_cost: Decimal
    salvage_value: Decimal
    depreciable_base: Decimal
    useful_life_years: int
    age_years: Decimal
    annual_depreciation: Decimal
    accumulated_depreciation: Decimal
    book_value: Decimal
    depreciation_pct: Decimal


def calculate_asset_depreciation(
    asset: Asset,
    as_of_date: date | None = None,
) -> AssetDepreciation:
    """Compute Straight-Line depreciation for a single Asset using Decimal & ROUND_HALF_UP."""
    ref_date = as_of_date or timezone.localdate()
    cost = Decimal(asset.acquisition_cost)
    salvage = Decimal(asset.salvage_value)
    life = max(1, int(asset.useful_life_years))

    depreciable_base = max(ZERO, cost - salvage)
    raw_annual = depreciable_base / Decimal(life)
    annual_depreciation = _q2(raw_annual)

    days_elapsed = max(0, (ref_date - asset.acquisition_date).days)
    age_years_raw = Decimal(days_elapsed) / DAYS_PER_YEAR
    age_years = age_years_raw.quantize(ONE_DP, rounding=ROUND_HALF_UP)

    accumulated = _q2(min(depreciable_base, raw_annual * age_years_raw))
    book_value = _q2(max(salvage, cost - accumulated))

    if depreciable_base == ZERO:
        depreciation_pct = ZERO
    else:
        depreciation_pct = min(
            Decimal("100.00"),
            _q2((accumulated / depreciable_base) * HUNDRED),
        )

    return AssetDepreciation(
        asset=asset,
        as_of_date=ref_date,
        acquisition_cost=_q2(cost),
        salvage_value=_q2(salvage),
        depreciable_base=_q2(depreciable_base),
        useful_life_years=life,
        age_years=age_years,
        annual_depreciation=annual_depreciation,
        accumulated_depreciation=accumulated,
        book_value=book_value,
        depreciation_pct=depreciation_pct,
    )


def calculate_portfolio_depreciation(
    queryset: QuerySet[Asset],
    as_of_date: date | None = None,
) -> dict:
    """Compute Straight-Line depreciation rows and aggregate totals for an Asset queryset."""
    ref_date = as_of_date or timezone.localdate()
    rows: list[AssetDepreciation] = []
    total_cost = ZERO
    total_salvage = ZERO
    total_annual = ZERO
    total_accumulated = ZERO
    total_book_value = ZERO

    for asset in queryset.select_related("category", "location"):
        row = calculate_asset_depreciation(asset, as_of_date=ref_date)
        rows.append(row)
        total_cost += row.acquisition_cost
        total_salvage += row.salvage_value
        total_annual += row.annual_depreciation
        total_accumulated += row.accumulated_depreciation
        total_book_value += row.book_value

    total_base = max(ZERO, total_cost - total_salvage)
    avg_pct = (
        ZERO
        if total_base == ZERO
        else min(Decimal("100.00"), _q2((total_accumulated / total_base) * HUNDRED))
    )

    return {
        "as_of_date": ref_date,
        "rows": rows,
        "totals": {
            "count": len(rows),
            "acquisition_cost": _q2(total_cost),
            "salvage_value": _q2(total_salvage),
            "annual_depreciation": _q2(total_annual),
            "accumulated_depreciation": _q2(total_accumulated),
            "book_value": _q2(total_book_value),
            "depreciation_pct": avg_pct,
        },
    }


# --- Dashboard KPIs & Chart.js JSON Payloads (FR-09) ---


def _recent_six_months(today: date) -> list[tuple[int, int, str]]:
    """Return ordered list of (year, month, label) for the last 6 calendar months."""
    months: list[tuple[int, int, str]] = []
    year, month = today.year, today.month
    for _ in range(6):
        months.append((year, month, f"{_ID_MONTHS[month]} {year}"))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    months.reverse()
    return months


def get_dashboard_charts_payload(today: date | None = None) -> dict:
    """Build JSON payload matching docs/05-Architecture-dan-API.md Section 4."""
    ref_date = today or timezone.localdate()
    active_assets = Asset.objects.filter(is_active=True).exclude(status=Asset.Status.RETIRED)

    # 1. Status distribution
    status_counts = {
        row["status"]: row["total"]
        for row in active_assets.values("status").annotate(total=Count("id"))
    }
    status_distribution = {
        "labels": ["Tersedia", "Dipinjam", "Pemeliharaan", "Rusak"],
        "values": [
            status_counts.get(Asset.Status.AVAILABLE, 0),
            status_counts.get(Asset.Status.BORROWED, 0),
            status_counts.get(Asset.Status.MAINTENANCE, 0),
            status_counts.get(Asset.Status.DAMAGED, 0),
        ],
    }

    # 2. Condition by category
    cat_rows = (
        Category.objects.annotate(
            good=Count(
                "assets",
                filter=Q(
                    assets__is_active=True,
                    assets__condition=Asset.Condition.GOOD,
                )
                & ~Q(assets__status=Asset.Status.RETIRED),
            ),
            minor_damage=Count(
                "assets",
                filter=Q(
                    assets__is_active=True,
                    assets__condition=Asset.Condition.MINOR_DAMAGE,
                )
                & ~Q(assets__status=Asset.Status.RETIRED),
            ),
            major_damage=Count(
                "assets",
                filter=Q(
                    assets__is_active=True,
                    assets__condition=Asset.Condition.MAJOR_DAMAGE,
                )
                & ~Q(assets__status=Asset.Status.RETIRED),
            ),
        )
        .order_by("code")
    )
    condition_by_category = {
        "labels": [c.name for c in cat_rows],
        "good": [c.good for c in cat_rows],
        "minor_damage": [c.minor_damage for c in cat_rows],
        "major_damage": [c.major_damage for c in cat_rows],
    }

    # 3. 6-month activity (Online vs Walk-In loans + Maintenances)
    months = _recent_six_months(ref_date)
    start_year, start_month, _ = months[0]
    window_start = date(start_year, start_month, 1)

    online_map: dict[tuple[int, int], int] = {}
    walk_in_map: dict[tuple[int, int], int] = {}
    for bdate, channel in Loan.objects.filter(borrow_date__gte=window_start).values_list(
        "borrow_date", "loan_channel"
    ):
        key = (bdate.year, bdate.month)
        if channel == Loan.Channel.ONLINE:
            online_map[key] = online_map.get(key, 0) + 1
        elif channel == Loan.Channel.WALK_IN:
            walk_in_map[key] = walk_in_map.get(key, 0) + 1

    maint_map: dict[tuple[int, int], int] = {}
    for pdate in MaintenanceLog.objects.filter(performed_date__gte=window_start).values_list(
        "performed_date", flat=True
    ):
        key = (pdate.year, pdate.month)
        maint_map[key] = maint_map.get(key, 0) + 1

    monthly_activity = {
        "labels": [label for _, _, label in months],
        "loans_online": [online_map.get((y, m), 0) for y, m, _ in months],
        "loans_walk_in": [walk_in_map.get((y, m), 0) for y, m, _ in months],
        "maintenances": [maint_map.get((y, m), 0) for y, m, _ in months],
    }

    return {
        "status_distribution": status_distribution,
        "condition_by_category": condition_by_category,
        "monthly_activity": monthly_activity,
    }


def get_staff_dashboard_context(today: date | None = None) -> dict:
    """Aggregate KPIs and operational queues for ADMIN / LABORAN dashboard."""
    ref_date = today or timezone.localdate()
    active_assets = Asset.objects.filter(is_active=True).exclude(status=Asset.Status.RETIRED)

    counts = active_assets.aggregate(
        total=Count("id"),
        available=Count("id", filter=Q(status=Asset.Status.AVAILABLE)),
        borrowed=Count("id", filter=Q(status=Asset.Status.BORROWED)),
        maintenance_or_damaged=Count(
            "id",
            filter=Q(status__in=[Asset.Status.MAINTENANCE, Asset.Status.DAMAGED]),
        ),
    )

    portfolio = calculate_portfolio_depreciation(active_assets, as_of_date=ref_date)

    overdue_loans = (
        Loan.objects.filter(
            Q(status=Loan.Status.OVERDUE)
            | Q(status=Loan.Status.ACTIVE, due_date__lt=ref_date)
        )
        .prefetch_related("items__asset")
        .order_by("due_date", "id")
    )

    pending_online_loans = (
        Loan.objects.filter(
            loan_channel=Loan.Channel.ONLINE,
            status=Loan.Status.PENDING,
        )
        .prefetch_related("items__asset")
        .order_by("borrow_date", "created_at")
    )

    h7_cutoff = ref_date + timedelta(days=7)
    upcoming_schedules = (
        MaintenanceSchedule.objects.filter(
            status__in=[
                MaintenanceSchedule.Status.SCHEDULED,
                MaintenanceSchedule.Status.IN_PROGRESS,
                MaintenanceSchedule.Status.OVERDUE,
            ],
            next_due_date__lte=h7_cutoff,
        )
        .select_related("asset", "assigned_to")
        .order_by("next_due_date", "id")
    )

    return {
        "kpi": {
            "total_assets": counts["total"],
            "available_assets": counts["available"],
            "borrowed_assets": counts["borrowed"],
            "overdue_loans_count": overdue_loans.count(),
            "maintenance_or_damaged": counts["maintenance_or_damaged"],
            "total_book_value": portfolio["totals"]["book_value"],
        },
        "pending_online_loans": pending_online_loans[:6],
        "pending_online_count": pending_online_loans.count(),
        "overdue_loans": overdue_loans[:6],
        "upcoming_schedules": upcoming_schedules[:6],
        "upcoming_schedules_count": upcoming_schedules.count(),
        "today": ref_date,
    }


def get_borrower_dashboard_context(user) -> dict:
    """Aggregate personal loan summary for BORROWER dashboard."""
    user_loans = Loan.objects.filter(borrower_user=user).prefetch_related("items__asset")
    counts = user_loans.aggregate(
        active=Count("id", filter=Q(status__in=[Loan.Status.ACTIVE, Loan.Status.OVERDUE])),
        pending=Count("id", filter=Q(status__in=[Loan.Status.PENDING, Loan.Status.APPROVED])),
        total=Count("id"),
    )
    available_assets_count = Asset.objects.filter(
        is_active=True,
        status=Asset.Status.AVAILABLE,
    ).exclude(condition=Asset.Condition.MAJOR_DAMAGE).count()

    return {
        "kpi": {
            "active_loans": counts["active"],
            "pending_loans": counts["pending"],
            "total_loans": counts["total"],
            "available_assets": available_assets_count,
        },
        "recent_loans": user_loans.order_by("-created_at")[:8],
    }


# --- Condition Report Aggregation (FR-10.1) ---


def get_condition_report(
    category_id: int | None = None,
    location_id: int | None = None,
    group_by: str = "location",
) -> dict:
    """Build condition summary grouped by location or category with totals row."""
    qs = Asset.objects.filter(is_active=True).exclude(status=Asset.Status.RETIRED)
    if category_id:
        qs = qs.filter(category_id=category_id)
    if location_id:
        qs = qs.filter(location_id=location_id)

    if group_by == "category":
        raw_rows = (
            qs.values("category__code", "category__name")
            .annotate(
                good=Count("id", filter=Q(condition=Asset.Condition.GOOD)),
                minor_damage=Count("id", filter=Q(condition=Asset.Condition.MINOR_DAMAGE)),
                major_damage=Count("id", filter=Q(condition=Asset.Condition.MAJOR_DAMAGE)),
                total=Count("id"),
            )
            .order_by("category__code")
        )
        rows = [
            {
                "code": r["category__code"],
                "name": r["category__name"],
                "good": r["good"],
                "minor_damage": r["minor_damage"],
                "major_damage": r["major_damage"],
                "total": r["total"],
                "good_pct": _q2(Decimal(r["good"]) * HUNDRED / Decimal(r["total"])) if r["total"] else ZERO,
            }
            for r in raw_rows
        ]
    else:
        group_by = "location"
        raw_rows = (
            qs.values("location__code", "location__name", "location__building")
            .annotate(
                good=Count("id", filter=Q(condition=Asset.Condition.GOOD)),
                minor_damage=Count("id", filter=Q(condition=Asset.Condition.MINOR_DAMAGE)),
                major_damage=Count("id", filter=Q(condition=Asset.Condition.MAJOR_DAMAGE)),
                total=Count("id"),
            )
            .order_by("location__code")
        )
        rows = [
            {
                "code": r["location__code"],
                "name": r["location__name"],
                "subtitle": r["location__building"],
                "good": r["good"],
                "minor_damage": r["minor_damage"],
                "major_damage": r["major_damage"],
                "total": r["total"],
                "good_pct": _q2(Decimal(r["good"]) * HUNDRED / Decimal(r["total"])) if r["total"] else ZERO,
            }
            for r in raw_rows
        ]

    total_good = sum(r["good"] for r in rows)
    total_minor = sum(r["minor_damage"] for r in rows)
    total_major = sum(r["major_damage"] for r in rows)
    total_all = sum(r["total"] for r in rows)

    return {
        "group_by": group_by,
        "rows": rows,
        "totals": {
            "good": total_good,
            "minor_damage": total_minor,
            "major_damage": total_major,
            "total": total_all,
            "good_pct": _q2(Decimal(total_good) * HUNDRED / Decimal(total_all)) if total_all else ZERO,
        },
    }


# --- CSV Exports (UTF-8 BOM for Microsoft Excel compatibility) ---


def build_condition_csv(report: dict) -> bytes:
    """Generate UTF-8 BOM CSV bytes for the Asset Condition Report."""
    buf = StringIO()
    writer = csv.writer(buf)
    group_label = "Kategori" if report["group_by"] == "category" else "Lokasi"
    writer.writerow(["Kode", group_label, "Baik", "Rusak Ringan", "Rusak Berat", "Total Aset", "% Baik"])
    for r in report["rows"]:
        writer.writerow([
            r["code"],
            r["name"],
            r["good"],
            r["minor_damage"],
            r["major_damage"],
            r["total"],
            f"{r['good_pct']}%",
        ])
    t = report["totals"]
    writer.writerow(["", "TOTAL", t["good"], t["minor_damage"], t["major_damage"], t["total"], f"{t['good_pct']}%"])
    return buf.getvalue().encode("utf-8-sig")


def build_depreciation_csv(report: dict) -> bytes:
    """Generate UTF-8 BOM CSV bytes for the Straight-Line Depreciation Report."""
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Kode Aset",
        "Nama Aset",
        "Kategori",
        "Lokasi",
        "Tgl Perolehan",
        "Harga Perolehan (Rp)",
        "Nilai Residu (Rp)",
        "Umur (Thn)",
        "Usia (Thn)",
        "Penyusutan/Thn (Rp)",
        "Akumulasi Penyusutan (Rp)",
        "Nilai Buku (Rp)",
        "% Susut",
    ])
    for r in report["rows"]:
        writer.writerow([
            r.asset.asset_code,
            r.asset.name,
            r.asset.category.name,
            r.asset.location.code,
            r.asset.acquisition_date.isoformat(),
            f"{r.acquisition_cost:.2f}",
            f"{r.salvage_value:.2f}",
            r.useful_life_years,
            f"{r.age_years:.1f}",
            f"{r.annual_depreciation:.2f}",
            f"{r.accumulated_depreciation:.2f}",
            f"{r.book_value:.2f}",
            f"{r.depreciation_pct:.2f}%",
        ])
    t = report["totals"]
    writer.writerow([
        "",
        f"TOTAL ({t['count']} aset)",
        "",
        "",
        "",
        f"{t['acquisition_cost']:.2f}",
        f"{t['salvage_value']:.2f}",
        "",
        "",
        f"{t['annual_depreciation']:.2f}",
        f"{t['accumulated_depreciation']:.2f}",
        f"{t['book_value']:.2f}",
        f"{t['depreciation_pct']:.2f}%",
    ])
    return buf.getvalue().encode("utf-8-sig")


# --- ReportLab PDF Exports ---

_TEAL_HEADER = colors.HexColor("#0F766E")
_SLATE_SUBTLE = colors.HexColor("#F1F5F9")
_SLATE_BORDER = colors.HexColor("#CBD5E1")
_SLATE_TEXT = colors.HexColor("#1E293B")
_MUTED_TEXT = colors.HexColor("#64748B")
_TEAL_TOTAL_BG = colors.HexColor("#F0FDFA")


def _pdf_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "LTTitle",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=_SLATE_TEXT,
            spaceAfter=2,
        ),
        "meta": ParagraphStyle(
            "LTMeta",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=_MUTED_TEXT,
            spaceAfter=10,
        ),
        "cell": ParagraphStyle(
            "LTCell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=_SLATE_TEXT,
        ),
        "cell_bold": ParagraphStyle(
            "LTCellBold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=_SLATE_TEXT,
        ),
        "header": ParagraphStyle(
            "LTHeader",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.white,
        ),
    }


def _base_table_style(right_cols: tuple[int, ...]) -> list:
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _TEAL_HEADER),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, _SLATE_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, _SLATE_SUBTLE]),
        ("BACKGROUND", (0, -1), (-1, -1), _TEAL_TOTAL_BG),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 1.0, _TEAL_HEADER),
    ]
    for col in right_cols:
        style.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    return style


def build_condition_pdf(report: dict, filter_summary: str = "Semua Kategori & Lokasi") -> bytes:
    """Generate formatted ReportLab PDF for Asset Condition Report."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Laporan Kondisi Aset Laboratorium — LabTrack",
    )
    styles = _pdf_styles()
    printed_at = timezone.localtime().strftime("%d %b %Y %H:%M WITA")
    group_label = "Kategori" if report["group_by"] == "category" else "Lokasi Ruangan"

    story = [
        Paragraph("LabTrack — Laporan Kondisi Aset Laboratorium", styles["title"]),
        Paragraph(
            f"Pengelompokan: {group_label} &nbsp;|&nbsp; Filter: {filter_summary} &nbsp;|&nbsp; Dicetak: {printed_at}",
            styles["meta"],
        ),
    ]

    data = [
        [
            Paragraph("Kode", styles["header"]),
            Paragraph(group_label, styles["header"]),
            "Baik",
            "Rusak Ringan",
            "Rusak Berat",
            "Total",
            "% Baik",
        ]
    ]
    for r in report["rows"]:
        data.append([
            r["code"],
            Paragraph(r["name"], styles["cell"]),
            str(r["good"]),
            str(r["minor_damage"]),
            str(r["major_damage"]),
            str(r["total"]),
            f"{r['good_pct']}%",
        ])
    t = report["totals"]
    data.append([
        "",
        Paragraph("TOTAL", styles["cell_bold"]),
        str(t["good"]),
        str(t["minor_damage"]),
        str(t["major_damage"]),
        str(t["total"]),
        f"{t['good_pct']}%",
    ])

    col_widths = [24 * mm, 64 * mm, 18 * mm, 24 * mm, 24 * mm, 14 * mm, 14 * mm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(_base_table_style(right_cols=(2, 3, 4, 5, 6))))
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph("Catatan: Hanya mencakup aset aktif (tidak termasuk aset berstatus RETIRED).", styles["meta"])
    )

    doc.build(story)
    return buf.getvalue()


def build_depreciation_pdf(report: dict, filter_summary: str = "Semua Kategori & Lokasi") -> bytes:
    """Generate landscape A4 ReportLab PDF for Straight-Line Depreciation Report."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Laporan Penyusutan Aset — LabTrack",
    )
    styles = _pdf_styles()
    printed_at = timezone.localtime().strftime("%d %b %Y %H:%M WITA")
    as_of_str = report["as_of_date"].strftime("%d %b %Y")

    story = [
        Paragraph("LabTrack — Laporan Penyusutan Aset (Metode Garis Lurus)", styles["title"]),
        Paragraph(
            f"Tanggal Acuan: {as_of_str} &nbsp;|&nbsp; Filter: {filter_summary} &nbsp;|&nbsp; Dicetak: {printed_at}",
            styles["meta"],
        ),
    ]

    data = [
        [
            Paragraph("Kode Aset", styles["header"]),
            Paragraph("Nama Aset", styles["header"]),
            Paragraph("Kategori", styles["header"]),
            "Perolehan",
            "Harga Beli",
            "Residu",
            "Umur/Usia",
            "Susut/Thn",
            "Akum. Susut",
            "Nilai Buku",
            "%",
        ]
    ]
    for r in report["rows"]:
        data.append([
            r.asset.asset_code,
            Paragraph(r.asset.name, styles["cell"]),
            Paragraph(r.asset.category.code, styles["cell"]),
            r.asset.acquisition_date.strftime("%Y-%m-%d"),
            format_rupiah_plain(r.acquisition_cost),
            format_rupiah_plain(r.salvage_value),
            f"{r.useful_life_years}t / {r.age_years}t",
            format_rupiah_plain(r.annual_depreciation),
            format_rupiah_plain(r.accumulated_depreciation),
            format_rupiah_plain(r.book_value),
            f"{r.depreciation_pct:.0f}%",
        ])

    t = report["totals"]
    data.append([
        "",
        Paragraph(f"TOTAL ({t['count']} aset)", styles["cell_bold"]),
        "",
        "",
        format_rupiah_plain(t["acquisition_cost"]),
        format_rupiah_plain(t["salvage_value"]),
        "",
        format_rupiah_plain(t["annual_depreciation"]),
        format_rupiah_plain(t["accumulated_depreciation"]),
        format_rupiah_plain(t["book_value"]),
        f"{t['depreciation_pct']:.0f}%",
    ])

    # Total usable width on landscape A4 (297mm - 24mm margins = 273mm)
    col_widths = [
        30 * mm,
        47 * mm,
        14 * mm,
        20 * mm,
        28 * mm,
        24 * mm,
        18 * mm,
        26 * mm,
        27 * mm,
        27 * mm,
        12 * mm,
    ]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(_base_table_style(right_cols=(4, 5, 6, 7, 8, 9, 10))))
    story.append(table)
    story.append(Spacer(1, 5 * mm))
    story.append(
        Paragraph(
            "Metode: Garis Lurus (Straight-Line) — Akumulasi = min(Harga - Residu, Penyusutan/Thn x Usia); "
            "Nilai Buku = max(Residu, Harga - Akumulasi).",
            styles["meta"],
        )
    )

    doc.build(story)
    return buf.getvalue()
