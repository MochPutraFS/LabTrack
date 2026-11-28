"""Custom template tags and filters for LabTrack UI."""

from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

register = template.Library()

# Soft pastel pill styles matching docs/06-UI-UX-Design-System.md
_BADGE_STYLES = {
    # Green — positive / available / good
    "AVAILABLE": ("#ECFDF5", "#065F46", "#A7F3D0", "Tersedia"),
    "GOOD": ("#ECFDF5", "#065F46", "#A7F3D0", "Baik"),
    "RETURNED": ("#ECFDF5", "#065F46", "#A7F3D0", "Dikembalikan"),
    "RESOLVED": ("#ECFDF5", "#065F46", "#A7F3D0", "Selesai Diperbaiki"),
    "COMPLETED": ("#ECFDF5", "#065F46", "#A7F3D0", "Selesai"),
    # Blue — active / borrowed / approved / scheduled
    "BORROWED": ("#EFF6FF", "#1E40AF", "#BFDBFE", "Dipinjam"),
    "ACTIVE": ("#EFF6FF", "#1E40AF", "#BFDBFE", "Sedang Dipinjam"),
    "APPROVED": ("#EFF6FF", "#1E40AF", "#BFDBFE", "Disetujui"),
    "SCHEDULED": ("#EFF6FF", "#1E40AF", "#BFDBFE", "Terjadwal"),
    "ADMIN": ("#EFF6FF", "#1E40AF", "#BFDBFE", "Admin"),
    # Amber — pending / maintenance / minor damage
    "PENDING": ("#FFFBEB", "#92400E", "#FDE68A", "Menunggu"),
    "MAINTENANCE": ("#FFFBEB", "#92400E", "#FDE68A", "Pemeliharaan"),
    "IN_REPAIR": ("#FFFBEB", "#92400E", "#FDE68A", "Dalam Perbaikan"),
    "MINOR_DAMAGE": ("#FFFBEB", "#92400E", "#FDE68A", "Rusak Ringan"),
    "IN_PROGRESS": ("#FFFBEB", "#92400E", "#FDE68A", "Sedang Dikerjakan"),
    "REPORTED": ("#FFFBEB", "#92400E", "#FDE68A", "Dilaporkan"),
    "VERIFIED": ("#FFFBEB", "#92400E", "#FDE68A", "Terverifikasi"),
    "LABORAN": ("#FFFBEB", "#92400E", "#FDE68A", "Laboran"),
    # Red — damaged / major damage / overdue / rejected / critical
    "DAMAGED": ("#FEF2F2", "#991B1B", "#FECACA", "Rusak"),
    "MAJOR_DAMAGE": ("#FEF2F2", "#991B1B", "#FECACA", "Rusak Berat"),
    "OVERDUE": ("#FEF2F2", "#991B1B", "#FECACA", "Terlambat"),
    "REJECTED": ("#FEF2F2", "#991B1B", "#FECACA", "Ditolak"),
    "UNREPAIRABLE": ("#FEF2F2", "#991B1B", "#FECACA", "Tidak Dapat Diperbaiki"),
    "CRITICAL": ("#FEF2F2", "#991B1B", "#FECACA", "Kritis"),
    "HIGH": ("#FEF2F2", "#991B1B", "#FECACA", "Tinggi"),
    # Slate — retired / cancelled / borrower / low / medium
    "RETIRED": ("#F1F5F9", "#475569", "#CBD5E1", "Dihapusbukukan"),
    "CANCELLED": ("#F1F5F9", "#475569", "#CBD5E1", "Dibatalkan"),
    "BORROWER": ("#F1F5F9", "#475569", "#CBD5E1", "Peminjam"),
    "LOW": ("#F1F5F9", "#475569", "#CBD5E1", "Rendah"),
    "MEDIUM": ("#FFFBEB", "#92400E", "#FDE68A", "Sedang"),
    # Loan channels
    "WALK_IN": ("#F0FDFA", "#115E59", "#99F6E4", "Walk-In"),
    "ONLINE": ("#EEF2FF", "#3730A3", "#C7D2FE", "Online"),
}


@register.filter
def format_rupiah(value) -> str:
    """Format a Decimal/numeric value into Indonesian Rupiah (e.g., Rp 15.000.000)."""
    if value is None or value == "":
        return "Rp 0"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return "Rp 0"
    sign = "-" if amount < 0 else ""
    whole = int(abs(amount).quantize(Decimal("1")))
    formatted = f"{whole:,}".replace(",", ".")
    return f"{sign}Rp {formatted}"


@register.simple_tag
def status_badge(code: str, label: str = "") -> str:
    """Render a soft pastel pill badge for any LabTrack domain status, condition, or role."""
    key = str(code or "").upper()
    bg, text, border, default_label = _BADGE_STYLES.get(
        key,
        ("#F1F5F9", "#475569", "#CBD5E1", code or "-"),
    )
    display = label or default_label
    return format_html(
        '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium whitespace-nowrap" '
        'style="background-color:{};color:{};border:1px solid {};">{}</span>',
        bg,
        text,
        border,
        display,
    )


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs) -> str:
    """Preserve existing GET query parameters while replacing specified keys (e.g., page)."""
    request = context.get("request")
    params = request.GET.copy() if request else {}
    for key, val in kwargs.items():
        if val is None or val == "":
            params.pop(key, None)
        else:
            params[key] = str(val)
    return params.urlencode()
