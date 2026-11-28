"""Views for authentication, profile management, and Admin user CRUD."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.forms import (
    AdminUserCreateForm,
    AdminUserUpdateForm,
    BorrowerRegistrationForm,
    LoginForm,
    ProfileForm,
)
from apps.core.permissions import role_required
from apps.core.services import log_audit

User = get_user_model()


class LabTrackLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["show_demo_hint"] = settings.DEBUG
        return ctx


class LabTrackLogoutView(LogoutView):
    http_method_names = ["post", "options"]


def register_view(request):
    """Self-registration for BORROWER accounts."""
    if request.user.is_authenticated:
        return redirect("inventory:asset_list")

    form = BorrowerRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        log_audit(
            actor=user,
            action="USER_REGISTERED",
            entity_type="User",
            entity_id=user.pk,
            metadata={"username": user.username, "role": user.role},
        )
        login(request, user)
        messages.success(request, f"Selamat datang, {user.full_name}! Akun Peminjam berhasil dibuat.")
        return redirect("inventory:asset_list")

    return render(request, "accounts/register.html", {"form": form})


@login_required
def profile_view(request):
    """View and update the signed-in user's own profile."""
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profil berhasil diperbarui.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})


@role_required(User.Role.ADMIN)
def user_list_view(request):
    """Admin-only paginated directory of all LabTrack users."""
    q = (request.GET.get("q") or "").strip()
    role = (request.GET.get("role") or "").strip()
    status = (request.GET.get("status") or "").strip()

    qs = User.objects.all()
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(full_name__icontains=q)
            | Q(email__icontains=q)
            | Q(identifier_number__icontains=q)
        )
    if role in User.Role.values:
        qs = qs.filter(role=role)
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)

    page_obj = Paginator(qs, 15).get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/user_list.html",
        {
            "page_obj": page_obj,
            "roles": User.Role.choices,
            "q": q,
            "selected_role": role,
            "selected_status": status,
        },
    )


@role_required(User.Role.ADMIN)
def user_create_view(request):
    """Admin-only view to create a new user of any role."""
    form = AdminUserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        log_audit(
            actor=request.user,
            action="USER_CREATED",
            entity_type="User",
            entity_id=user.pk,
            metadata={"username": user.username, "role": user.role, "is_active": user.is_active},
        )
        messages.success(request, f"Pengguna {user.full_name} ({user.get_role_display()}) berhasil ditambahkan.")
        return redirect("accounts:user_list")

    return render(request, "accounts/user_form.html", {"form": form, "is_edit": False})


@role_required(User.Role.ADMIN)
def user_edit_view(request, pk: int):
    """Admin-only view to edit a user's role, status, and profile."""
    target_user = get_object_or_404(User, pk=pk)
    old_role = target_user.role
    old_active = target_user.is_active

    form = AdminUserUpdateForm(request.POST or None, instance=target_user, current_user=request.user)
    if request.method == "POST" and form.is_valid():
        updated = form.save()
        log_audit(
            actor=request.user,
            action="USER_UPDATED",
            entity_type="User",
            entity_id=updated.pk,
            metadata={
                "username": updated.username,
                "old_role": old_role,
                "new_role": updated.role,
                "old_active": old_active,
                "new_active": updated.is_active,
            },
        )
        messages.success(request, f"Data pengguna {updated.full_name} berhasil diperbarui.")
        return redirect("accounts:user_list")

    return render(
        request,
        "accounts/user_form.html",
        {"form": form, "is_edit": True, "target_user": target_user},
    )
