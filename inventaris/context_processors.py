def user_context(request):
    """Sediakan user_role dan user_profile secara aman di seluruh template."""
    if not request.user.is_authenticated:
        return {'user_role': None, 'user_profile': None}

    profile = getattr(request.user, 'profile', None)
    if profile:
        role = profile.role
    elif request.user.is_superuser:
        role = 'ADMIN'
    else:
        role = None

    return {
        'user_role': role,
        'user_profile': profile,
    }
