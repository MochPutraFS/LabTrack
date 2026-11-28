"""Views for Hybrid Loan (Online & Walk-In) management, approvals, handover, and return."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.permissions import STAFF_ROLES, role_required
from apps.inventory.models import Asset
from apps.loans import services
from apps.loans.forms import (
    LoanOnlineRequestForm,
    LoanRejectForm,
    LoanReturnForm,
    LoanWalkInForm,
    borrowable_assets_queryset,
)
from apps.loans.models import Loan

User = get_user_model()


def _get_accessible_loan_or_403(request, pk: int) -> Loan:
    """Fetch a Loan and enforce IDOR ownership protection for BORROWER users."""
    loan = get_object_or_404(
        Loan.objects.select_related("borrower_user", "processed_by", "received_by").prefetch_related(
            "items__asset__category", "items__asset__location"
        ),
        pk=pk,
    )
    if not request.user.is_staff_lab and loan.borrower_user_id != request.user.pk:
        raise PermissionDenied("Anda tidak memiliki akses ke transaksi peminjaman ini.")
    return loan


def _preselected_asset_initial(request) -> tuple[list[int], Asset | None]:
    """Parse optional ?asset=<id> query param and warn if the asset is not borrowable."""
    raw_asset = (request.GET.get("asset") or "").strip()
    if not raw_asset.isdigit():
        return [], None
    asset = Asset.objects.select_related("category", "location").filter(pk=int(raw_asset)).first()
    if not asset:
        return [], None
    if not asset.is_borrowable:
        messages.warning(
            request,
            f"Aset {asset.asset_code} ({asset.name}) saat ini berstatus '{asset.get_status_display()}' "
            f"dengan kondisi '{asset.get_condition_display()}' sehingga tidak dapat dipinjam.",
        )
        return [], None
    return [asset.pk], asset


@login_required
def loan_list_view(request):
    """List loans with status/channel filters, search, and BORROWER ownership scoping."""
    services.sync_overdue_loans()

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    channel = (request.GET.get("channel") or "").strip()

    qs = (
        Loan.objects.select_related("borrower_user", "processed_by", "received_by")
        .annotate(item_count=Count("items"))
        .order_by("-created_at")
    )
    if not request.user.is_staff_lab:
        qs = qs.filter(borrower_user=request.user)

    if q:
        qs = qs.filter(
            Q(loan_number__icontains=q)
            | Q(borrower_name__icontains=q)
            | Q(borrower_identifier__icontains=q)
            | Q(purpose__icontains=q)
            | Q(items__asset__asset_code__icontains=q)
            | Q(items__asset__name__icontains=q)
        ).distinct()

    if status in Loan.Status.values:
        qs = qs.filter(status=status)
    if channel in Loan.Channel.values:
        qs = qs.filter(loan_channel=channel)

    page_obj = Paginator(qs, 12).get_page(request.GET.get("page"))

    return render(
        request,
        "loans/loan_list.html",
        {
            "page_obj": page_obj,
            "statuses": Loan.Status.choices,
            "channels": Loan.Channel.choices,
            "filters": {"q": q, "status": status, "channel": channel},
        },
    )


@login_required
def loan_request_view(request):
    """Submit an ONLINE loan request (channel=ONLINE, status=PENDING)."""
    initial = {}
    if request.method == "GET":
        preselected_ids, _ = _preselected_asset_initial(request)
        if preselected_ids:
            initial["assets"] = preselected_ids

    form = LoanOnlineRequestForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            loan = services.create_online_loan(
                borrower_user=request.user,
                asset_ids=[a.pk for a in form.cleaned_data["assets"]],
                borrow_date=form.cleaned_data["borrow_date"],
                due_date=form.cleaned_data["due_date"],
                purpose=form.cleaned_data["purpose"],
                notes=form.cleaned_data.get("notes", ""),
            )
            messages.success(
                request,
                f"Pengajuan peminjaman {loan.loan_number} berhasil dikirim dan menunggu persetujuan laboran.",
            )
            return redirect("loans:loan_detail", pk=loan.pk)
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))

    selected_ids = {str(v) for v in (request.POST.getlist("assets") if request.method == "POST" else initial.get("assets", []))}
    return render(
        request,
        "loans/loan_request.html",
        {
            "form": form,
            "available_assets": borrowable_assets_queryset(),
            "selected_asset_ids": selected_ids,
        },
    )


@role_required(*STAFF_ROLES)
def loan_walk_in_view(request):
    """Record a WALK_IN loan directly as ACTIVE (with optional linked BORROWER account)."""
    initial = {}
    preselected_asset = None
    if request.method == "GET":
        preselected_ids, preselected_asset = _preselected_asset_initial(request)
        if preselected_ids:
            initial["assets"] = preselected_ids

    form = LoanWalkInForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            loan = services.create_walk_in_loan(
                staff_user=request.user,
                asset_ids=[a.pk for a in form.cleaned_data["assets"]],
                borrow_date=form.cleaned_data["borrow_date"],
                due_date=form.cleaned_data["due_date"],
                purpose=form.cleaned_data["purpose"],
                borrower_user=form.cleaned_data.get("borrower_user"),
                borrower_name=form.cleaned_data["borrower_name"],
                borrower_identifier=form.cleaned_data["borrower_identifier"],
                borrower_contact=form.cleaned_data["borrower_contact"],
                notes=form.cleaned_data.get("notes", ""),
            )
            messages.success(
                request,
                f"Peminjaman Walk-In {loan.loan_number} berhasil dicatat (status: Sedang Dipinjam).",
            )
            return redirect("loans:loan_detail", pk=loan.pk)
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))

    borrowers_data = {
        str(u.pk): {
            "name": u.full_name or u.username,
            "identifier": u.identifier_number or u.username,
            "contact": u.phone_number or u.email,
        }
        for u in User.objects.filter(is_active=True, role=User.Role.BORROWER).only(
            "id", "full_name", "username", "identifier_number", "phone_number", "email"
        )
    }
    selected_ids = {str(v) for v in (request.POST.getlist("assets") if request.method == "POST" else initial.get("assets", []))}

    return render(
        request,
        "loans/loan_walk_in.html",
        {
            "form": form,
            "available_assets": borrowable_assets_queryset(),
            "selected_asset_ids": selected_ids,
            "preselected_asset": preselected_asset,
            "borrowers_data": borrowers_data,
        },
    )


@login_required
def loan_detail_view(request, pk: int):
    """Display loan details, items, timeline, and role/state-aware action controls."""
    services.sync_overdue_loans()
    loan = _get_accessible_loan_or_403(request, pk)

    is_staff = request.user.is_staff_lab
    is_owner = loan.borrower_user_id == request.user.pk

    can_approve = is_staff and loan.status == Loan.Status.PENDING
    can_reject = is_staff and loan.status == Loan.Status.PENDING
    can_handover = is_staff and loan.status == Loan.Status.APPROVED
    can_return = is_staff and loan.status in (Loan.Status.ACTIVE, Loan.Status.OVERDUE)
    can_cancel = (is_staff and loan.status in (Loan.Status.PENDING, Loan.Status.APPROVED)) or (
        is_owner and loan.status == Loan.Status.PENDING
    )

    return render(
        request,
        "loans/loan_detail.html",
        {
            "loan": loan,
            "items": loan.items.all(),
            "reject_form": LoanRejectForm() if can_reject else None,
            "can_approve": can_approve,
            "can_reject": can_reject,
            "can_handover": can_handover,
            "can_return": can_return,
            "can_cancel": can_cancel,
        },
    )


@role_required(*STAFF_ROLES)
@require_POST
def loan_approve_view(request, pk: int):
    """Approve a PENDING loan (optionally handing over immediately when handover_now=1)."""
    loan = get_object_or_404(Loan, pk=pk)
    handover_now = request.POST.get("handover_now") == "1"
    try:
        updated = services.approve_loan(loan, staff_user=request.user, handover_now=handover_now)
        if handover_now:
            messages.success(
                request,
                f"Peminjaman {updated.loan_number} disetujui dan langsung diserahkan (status: Sedang Dipinjam).",
            )
        else:
            messages.success(
                request,
                f"Peminjaman {updated.loan_number} disetujui. Silakan konfirmasi serah terima saat barang diambil.",
            )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("loans:loan_detail", pk=loan.pk)


@role_required(*STAFF_ROLES)
@require_POST
def loan_reject_view(request, pk: int):
    """Reject a PENDING loan with a mandatory reason."""
    loan = get_object_or_404(Loan, pk=pk)
    form = LoanRejectForm(request.POST)
    if form.is_valid():
        try:
            updated = services.reject_loan(
                loan,
                staff_user=request.user,
                reason=form.cleaned_data["rejection_reason"],
            )
            messages.success(request, f"Pengajuan peminjaman {updated.loan_number} telah ditolak.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    else:
        messages.error(request, "Alasan penolakan wajib diisi.")
    return redirect("loans:loan_detail", pk=loan.pk)


@role_required(*STAFF_ROLES)
@require_POST
def loan_handover_view(request, pk: int):
    """Hand over an APPROVED loan to the borrower (APPROVED -> ACTIVE)."""
    loan = get_object_or_404(Loan, pk=pk)
    try:
        updated = services.handover_loan(loan, staff_user=request.user)
        messages.success(
            request,
            f"Serah terima {updated.loan_number} berhasil dicatat. Seluruh aset kini berstatus Dipinjam.",
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("loans:loan_detail", pk=loan.pk)


@login_required
@require_POST
def loan_cancel_view(request, pk: int):
    """Cancel a PENDING (owner/staff) or APPROVED (staff) loan."""
    loan = _get_accessible_loan_or_403(request, pk)
    try:
        updated = services.cancel_loan(loan, actor=request.user)
        messages.success(request, f"Peminjaman {updated.loan_number} berhasil dibatalkan.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("loans:loan_detail", pk=loan.pk)


@role_required(*STAFF_ROLES)
def loan_return_view(request, pk: int):
    """Inspect each returned asset's condition and close an ACTIVE/OVERDUE loan."""
    services.sync_overdue_loans()
    loan = get_object_or_404(
        Loan.objects.select_related("borrower_user", "processed_by").prefetch_related(
            "items__asset__category", "items__asset__location"
        ),
        pk=pk,
    )
    if loan.status not in (Loan.Status.ACTIVE, Loan.Status.OVERDUE):
        messages.error(
            request,
            f"Pengembalian hanya dapat diproses untuk pinjaman aktif atau terlambat "
            f"(status saat ini: {loan.get_status_display()}).",
        )
        return redirect("loans:loan_detail", pk=loan.pk)

    items = list(loan.items.all())
    form = LoanReturnForm(request.POST or None, items=items)

    if request.method == "POST" and form.is_valid():
        try:
            result = services.process_loan_return(
                loan=loan,
                staff_user=request.user,
                item_inspections=form.build_inspections(),
            )
            created_reports = result["created_damage_reports"]
            if created_reports:
                codes = ", ".join(r.report_number for r in created_reports)
                messages.warning(
                    request,
                    f"Pengembalian {loan.loan_number} dicatat. Tiket laporan kerusakan otomatis dibuat "
                    f"untuk aset Rusak Berat: {codes}.",
                )
            else:
                messages.success(
                    request,
                    f"Pengembalian {loan.loan_number} berhasil dicatat. Seluruh aset kembali tersedia.",
                )
            return redirect("loans:loan_detail", pk=loan.pk)
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))

    return render(
        request,
        "loans/loan_return.html",
        {
            "loan": loan,
            "form": form,
            "item_rows": form.get_item_rows(),
        },
    )
