"""Automated tests for Module A — Authentication & RBAC (TC-01 to TC-06)."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditLog
from apps.inventory.models import Asset, Category, Location
from apps.loans.models import Loan, LoanItem

User = get_user_model()


class ModuleAAuthAndRBACTests(TestCase):
    """Covers TC-01 through TC-06 from docs/08-Test-Plan-dan-QA.md."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin_auth",
            email="admin_auth@labtrack.local",
            password="Password123!",
            full_name="Admin Auth",
            role=User.Role.ADMIN,
            is_staff=True,
        )
        cls.laboran = User.objects.create_user(
            username="laboran_auth",
            email="laboran_auth@labtrack.local",
            password="Password123!",
            full_name="Laboran Auth",
            role=User.Role.LABORAN,
            is_staff=True,
        )
        cls.borrower_a = User.objects.create_user(
            username="mhs_a",
            email="mhs_a@labtrack.local",
            password="Password123!",
            full_name="Mahasiswa A",
            role=User.Role.BORROWER,
            identifier_number="H071241101",
            phone_number="081200000101",
        )
        cls.borrower_b = User.objects.create_user(
            username="mhs_b",
            email="mhs_b@labtrack.local",
            password="Password123!",
            full_name="Mahasiswa B",
            role=User.Role.BORROWER,
            identifier_number="H071241102",
            phone_number="081200000102",
        )
        cat = Category.objects.create(code="KOM", name="Komputer", default_useful_life_years=5)
        loc = Location.objects.create(code="LAB-RPL", name="Lab RPL")
        asset = Asset.objects.create(
            asset_code="LAB-KOM-2026-0001",
            name="Laptop Praktikum 01",
            category=cat,
            location=loc,
            acquisition_date=date(2025, 1, 10),
            acquisition_cost=Decimal("10000000.00"),
            useful_life_years=5,
            salvage_value=Decimal("1000000.00"),
        )
        today = timezone.localdate()
        cls.other_loan = Loan.objects.create(
            loan_number="LOAN-20261128-9001",
            loan_channel=Loan.Channel.ONLINE,
            borrower_user=cls.borrower_a,
            borrower_name=cls.borrower_a.full_name,
            borrower_identifier=cls.borrower_a.identifier_number,
            borrower_contact=cls.borrower_a.phone_number,
            purpose="Praktikum Basis Data",
            borrow_date=today,
            due_date=today + timedelta(days=2),
            status=Loan.Status.PENDING,
        )
        LoanItem.objects.create(
            loan=cls.other_loan,
            asset=asset,
            condition_on_checkout=Asset.Condition.GOOD,
        )

    def test_tc01_login_valid_redirects_to_role_dashboard(self):
        """TC-01: Valid login redirects to role-appropriate dashboard (by username or email)."""
        for identifier, expected_heading in [
            ("admin_auth", "Dashboard Laboratorium"),
            ("laboran_auth", "Dashboard Laboratorium"),
            ("mhs_a@labtrack.local", "Peminjaman Terkini Anda"),
        ]:
            resp = self.client.post(
                reverse("accounts:login"),
                {"username": identifier, "password": "Password123!"},
                follow=True,
            )
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, expected_heading)
            # Logout must reject GET and accept POST
            self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
            self.assertEqual(self.client.post(reverse("accounts:logout")).status_code, 302)

    def test_tc02_login_wrong_password_stays_on_login_with_error(self):
        """TC-02: Invalid password stays on /accounts/login/ with error message."""
        resp = self.client.post(
            reverse("accounts:login"),
            {"username": "admin_auth", "password": "WrongPassword!"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Username/email atau kata sandi tidak valid.")

    def test_tc03_self_registration_creates_borrower_account(self):
        """TC-03: Public self-registration creates a BORROWER user and records audit log."""
        resp = self.client.post(
            reverse("accounts:register"),
            {
                "username": "mhs_baru_sintetis",
                "full_name": "Nadia Putri Sintetis",
                "identifier_number": "H071241998",
                "email": "nadia.sintetis@labtrack.local",
                "phone_number": "081299998888",
                "department": "Sistem Informasi",
                "password1": "LabTrackPass2026!",
                "password2": "LabTrackPass2026!",
            },
        )
        self.assertEqual(resp.status_code, 302)
        new_user = User.objects.get(username="mhs_baru_sintetis")
        self.assertEqual(new_user.role, User.Role.BORROWER)
        self.assertFalse(new_user.is_staff)
        self.assertTrue(
            AuditLog.objects.filter(action="USER_REGISTERED", entity_id=str(new_user.pk)).exists()
        )

    def test_tc04_admin_menu_protected_from_laboran(self):
        """TC-04: LABORAN accessing GET /accounts/users/ is rejected with HTTP 403."""
        self.client.force_login(self.laboran)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("accounts:user_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("core:audit_log_list")).status_code, 403)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 200)

    def test_tc05_staff_menu_protected_from_borrower(self):
        """TC-05: BORROWER accessing GET /loans/walk-in/ is rejected with HTTP 403."""
        self.client.force_login(self.borrower_a)
        self.assertEqual(self.client.get(reverse("loans:loan_walk_in")).status_code, 403)
        self.assertEqual(self.client.get(reverse("inventory:asset_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("maintenance:schedule_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("reports:condition_report")).status_code, 403)

    def test_tc06_idor_protection_on_other_borrower_loan_detail(self):
        """TC-06: BORROWER accessing another user's /loans/<pk>/ is rejected with HTTP 403."""
        self.client.force_login(self.borrower_b)
        resp = self.client.get(reverse("loans:loan_detail", args=[self.other_loan.pk]))
        self.assertEqual(resp.status_code, 403)
        # Also cannot cancel another user's loan
        cancel_resp = self.client.post(reverse("loans:loan_cancel", args=[self.other_loan.pk]))
        self.assertEqual(cancel_resp.status_code, 403)
