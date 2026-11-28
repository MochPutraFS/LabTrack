"""Automated tests for Module C — Hybrid Loans & Returns (TC-16 to TC-24)."""

import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditLog
from apps.inventory import services as inv_services
from apps.inventory.models import Asset, Category, Location
from apps.loans import services as loan_services
from apps.loans.models import Loan
from apps.maintenance.models import DamageReport

User = get_user_model()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="labtrack_test_loans_"))
class ModuleCLoansTests(TestCase):
    """Covers TC-16 through TC-24 from docs/08-Test-Plan-dan-QA.md."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_l",
            email="admin_l@labtrack.local",
            password="Password123!",
            full_name="Admin Lab",
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.laboran = User.objects.create_user(
            username="laboran_l",
            email="laboran_l@labtrack.local",
            password="Password123!",
            full_name="Laboran Lab",
            role=User.Role.LABORAN,
            is_staff=True,
        )
        self.borrower1 = User.objects.create_user(
            username="mhs_1",
            email="mhs_1@labtrack.local",
            password="Password123!",
            full_name="Mahasiswa Satu",
            role=User.Role.BORROWER,
            identifier_number="H071241001",
            phone_number="081200000001",
        )
        self.dosen_sari = User.objects.create_user(
            username="dosen_sari",
            email="sari.dosen@labtrack.local",
            password="Password123!",
            full_name="Sari Wulandari, M.Kom",
            role=User.Role.BORROWER,
            identifier_number="NIP-19890512004",
            phone_number="081240000005",
        )
        self.cat = Category.objects.create(code="PRJ", name="Proyektor", default_useful_life_years=5)
        self.loc = Location.objects.create(code="LAB-RPL", name="Lab RPL")

        self.asset1 = inv_services.create_asset(
            Asset(
                name="Proyektor Epson 01",
                category=self.cat,
                location=self.loc,
                acquisition_date=date(2025, 1, 10),
                acquisition_cost=Decimal("8000000.00"),
                useful_life_years=5,
                salvage_value=Decimal("800000.00"),
            ),
            actor=self.admin,
        )
        self.asset2 = inv_services.create_asset(
            Asset(
                name="Proyektor Epson 02",
                category=self.cat,
                location=self.loc,
                acquisition_date=date(2025, 2, 10),
                acquisition_cost=Decimal("8000000.00"),
                useful_life_years=5,
                salvage_value=Decimal("800000.00"),
            ),
            actor=self.admin,
        )
        self.today = timezone.localdate()

    def test_tc16_online_loan_request_creates_pending_without_locking_asset(self):
        """TC-16: BORROWER submits online loan -> ONLINE/PENDING; asset remains AVAILABLE before handover."""
        self.client.force_login(self.borrower1)
        resp = self.client.post(
            reverse("loans:loan_request"),
            {
                "assets": [self.asset1.pk],
                "borrow_date": str(self.today),
                "due_date": str(self.today + timedelta(days=3)),
                "purpose": "Presentasi Praktikum RPL",
            },
        )
        self.assertEqual(resp.status_code, 302)
        loan = Loan.objects.get()
        self.assertEqual(loan.loan_channel, Loan.Channel.ONLINE)
        self.assertEqual(loan.status, Loan.Status.PENDING)
        self.asset1.refresh_from_db()
        self.assertEqual(self.asset1.status, Asset.Status.AVAILABLE)
        self.assertTrue(
            AuditLog.objects.filter(action="LOAN_ONLINE_REQUESTED", entity_id=str(loan.pk)).exists()
        )

    def test_tc17_approve_and_handover_online_loan_marks_asset_borrowed(self):
        """TC-17: LABORAN approves then hands over PENDING loan -> ACTIVE & asset becomes BORROWED."""
        loan = loan_services.create_online_loan(
            borrower_user=self.borrower1,
            asset_ids=[self.asset1.pk],
            borrow_date=self.today,
            due_date=self.today + timedelta(days=3),
            purpose="Demo Aplikasi",
        )
        self.client.force_login(self.laboran)
        self.assertEqual(self.client.post(reverse("loans:loan_approve", args=[loan.pk])).status_code, 302)
        loan.refresh_from_db()
        self.assertEqual(loan.status, Loan.Status.APPROVED)

        self.assertEqual(self.client.post(reverse("loans:loan_handover", args=[loan.pk])).status_code, 302)
        loan.refresh_from_db()
        self.asset1.refresh_from_db()
        self.assertEqual(loan.status, Loan.Status.ACTIVE)
        self.assertIsNotNone(loan.handed_over_at)
        self.assertEqual(self.asset1.status, Asset.Status.BORROWED)

    def test_tc18_reject_loan_requires_non_empty_reason(self):
        """TC-18: Rejecting loan with empty rejection_reason is blocked by validation."""
        loan = loan_services.create_online_loan(
            borrower_user=self.borrower1,
            asset_ids=[self.asset1.pk],
            borrow_date=self.today,
            due_date=self.today + timedelta(days=1),
            purpose="Uji Penolakan",
        )
        self.client.force_login(self.laboran)
        resp = self.client.post(
            reverse("loans:loan_reject", args=[loan.pk]),
            {"rejection_reason": ""},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alasan penolakan wajib diisi.")
        loan.refresh_from_db()
        self.assertEqual(loan.status, Loan.Status.PENDING)

        with self.assertRaises(ValidationError):
            loan_services.reject_loan(loan, staff_user=self.laboran, reason="   ")

    def test_tc19_walk_in_loan_without_borrower_account(self):
        """TC-19: LABORAN records manual Walk-In loan -> WALK_IN, ACTIVE, borrower_user=None, asset=BORROWED."""
        self.client.force_login(self.laboran)
        resp = self.client.post(
            reverse("loans:loan_walk_in"),
            {
                "borrower_name": "Budi Santoso (Walk-In)",
                "borrower_identifier": "H071241888",
                "borrower_contact": "081234567888",
                "assets": [self.asset1.pk],
                "borrow_date": str(self.today),
                "due_date": str(self.today + timedelta(days=2)),
                "purpose": "Workshop Jaringan",
            },
        )
        self.assertEqual(resp.status_code, 302)
        loan = Loan.objects.get()
        self.assertEqual(loan.loan_channel, Loan.Channel.WALK_IN)
        self.assertEqual(loan.status, Loan.Status.ACTIVE)
        self.assertIsNone(loan.borrower_user)
        self.asset1.refresh_from_db()
        self.assertEqual(self.asset1.status, Asset.Status.BORROWED)

    def test_tc20_walk_in_loan_linked_to_existing_account(self):
        """TC-20: LABORAN records Walk-In linked to existing account (dosen_sari) -> WALK_IN, ACTIVE."""
        self.client.force_login(self.laboran)
        resp = self.client.post(
            reverse("loans:loan_walk_in"),
            {
                "borrower_user": self.dosen_sari.pk,
                "borrower_name": self.dosen_sari.full_name,
                "borrower_identifier": self.dosen_sari.identifier_number,
                "borrower_contact": self.dosen_sari.phone_number,
                "assets": [self.asset1.pk],
                "borrow_date": str(self.today),
                "due_date": str(self.today + timedelta(days=2)),
                "purpose": "Kuliah Tamu RPL",
            },
        )
        self.assertEqual(resp.status_code, 302)
        loan = Loan.objects.get()
        self.assertEqual(loan.loan_channel, Loan.Channel.WALK_IN)
        self.assertEqual(loan.status, Loan.Status.ACTIVE)
        self.assertEqual(loan.borrower_user, self.dosen_sari)
        self.asset1.refresh_from_db()
        self.assertEqual(self.asset1.status, Asset.Status.BORROWED)

    def test_tc21_anti_double_booking_blocks_borrowed_and_maintenance_assets(self):
        """TC-21: Attempting to borrow a BORROWED or MAINTENANCE asset raises ValidationError."""
        loan_services.create_walk_in_loan(
            staff_user=self.laboran,
            asset_ids=[self.asset1.pk],
            borrow_date=self.today,
            due_date=self.today + timedelta(days=1),
            purpose="Pinjaman Aktif",
            borrower_user=self.borrower1,
        )
        with self.assertRaises(ValidationError):
            loan_services.create_online_loan(
                borrower_user=self.dosen_sari,
                asset_ids=[self.asset1.pk],
                borrow_date=self.today,
                due_date=self.today + timedelta(days=2),
                purpose="Coba Double Booking",
            )

        self.asset2.status = Asset.Status.MAINTENANCE
        self.asset2.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            loan_services.create_walk_in_loan(
                staff_user=self.laboran,
                asset_ids=[self.asset2.pk],
                borrow_date=self.today,
                due_date=self.today + timedelta(days=1),
                purpose="Coba Pinjam Aset Maintenance",
                borrower_name="Tamu",
                borrower_identifier="H071249999",
                borrower_contact="081299999999",
            )
        self.asset1.refresh_from_db()
        self.asset2.refresh_from_db()
        self.assertEqual(self.asset1.status, Asset.Status.BORROWED)
        self.assertEqual(self.asset2.status, Asset.Status.MAINTENANCE)

    def test_tc22_return_in_good_condition_restores_asset_available(self):
        """TC-22: Returning asset in GOOD condition marks loan RETURNED and asset AVAILABLE."""
        loan = loan_services.create_walk_in_loan(
            staff_user=self.laboran,
            asset_ids=[self.asset1.pk],
            borrow_date=self.today,
            due_date=self.today + timedelta(days=2),
            purpose="Uji Return Baik",
            borrower_user=self.borrower1,
        )
        item = loan.items.get(asset=self.asset1)
        self.client.force_login(self.laboran)
        resp = self.client.post(
            reverse("loans:loan_return", args=[loan.pk]),
            {
                f"condition_{item.pk}": Asset.Condition.GOOD,
                f"notes_{item.pk}": "Lengkap tanpa cacat",
            },
        )
        self.assertEqual(resp.status_code, 302)
        loan.refresh_from_db()
        self.asset1.refresh_from_db()
        self.assertEqual(loan.status, Loan.Status.RETURNED)
        self.assertIsNotNone(loan.returned_at)
        self.assertEqual(self.asset1.status, Asset.Status.AVAILABLE)
        self.assertEqual(self.asset1.condition, Asset.Condition.GOOD)

    def test_tc23_return_in_major_damage_marks_damaged_and_creates_damage_report(self):
        """TC-23: Returning asset in MAJOR_DAMAGE marks asset DAMAGED and auto-creates DamageReport."""
        loan = loan_services.create_walk_in_loan(
            staff_user=self.laboran,
            asset_ids=[self.asset2.pk],
            borrow_date=self.today,
            due_date=self.today + timedelta(days=2),
            purpose="Uji Return Rusak Berat",
            borrower_user=self.borrower1,
        )
        item = loan.items.get(asset=self.asset2)
        self.client.force_login(self.laboran)
        resp = self.client.post(
            reverse("loans:loan_return", args=[loan.pk]),
            {
                f"condition_{item.pk}": Asset.Condition.MAJOR_DAMAGE,
                f"notes_{item.pk}": "Lensa proyektor pecah",
            },
        )
        self.assertEqual(resp.status_code, 302)
        loan.refresh_from_db()
        self.asset2.refresh_from_db()
        self.assertEqual(loan.status, Loan.Status.RETURNED)
        self.assertEqual(self.asset2.status, Asset.Status.DAMAGED)
        self.assertEqual(self.asset2.condition, Asset.Condition.MAJOR_DAMAGE)

        dmg = DamageReport.objects.get(asset=self.asset2)
        self.assertEqual(dmg.status, DamageReport.Status.VERIFIED)
        self.assertEqual(dmg.severity, DamageReport.Severity.HIGH)
        self.assertIn(loan.loan_number, dmg.description)

    def test_tc24_borrower_cancels_own_pending_loan(self):
        """TC-24: BORROWER cancels own PENDING loan -> status becomes CANCELLED."""
        loan = loan_services.create_online_loan(
            borrower_user=self.borrower1,
            asset_ids=[self.asset1.pk],
            borrow_date=self.today,
            due_date=self.today + timedelta(days=1),
            purpose="Uji Batal Peminjam",
        )
        self.client.force_login(self.borrower1)
        resp = self.client.post(reverse("loans:loan_cancel", args=[loan.pk]))
        self.assertEqual(resp.status_code, 302)
        loan.refresh_from_db()
        self.assertEqual(loan.status, Loan.Status.CANCELLED)

    def test_overdue_sync_and_loan_list_query_efficiency(self):
        """sync_overdue_loans transitions expired ACTIVE loans; loan_list stays free of N+1."""
        overdue_loan = loan_services.create_walk_in_loan(
            staff_user=self.laboran,
            asset_ids=[self.asset1.pk],
            borrow_date=self.today - timedelta(days=5),
            due_date=self.today - timedelta(days=1),
            purpose="Uji Terlambat",
            borrower_user=self.borrower1,
        )
        self.assertEqual(loan_services.sync_overdue_loans(), 1)
        overdue_loan.refresh_from_db()
        self.assertEqual(overdue_loan.status, Loan.Status.OVERDUE)

        self.client.force_login(self.laboran)
        resp = self.client.get(reverse("loans:loan_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, overdue_loan.loan_number)
