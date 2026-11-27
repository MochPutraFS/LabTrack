from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

User = get_user_model()


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    next_url = request.POST.get('next') or request.GET.get('next', '')
    context = {
        'username': '',
        'next': next_url,
        'error_message': '',
        'field_errors': {},
    }

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        context['username'] = username

        field_errors = {}
        if not username:
            field_errors['username'] = 'Username wajib diisi.'
        if not password:
            field_errors['password'] = 'Password wajib diisi.'

        if field_errors:
            context['field_errors'] = field_errors
            context['error_message'] = 'Mohon lengkapi username dan password Anda.'
            return render(request, 'inventaris/auth/login.html', context)

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect('dashboard')

        # Bedakan akun nonaktif dengan kredensial salah agar pesan error spesifik
        existing = User.objects.filter(username=username).first()
        if existing and not existing.is_active and existing.check_password(password):
            context['error_message'] = 'Akun Anda saat ini tidak aktif. Hubungi admin laboratorium.'
        else:
            context['error_message'] = 'Username atau password salah. Silakan periksa kembali kredensial Anda.'

    return render(request, 'inventaris/auth/login.html', context)


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, 'Anda telah berhasil keluar dari sistem.')
    return redirect('login')


@login_required
def dashboard(request):
    return render(request, 'inventaris/dashboard.html')
