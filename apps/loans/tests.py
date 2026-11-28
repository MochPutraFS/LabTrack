"""Automated tests for Session 3: Hybrid Loans (Online & Walk-In), Returns, RBAC & State Machine."""

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
class Session3LoansTests(TestCase):
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
        self.borrower2 = User.objects.create_user(
            username="mhs_2",
            email="mhs_2@labtrack.local",
            password="Password123!",
            full_name="Mahasiswa Dua",
            role=User.Role.BORROWER,
            identifier_number="H071241002",
            phone_number="081200000002",
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

    def test_online_loan_lifecycle_and_idor_protection(self):
        # Borrower1 requests ONLINE loan
        self.client.force_login(self.borrower1)
        resp = self.client.post(
            reverse("loans:loan_request"),
            {
                "assets": [self.asset1.pk],
                "borrow_date": str(self.today),
                "due_date": str(self.today + timedelta(days=3)),
                "purpose": "Presentasi Praktikum",
            },
        )
        self.assertEqual(resp.status_code, 302)
        loan = Loan.objects.get()
        self.assertEqual(loan.loan_channel, Loan.Channel.ONLINE)
        self.assertEqual(loan.status, Loan.Status.PENDING)
        self.assertTrue(AuditLog.objects.filter(action="LOAN_ONLINE_REQUESTED", entity_id=str(loan.pk)).exists())

        # Asset remains AVAILABLE while PENDING
        self.asset1.refresh_from_db()
        self.assertEqual(self.asset1.status, Asset.Status.AVAILABLE)

        # IDOR: Borrower2 cannot view Borrower1's loan detail or see it in loan_list
        self.client.force_login(self.borrower2)
        self.assertEqual(self.client.get(reverse("loans:loan_detail", args=[loan.pk])).status_code, 403)
        list_resp = self.client.get(reverse("loans:loan_list"))
        self.assertNotContains(list_resp, loan.loan_number)

        # RBAC: Borrower1 cannot access walk-in or approve
        self.client.force_login(self.borrower1)
        self.assertEqual(self.client.get(reverse("loans:loan_walk_in")).status_code, 403)
        self.assertEqual(self.client.post(reverse("loans:loan_approve", args=[loan.pk])).status_code, 403)

        # Laboran approves (APPROVED), then hands over (ACTIVE)
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

        # Anti double-booking: asset1 cannot be borrowed again while BORROWED
        with self.assertRaises(ValidationError):
            loan_services.create_walk_in_loan(
                staff_user=self.laboran,
                asset_ids=[self.asset1.pk],
                borrow_date=self.today,
                due_date=self.today + timedelta(days=1),
                purpose="Coba Double Booking",
                borrower_name="Tamu",
                borrower_identifier="H071249999",
                borrower_contact="081299999999",
            )

    def test_walk_in_without_account_and_qr_preselect(self):
        self.client.force_login(self.laboran)

        # QR Scan shows Walk-In button for staff
        scan_resp = self.client.get(reverse("asset_qr_scan", args=[self.asset1.asset_code]))
        self.assertContains(scan_resp, f"?asset={self.asset1.pk}")

        # Walk-In GET preselects ?asset=<id>
        get_resp = self.client.get(reverse("loans:loan_walk_in") + f"?asset={self.asset1.pk}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertContains(get_resp, self.asset1.asset_code)

        # Walk-In POST without borrower_user (manual guest identity)
        post_resp = self.client.post(
            reverse("loans:loan_walk_in"),
            {
                "borrower_name": "Budi Santoso (Walk-In)",
                "borrower_identifier": "H071241888",
                "borrower_contact": "081234567888",
                "assets": [self.asset1.pk, self.asset2.pk],
                "borrow_date": str(self.today),
                "due_date": str(self.today + timedelta(days=2)),
                "purpose": "Workshop RPL",
            },
        )
        self.assertEqual(post_resp.status_code, 302)
        loan = Loan.objects.get()
        self.assertEqual(loan.loan_channel, Loan.Channel.WALK_IN)
        self.assertEqual(loan.status, Loan.Status.ACTIVE)
        self.assertIsNone(loan.borrower_user)
        self.asset1.refresh_from_db()
        self.asset2.refresh_from_db()
        self.assertEqual(self.asset1.status, Asset.Status.BORROWED)
        self.assertEqual(self.asset2.status, Asset.Status.BORROWED)

        # Return inspection: asset1 GOOD -> AVAILABLE, asset2 MAJOR_DAMAGE -> DAMAGED + auto DamageReport
        item1 = loan.items.get(asset=self.asset1)
        item2 = loan.items.get(asset=self.asset2)
        ret_resp = self.client.post(
            reverse("loans:loan_return", args=[loan.pk]),
            {
                f"condition_{item1.pk}": Asset.Condition.GOOD,
                f"notes_{item1.pk}": "Lengkap",
                f"condition_{item2.pk}": Asset.Condition.MAJOR_DAMAGE,
                f"notes_{item2.pk}": "Lensa proyektor pecah",
            },
        )
        self.assertEqual(ret_resp.status_code, 302)

        loan.refresh_from_db()
        self.asset1.refresh_from_db()
        self.asset2.refresh_from_db()
        self.assertEqual(loan.status, Loan.Status.RETURNED)
        self.assertIsNotNone(loan.returned_at)
        self.assertEqual(self.asset1.status, Asset.Status.AVAILABLE)
        self.assertEqual(self.asset1.condition, Asset.Condition.GOOD)
        self.assertEqual(self.asset2.status, Asset.Status.DAMAGED)
        self.assertEqual(self.asset2.condition, Asset.Condition.MAJOR_DAMAGE)

        dmg = DamageReport.objects.get(asset=self.asset2)
        self.assertEqual(dmg.status, DamageReport.Status.VERIFIED)
        self.assertEqual(dmg.severity, DamageReport.Severity.HIGH)
        self.assertIn(loan.loan_number, dmg.description)

    def test_reject_cancel_overdue_and_state_machine_guards(self):
        # Reject requires mandatory reason
        loan = loan_services.create_online_loan(
            borrower_user=self.borrower1,
            asset_ids=[self.asset1.pk],
            borrow_date=self.today,
            due_date=self.today + timedelta(days=1),
            purpose="Uji Penolakan",
        )
        with self.assertRaises(ValidationError):
            loan_services.reject_loan(loan, staff_user=self.laboran, reason="   ")

        loan = loan_services.reject_loan(loan, staff_user=self.laboran, reason="Jadwal bentrok praktikum")
        self.assertEqual(loan.status, Loan.Status.REJECTED)
        # Terminal state cannot be approved
        with self.assertRaises(ValidationError):
            loan_services.approve_loan(loan, staff_user=self.laboran)

        # Borrower can cancel own PENDING loan, but not APPROVED loan
        loan2 = loan_services.create_online_loan(
            borrower_user=self.borrower1,
            asset_ids=[self.asset1.pk],
            borrow_date=self.today,
            due_date=self.today + timedelta(days=1),
            purpose="Uji Batal",
        )
        loan2 = loan_services.approve_loan(loan2, staff_user=self.laboran, handover_now=False)
        with self.assertRaises(ValidationError):
            loan_services.cancel_loan(loan2, actor=self.borrower1)
        loan2 = loan_services.cancel_loan(loan2, actor=self.laboran)
        self.assertEqual(loan2.status, Loan.Status.CANCELLED)

        # sync_overdue_loans marks ACTIVE past due_date as OVERDUE
        overdue_loan = loan_services.create_walk_in_loan(
            staff_user=self.laboran,
            asset_ids=[self.asset1.pk],
            borrow_date=self.today - timedelta(days=5),
            due_date=self.today - timedelta(days=1),
            purpose="Uji Terlambat",
            borrower_user=self.borrower1,
        )
        updated_count = loan_services.sync_overdue_loans()
        self.assertEqual(updated_count, 1)
        overdue_loan.refresh_from_db()
        self.assertEqual(overdue_loan.status, Loan.Status.OVERDUE)
