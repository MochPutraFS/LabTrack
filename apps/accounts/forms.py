"""Forms for authentication, borrower self-registration, profile, and admin user management."""

from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

User = get_user_model()

INPUT_CLASS = (
    "w-full min-h-11 sm:min-h-0 rounded-lg border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-800 "
    "placeholder:text-slate-400 focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20 "
    "disabled:bg-slate-100 disabled:text-slate-500 disabled:cursor-not-allowed"
)
SELECT_CLASS = INPUT_CLASS
CHECKBOX_CLASS = "h-4 w-4 rounded border-slate-300 text-teal-700 focus:ring-teal-600"


class LoginForm(AuthenticationForm):
    """Allow login with either username or email address."""

    username = forms.CharField(
        label="Username atau Email",
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASS,
                "placeholder": "Username atau email",
                "autocomplete": "username",
                "autocorrect": "off",
                "autocapitalize": "none",
                "spellcheck": "false",
                "autofocus": True,
            }
        ),
    )
    password = forms.CharField(
        label="Kata Sandi",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": INPUT_CLASS,
                "placeholder": "Masukkan kata sandi",
                "autocomplete": "current-password",
            }
        ),
    )

    error_messages = {
        "invalid_login": "Username/email atau kata sandi tidak valid.",
        "inactive": "Akun ini sedang dinonaktifkan. Hubungi Admin laboratorium.",
    }

    def clean(self):
        identifier = (self.cleaned_data.get("username") or "").strip()
        password = self.cleaned_data.get("password")

        if identifier and password:
            lookup_username = identifier
            if "@" in identifier:
                matched = User.objects.filter(email__iexact=identifier).first()
                if matched:
                    lookup_username = matched.username

            self.user_cache = authenticate(
                self.request,
                username=lookup_username,
                password=password,
            )
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class BorrowerRegistrationForm(UserCreationForm):
    """Self-registration form restricted strictly to BORROWER role (FR-01.2)."""

    full_name = forms.CharField(
        label="Nama Lengkap",
        max_length=150,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "autocomplete": "name"}),
    )
    identifier_number = forms.CharField(
        label="NIM / NIP",
        max_length=50,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASS,
                "placeholder": "Contoh: H071241099",
                "autocorrect": "off",
                "autocapitalize": "characters",
                "spellcheck": "false",
            }
        ),
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={
                "class": INPUT_CLASS,
                "autocomplete": "email",
                "autocorrect": "off",
                "autocapitalize": "none",
                "spellcheck": "false",
            }
        ),
    )
    phone_number = forms.CharField(
        label="Nomor HP / WhatsApp",
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "autocomplete": "tel", "inputmode": "tel"}),
    )
    department = forms.CharField(
        label="Program Studi / Unit",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "Contoh: Sistem Informasi"}),
    )

    class Meta:
        model = User
        fields = (
            "username",
            "full_name",
            "identifier_number",
            "email",
            "phone_number",
            "department",
            "password1",
            "password2",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Username"
        self.fields["username"].widget.attrs.update(
            {
                "class": INPUT_CLASS,
                "autocomplete": "username",
                "autocorrect": "off",
                "autocapitalize": "none",
                "spellcheck": "false",
            }
        )
        self.fields["password1"].label = "Kata Sandi"
        self.fields["password1"].widget.attrs.update({"class": INPUT_CLASS, "autocomplete": "new-password"})
        self.fields["password2"].label = "Konfirmasi Kata Sandi"
        self.fields["password2"].widget.attrs.update({"class": INPUT_CLASS, "autocomplete": "new-password"})

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Email ini sudah terdaftar.")
        return email

    def clean_identifier_number(self):
        identifier = self.cleaned_data["identifier_number"].strip()
        if User.objects.filter(identifier_number__iexact=identifier).exists():
            raise forms.ValidationError("NIM/NIP ini sudah terdaftar pada akun lain.")
        return identifier

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.BORROWER
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    """Self-service profile update form."""

    class Meta:
        model = User
        fields = ("full_name", "email", "identifier_number", "phone_number", "department")
        labels = {
            "full_name": "Nama Lengkap",
            "email": "Email",
            "identifier_number": "NIM / NIP / ID Staf",
            "phone_number": "Nomor Kontak",
            "department": "Unit / Program Studi",
        }
        widgets = {
            "full_name": forms.TextInput(attrs={"class": INPUT_CLASS, "autocomplete": "name"}),
            "email": forms.EmailInput(attrs={"class": INPUT_CLASS, "autocomplete": "email"}),
            "identifier_number": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "phone_number": forms.TextInput(attrs={"class": INPUT_CLASS, "autocomplete": "tel"}),
            "department": forms.TextInput(attrs={"class": INPUT_CLASS}),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Email sudah digunakan oleh akun lain.")
        return email

    def clean_identifier_number(self):
        identifier = (self.cleaned_data.get("identifier_number") or "").strip()
        if identifier and User.objects.filter(identifier_number__iexact=identifier).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("NIM/NIP/ID Staf sudah digunakan oleh akun lain.")
        return identifier or None


class AdminUserCreateForm(UserCreationForm):
    """Admin form to create a user with any role."""

    class Meta:
        model = User
        fields = (
            "username",
            "full_name",
            "email",
            "role",
            "identifier_number",
            "phone_number",
            "department",
            "is_active",
            "password1",
            "password2",
        )
        labels = {
            "username": "Username",
            "full_name": "Nama Lengkap",
            "email": "Email",
            "role": "Peran (Role)",
            "identifier_number": "NIM / NIP / ID Staf",
            "phone_number": "Nomor Kontak",
            "department": "Unit / Program Studi",
            "is_active": "Akun Aktif",
        }
        widgets = {
            "username": forms.TextInput(attrs={"class": INPUT_CLASS, "autocorrect": "off", "autocapitalize": "none"}),
            "full_name": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "email": forms.EmailInput(attrs={"class": INPUT_CLASS}),
            "role": forms.Select(attrs={"class": SELECT_CLASS}),
            "identifier_number": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "phone_number": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "department": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "is_active": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Kata Sandi"
        self.fields["password1"].widget.attrs.update({"class": INPUT_CLASS, "autocomplete": "new-password"})
        self.fields["password2"].label = "Konfirmasi Kata Sandi"
        self.fields["password2"].widget.attrs.update({"class": INPUT_CLASS, "autocomplete": "new-password"})

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Email sudah digunakan oleh akun lain.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = user.role in (User.Role.ADMIN, User.Role.LABORAN)
        if commit:
            user.save()
        return user


class AdminUserUpdateForm(forms.ModelForm):
    """Admin form to update an existing user's role, status, and metadata."""

    new_password = forms.CharField(
        label="Atur Ulang Kata Sandi (Opsional)",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                "class": INPUT_CLASS,
                "placeholder": "Kosongkan jika tidak ingin mengubah kata sandi",
                "autocomplete": "new-password",
            }
        ),
    )

    class Meta:
        model = User
        fields = (
            "full_name",
            "email",
            "role",
            "identifier_number",
            "phone_number",
            "department",
            "is_active",
        )
        labels = {
            "full_name": "Nama Lengkap",
            "email": "Email",
            "role": "Peran (Role)",
            "identifier_number": "NIM / NIP / ID Staf",
            "phone_number": "Nomor Kontak",
            "department": "Unit / Program Studi",
            "is_active": "Akun Aktif",
        }
        widgets = {
            "full_name": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "email": forms.EmailInput(attrs={"class": INPUT_CLASS}),
            "role": forms.Select(attrs={"class": SELECT_CLASS}),
            "identifier_number": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "phone_number": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "department": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "is_active": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS}),
        }

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_user = current_user

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Email sudah digunakan oleh akun lain.")
        return email

    def clean_is_active(self):
        is_active = self.cleaned_data["is_active"]
        if self.current_user and self.instance.pk == self.current_user.pk and not is_active:
            raise forms.ValidationError("Anda tidak dapat menonaktifkan akun Anda sendiri.")
        return is_active

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = user.role in (User.Role.ADMIN, User.Role.LABORAN)
        new_pw = (self.cleaned_data.get("new_password") or "").strip()
        if new_pw:
            user.set_password(new_pw)
        if commit:
            user.save()
        return user
