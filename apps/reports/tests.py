"""Automated tests for Module E — Dashboard, Straight-Line Depreciation & Exports (TC-29 to TC-32)."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import AuditLog
from apps.inventory.models import Asset, Category, Location
from apps.loans.models import Loan, LoanItem
from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule
from apps.reports.services import (
    calculate_asset_depreciation,
    calculate_portfolio_depreciation,
)

User = get_user_model()


class ModuleEReportsAndAnalyticsTests(TestCase):
    """Covers TC-29 through TC-32 from docs/08-Test-Plan-dan-QA.md plus AuditLog RBAC."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin_rep",
            email="admin_rep@labtrack.local",
            password="Password123!",
            full_name="Admin Laporan",
            role=User.Role.ADMIN,
        )
        cls.laboran = User.objects.create_user(
            username="laboran_rep",
            email="laboran_rep@labtrack.local",
            password="Password123!",
            full_name="Laboran Laporan",
            role=User.Role.LABORAN,
        )
        cls.borrower = User.objects.create_user(
            username="mhs_rep",
            email="mhs_rep@labtrack.local",
            password="Password123!",
            full_name="Mahasiswa Uji",
            role=User.Role.BORROWER,
        )

        cls.cat_kom = Category.objects.create(code="KOM", name="Komputer", default_useful_life_years=5)
        cls.loc_rpl = Location.objects.create(code="LAB-RPL", name="Lab RPL", building="Gedung Sains")

        # TC-29 fixture: C=12.000.000, S=2.000.000, N=5, age=2 years on 2026-11-28
        cls.asset_tc29 = Asset.objects.create(
            asset_code="LAB-KOM-2024-0001",
            name="Workstation Uji",
            category=cls.cat_kom,
            location=cls.loc_rpl,
            acquisition_date=date(2024, 11, 28),
            acquisition_cost=Decimal("12000000.00"),
            useful_life_years=5,
            salvage_value=Decimal("2000000.00"),
            status=Asset.Status.AVAILABLE,
            condition=Asset.Condition.GOOD,
        )
        # TC-30 fixture: C=10.000.000, S=1.000.000, N=4, age=6 years on 2026-11-28
        cls.asset_tc30 = Asset.objects.create(
            asset_code="LAB-KOM-2020-0002",
            name="PC Lama 6 Tahun",
            category=cls.cat_kom,
            location=cls.loc_rpl,
            acquisition_date=date(2020, 11, 28),
            acquisition_cost=Decimal("10000000.00"),
            useful_life_years=4,
            salvage_value=Decimal("1000000.00"),
            status=Asset.Status.MAINTENANCE,
            condition=Asset.Condition.MINOR_DAMAGE,
        )

        cls.loan = Loan.objects.create(
            loan_number="LOAN-20261128-0001",
            loan_channel=Loan.Channel.ONLINE,
            borrower_user=cls.borrower,
            borrower_name=cls.borrower.full_name,
            borrower_identifier="H071231001",
            borrower_contact="081200000001",
            purpose="Praktikum RPL",
            borrow_date=date(2026, 11, 20),
            due_date=date(2026, 11, 25),
            status=Loan.Status.PENDING,
        )
        LoanItem.objects.create(
            loan=cls.loan,
            asset=cls.asset_tc29,
            condition_on_checkout=Asset.Condition.GOOD,
        )
        MaintenanceSchedule.objects.create(
            asset=cls.asset_tc30,
            title="Pembersihan Berkala",
            frequency=MaintenanceSchedule.Frequency.MONTHLY,
            next_due_date=date.today() + timedelta(days=3),
            assigned_to=cls.laboran,
        )
        MaintenanceLog.objects.create(
            asset=cls.asset_tc30,
            performed_by=cls.laboran,
            performed_date=date.today(),
            summary="Ganti thermal paste",
            cost=Decimal("150000.00"),
            result_condition=Asset.Condition.GOOD,
        )
        AuditLog.objects.create(
            actor=cls.admin,
            action="ASSET_CREATED",
            entity_type="Asset",
            entity_id=str(cls.asset_tc29.pk),
            metadata={"asset_code": cls.asset_tc29.asset_code},
        )

    def test_tc29_straight_line_depreciation_formula_accuracy(self):
        """TC-29: C=12M, S=2M, N=5, age=2y -> annual=2M, accumulated~=4M, book_value~=8M."""
        res = calculate_asset_depreciation(self.asset_tc29, as_of_date=date(2026, 11, 28))
        self.assertEqual(res.depreciable_base, Decimal("10000000.00"))
        self.assertEqual(res.annual_depreciation, Decimal("2000000.00"))
        self.assertEqual(res.accumulated_depreciation + res.book_value, res.acquisition_cost)
        self.assertTrue(Decimal("3990000.00") <= res.accumulated_depreciation <= Decimal("4000000.00"))
        self.assertTrue(Decimal("8000000.00") <= res.book_value <= Decimal("8010000.00"))

        portfolio = calculate_portfolio_depreciation(Asset.objects.all(), as_of_date=date(2026, 11, 28))
        self.assertEqual(portfolio["totals"]["count"], 2)
        self.assertEqual(portfolio["totals"]["book_value"], sum(r.book_value for r in portfolio["rows"]))

    def test_tc30_depreciation_floor_when_age_exceeds_useful_life(self):
        """TC-30: C=10M, S=1M, N=4, age=6y -> accumulated=9M, book_value=1M (never below salvage)."""
        res = calculate_asset_depreciation(self.asset_tc30, as_of_date=date(2026, 11, 28))
        self.assertEqual(res.accumulated_depreciation, Decimal("9000000.00"))
        self.assertEqual(res.book_value, Decimal("1000000.00"))
        self.assertEqual(res.depreciation_pct, Decimal("100.00"))

        # Edge case: as_of_date before acquisition_date -> 0 depreciation
        pre = calculate_asset_depreciation(self.asset_tc29, as_of_date=date(2024, 1, 1))
        self.assertEqual(pre.accumulated_depreciation, Decimal("0.00"))
        self.assertEqual(pre.book_value, Decimal("12000000.00"))

    def test_tc31_dashboard_charts_json_endpoint_contract(self):
        """TC-31: ADMIN GET /reports/api/dashboard-charts/ returns 200 and valid JSON contract; BORROWER gets 403."""
        self.client.force_login(self.borrower)
        self.assertEqual(self.client.get(reverse("reports:api_dashboard_charts")).status_code, 403)

        self.client.force_login(self.admin)
        resp = self.client.get(reverse("reports:api_dashboard_charts"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(
            data["status_distribution"]["labels"],
            ["Tersedia", "Dipinjam", "Pemeliharaan", "Rusak"],
        )
        self.assertEqual(len(data["status_distribution"]["values"]), 4)
        self.assertIn("labels", data["condition_by_category"])
        self.assertIn("good", data["condition_by_category"])
        self.assertEqual(len(data["monthly_activity"]["labels"]), 6)
        self.assertIn("loans_online", data["monthly_activity"])
        self.assertIn("loans_walk_in", data["monthly_activity"])
        self.assertIn("maintenances", data["monthly_activity"])

    def test_tc32_condition_and_depreciation_csv_pdf_exports(self):
        """TC-32: ADMIN exports Condition & Depreciation reports as CSV and PDF with attachment headers."""
        self.client.force_login(self.admin)

        for url in [
            reverse("reports:condition_report") + "?export=csv",
            reverse("reports:depreciation_report") + "?as_of=2026-11-28&export=csv",
        ]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertIn("attachment;", resp["Content-Disposition"])
            self.assertTrue(resp.content.startswith(b"\xef\xbb\xbf"))
            self.assertGreater(len(resp.content), 40)

        for url in [
            reverse("reports:condition_report") + "?export=pdf",
            reverse("reports:depreciation_report") + "?as_of=2026-11-28&export=pdf",
        ]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp["Content-Type"], "application/pdf")
            self.assertIn("attachment;", resp["Content-Disposition"])
            self.assertTrue(resp.content.startswith(b"%PDF"))
            self.assertGreater(len(resp.content), 500)

    def test_audit_log_view_admin_only(self):
        """Audit log viewer is strictly restricted to ADMIN."""
        url = reverse("core:audit_log_list")
        self.client.force_login(self.borrower)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.laboran)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ASSET_CREATED")
