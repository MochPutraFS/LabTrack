"""RBAC permission decorators and CBV mixins for LabTrack."""

from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

STAFF_ROLES = ("ADMIN", "LABORAN")


def role_required(*allowed_roles: str):
    """Restrict a function-based view to authenticated users with an allowed role."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if allowed_roles and request.user.role not in allowed_roles:
                raise PermissionDenied("Anda tidak memiliki hak akses untuk halaman ini.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


class RoleRequiredMixin(LoginRequiredMixin):
    """Restrict a class-based view to authenticated users with an allowed role."""

    allowed_roles: tuple[str, ...] = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.allowed_roles and request.user.role not in self.allowed_roles:
            raise PermissionDenied("Anda tidak memiliki hak akses untuk halaman ini.")
        return super().dispatch(request, *args, **kwargs)
