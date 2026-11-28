"""Automated tests for Module D — Damage Reports & Maintenance Schedules (TC-25 to TC-28)."""

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.core.models import AuditLog
from apps.inventory.models import Asset, Category, Location
from apps.maintenance import services
from apps.maintenance.models import DamageReport, MaintenanceLog, MaintenanceSchedule

User = get_user_model()


def _make_test_png(name: str = "bukti.png") -> SimpleUploadedFile:
    buf = BytesIO()
    Image.new("RGB", (32, 32), color=(15, 118, 110)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


class ModuleDMaintenanceTests(TestCase):
    """Covers TC-25 through TC-28 from docs/08-Test-Plan-dan-QA.md plus guards."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin_mnt",
            email="admin_mnt@labtrack.test",
            password="Password123!",
            full_name="Admin Lab",
            role=User.Role.ADMIN,
        )
        cls.laboran = User.objects.create_user(
            username="laboran_mnt",
            email="laboran_mnt@labtrack.test",
            password="Password123!",
            full_name="Teknisi Lab",
            role=User.Role.LABORAN,
        )
        cls.borrower = User.objects.create_user(
            username="mhs_mnt",
            email="mhs_mnt@labtrack.test",
            password="Password123!",
            full_name="Mahasiswa Sintetis",
            role=User.Role.BORROWER,
            identifier_number="H071241099",
        )
        cls.category = Category.objects.create(
            code="PRJ",
            name="Proyektor",
            default_useful_life_years=5,
        )
        cls.location = Location.objects.create(
            code="LAB-RPL",
            name="Lab RPL & Basis Data",
        )
        cls.asset = Asset.objects.create(
            asset_code="LAB-PRJ-2026-0001",
            name="Proyektor Epson EB-X500",
            category=cls.category,
            location=cls.location,
            acquisition_date=date(2025, 1, 15),
            acquisition_cost=Decimal("7500000.00"),
            useful_life_years=5,
            salvage_value=Decimal("500000.00"),
            status=Asset.Status.AVAILABLE,
            condition=Asset.Condition.GOOD,
        )

    def test_tc25_borrower_submits_damage_report(self):
        """TC-25: BORROWER submits damage report -> DamageReport created with status REPORTED."""
        self.client.force_login(self.borrower)
        photo = _make_test_png("lensa_rusak.png")
        resp = self.client.post(
            reverse("maintenance:damage_create"),
            {
                "asset": self.asset.pk,
                "severity": DamageReport.Severity.HIGH,
                "description": "Lampu proyektor berkedip merah dan mati otomatis.",
                "photo": photo,
            },
        )
        self.assertEqual(resp.status_code, 302)
        report = DamageReport.objects.get()
        self.assertEqual(report.status, DamageReport.Status.REPORTED)
        self.assertEqual(report.reported_by, self.borrower)
        self.assertTrue(
            AuditLog.objects.filter(
                action="DAMAGE_REPORT_CREATED",
                entity_id=str(report.pk),
            ).exists()
        )
        if report.photo:
            report.photo.delete(save=False)

    def test_tc26_damage_repair_lifecycle_reported_to_resolved(self):
        """TC-26: REPORTED -> VERIFIED -> IN_REPAIR (asset=MAINTENANCE) -> RESOLVED (asset=AVAILABLE & GOOD)."""
        report = services.create_damage_report(
            asset=self.asset,
            reported_by=self.borrower,
            severity=DamageReport.Severity.MEDIUM,
            description="Port HDMI longgar.",
        )

        # Invalid jump REPORTED -> RESOLVED must fail
        with self.assertRaises(ValidationError):
            services.update_damage_report_status(
                report=report,
                staff_user=self.laboran,
                new_status=DamageReport.Status.RESOLVED,
            )

        self.client.force_login(self.laboran)
        # REPORTED -> VERIFIED
        self.client.post(
            reverse("maintenance:damage_update_status", args=[report.pk]),
            {"new_status": DamageReport.Status.VERIFIED, "resolution_notes": "Port HDMI kendor."},
        )
        report.refresh_from_db()
        self.assertEqual(report.status, DamageReport.Status.VERIFIED)

        # VERIFIED -> IN_REPAIR => asset becomes MAINTENANCE
        self.client.post(
            reverse("maintenance:damage_update_status", args=[report.pk]),
            {"new_status": DamageReport.Status.IN_REPAIR, "resolution_notes": "Proses perbaikan."},
        )
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.MAINTENANCE)

        # IN_REPAIR -> RESOLVED => asset becomes AVAILABLE & GOOD + MaintenanceLog created
        self.client.post(
            reverse("maintenance:damage_update_status", args=[report.pk]),
            {
                "new_status": DamageReport.Status.RESOLVED,
                "resolution_notes": "Port HDMI diganti baru.",
                "create_maintenance_log": "on",
                "repair_cost": "250000.00",
                "repair_summary": "Penggantian modul port HDMI.",
                "performed_date": str(timezone.localdate()),
            },
        )
        report.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(report.status, DamageReport.Status.RESOLVED)
        self.assertIsNotNone(report.resolved_at)
        self.assertEqual(self.asset.status, Asset.Status.AVAILABLE)
        self.assertEqual(self.asset.condition, Asset.Condition.GOOD)
        log = MaintenanceLog.objects.get(damage_report=report)
        self.assertEqual(log.cost, Decimal("250000.00"))

    def test_tc27_execute_quarterly_schedule_advances_due_date_3_months(self):
        """TC-27: Executing QUARTERLY schedule creates MaintenanceLog, advances next_due_date +3 months, stays SCHEDULED."""
        schedule = services.create_or_update_schedule(
            staff_user=self.laboran,
            asset=self.asset,
            title="Pembersihan Filter Proyektor",
            frequency=MaintenanceSchedule.Frequency.QUARTERLY,
            next_due_date=date(2026, 11, 28),
            assigned_to=self.laboran,
        )
        self.client.force_login(self.laboran)
        resp = self.client.post(
            reverse("maintenance:schedule_execute", args=[schedule.pk]),
            {
                "performed_date": "2026-11-28",
                "summary": "Filter dibersihkan dan kalibrasi fokus selesai.",
                "cost": "75000.00",
                "result_condition": Asset.Condition.GOOD,
            },
        )
        self.assertEqual(resp.status_code, 302)
        schedule.refresh_from_db()
        self.assertEqual(schedule.status, MaintenanceSchedule.Status.SCHEDULED)
        self.assertEqual(schedule.next_due_date, date(2027, 2, 28))
        self.assertIsNotNone(schedule.last_completed_at)
        self.assertTrue(MaintenanceLog.objects.filter(schedule=schedule, cost=Decimal("75000.00")).exists())

    def test_tc28_execute_once_schedule_marks_completed(self):
        """TC-28: Executing ONCE schedule creates MaintenanceLog and marks schedule COMPLETED."""
        schedule = services.create_or_update_schedule(
            staff_user=self.admin,
            asset=self.asset,
            title="Penggantian Kabel Power",
            frequency=MaintenanceSchedule.Frequency.ONCE,
            next_due_date=timezone.localdate(),
            assigned_to=self.laboran,
        )
        self.client.force_login(self.laboran)
        resp = self.client.post(
            reverse("maintenance:schedule_execute", args=[schedule.pk]),
            {
                "performed_date": str(timezone.localdate()),
                "summary": "Kabel power diganti.",
                "cost": "50000.00",
                "result_condition": Asset.Condition.GOOD,
            },
        )
        self.assertEqual(resp.status_code, 302)
        schedule.refresh_from_db()
        self.assertEqual(schedule.status, MaintenanceSchedule.Status.COMPLETED)
        self.assertTrue(MaintenanceLog.objects.filter(schedule=schedule, cost=Decimal("50000.00")).exists())

    def test_photo_validation_and_rbac_on_maintenance_endpoints(self):
        """Photo extension/size validation and BORROWER 403 guards on staff maintenance routes."""
        bad_ext = SimpleUploadedFile("virus.exe", b"not-an-image", content_type="application/octet-stream")
        with self.assertRaises(ValidationError):
            services.create_damage_report(
                asset=self.asset,
                reported_by=self.borrower,
                severity=DamageReport.Severity.LOW,
                description="Tes format salah",
                photo=bad_ext,
            )

        oversize = SimpleUploadedFile("besar.jpg", b"x" * (2 * 1024 * 1024 + 10), content_type="image/jpeg")
        with self.assertRaises(ValidationError):
            services.create_damage_report(
                asset=self.asset,
                reported_by=self.borrower,
                severity=DamageReport.Severity.LOW,
                description="Tes ukuran terlalu besar",
                photo=oversize,
            )

        report = services.create_damage_report(
            asset=self.asset,
            reported_by=self.borrower,
            severity=DamageReport.Severity.LOW,
            description="Tombol power macet",
        )
        self.client.force_login(self.borrower)
        self.assertEqual(
            self.client.post(
                reverse("maintenance:damage_update_status", args=[report.pk]),
                {"new_status": DamageReport.Status.VERIFIED},
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get(reverse("maintenance:schedule_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("maintenance:log_list")).status_code, 403)
