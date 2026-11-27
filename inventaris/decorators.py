from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def role_required(*allowed_roles):
    """Batasi akses view untuk peran tertentu (superuser selalu diizinkan)."""
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            profile = getattr(request.user, 'profile', None)
            if profile and profile.role in allowed_roles:
                return view_func(request, *args, **kwargs)
            messages.error(request, 'Anda tidak memiliki hak akses untuk halaman ini.')
            return redirect('dashboard')
        return _wrapped
    return decorator
