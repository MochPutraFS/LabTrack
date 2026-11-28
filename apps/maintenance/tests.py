"""Unit and integration tests for Damage Reports, Maintenance Schedules, and Logs (Sesi 4)."""

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


class MaintenanceTestBase(TestCase):
    """Shared fixtures for maintenance service and view tests."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin_mnt",
            email="admin_mnt@labtrack.test",
            password="password123",
            full_name="Admin Lab",
            role=User.Role.ADMIN,
        )
        cls.laboran = User.objects.create_user(
            username="laboran_mnt",
            email="laboran_mnt@labtrack.test",
            password="password123",
            full_name="Teknisi Lab",
            role=User.Role.LABORAN,
        )
        cls.borrower = User.objects.create_user(
            username="mhs_mnt",
            email="mhs_mnt@labtrack.test",
            password="password123",
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


class DamageReportServiceTests(MaintenanceTestBase):
    def test_create_damage_report_generates_number_validates_photo_and_audits(self):
        photo = _make_test_png("lensa_rusak.png")
        report = services.create_damage_report(
            asset=self.asset,
            reported_by=self.borrower,
            severity=DamageReport.Severity.HIGH,
            description="Lampu proyektor berkedip merah dan mati otomatis.",
            photo=photo,
        )
        today_str = timezone.localdate().strftime("%Y%m%d")
        self.assertTrue(report.report_number.startswith(f"DMG-{today_str}-"))
        self.assertEqual(report.status, DamageReport.Status.REPORTED)
        self.assertTrue(bool(report.photo))
        self.assertTrue(
            AuditLog.objects.filter(
                action="DAMAGE_REPORT_CREATED",
                entity_type="DamageReport",
                entity_id=str(report.pk),
            ).exists()
        )
        if report.photo:
            report.photo.delete(save=False)

    def test_create_damage_report_rejects_invalid_photo_format_and_oversize(self):
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

    def test_damage_state_machine_to_resolved_with_maintenance_log(self):
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

        # REPORTED -> VERIFIED
        services.update_damage_report_status(
            report=report,
            staff_user=self.laboran,
            new_status=DamageReport.Status.VERIFIED,
            resolution_notes="Dikonfirmasi port HDMI kendor.",
        )
        report.refresh_from_db()
        self.assertEqual(report.status, DamageReport.Status.VERIFIED)

        # VERIFIED -> IN_REPAIR (asset becomes MAINTENANCE)
        services.update_damage_report_status(
            report=report,
            staff_user=self.laboran,
            new_status=DamageReport.Status.IN_REPAIR,
        )
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.MAINTENANCE)

        # IN_REPAIR -> RESOLVED (asset becomes AVAILABLE & GOOD + MaintenanceLog)
        result = services.update_damage_report_status(
            report=report,
            staff_user=self.laboran,
            new_status=DamageReport.Status.RESOLVED,
            resolution_notes="Port HDMI diganti baru.",
            create_maintenance_log=True,
            repair_cost=Decimal("250000.00"),
            repair_summary="Penggantian modul port HDMI.",
        )
        report.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(report.status, DamageReport.Status.RESOLVED)
        self.assertIsNotNone(report.resolved_at)
        self.assertEqual(self.asset.status, Asset.Status.AVAILABLE)
        self.assertEqual(self.asset.condition, Asset.Condition.GOOD)
        self.assertIsNotNone(result["maintenance_log"])
        self.assertEqual(result["maintenance_log"].cost, Decimal("250000.00"))
        self.assertEqual(result["maintenance_log"].damage_report_id, report.pk)

    def test_damage_state_machine_to_unrepairable_marks_asset_damaged(self):
        report = services.create_damage_report(
            asset=self.asset,
            reported_by=self.laboran,
            severity=DamageReport.Severity.CRITICAL,
            description="Mainboard terbakar total.",
        )
        services.update_damage_report_status(report, self.laboran, DamageReport.Status.VERIFIED)
        services.update_damage_report_status(
            report,
            self.laboran,
            DamageReport.Status.UNREPAIRABLE,
            resolution_notes="Suku cadang sudah discontinue.",
        )
        report.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(report.status, DamageReport.Status.UNREPAIRABLE)
        self.assertEqual(self.asset.status, Asset.Status.DAMAGED)
        self.assertEqual(self.asset.condition, Asset.Condition.MAJOR_DAMAGE)


class MaintenanceScheduleServiceTests(MaintenanceTestBase):
    def test_execute_recurring_schedule_advances_next_due_date_and_creates_log(self):
        due = date(2026, 11, 28)
        schedule = services.create_or_update_schedule(
            staff_user=self.laboran,
            asset=self.asset,
            title="Pembersihan Filter Proyektor",
            frequency=MaintenanceSchedule.Frequency.QUARTERLY,
            next_due_date=due,
            assigned_to=self.laboran,
        )

        result = services.execute_maintenance_schedule(
            schedule=schedule,
            staff_user=self.laboran,
            performed_date=date(2026, 11, 28),
            summary="Filter dibersihkan dan kalibrasi fokus selesai.",
            cost=Decimal("75000.00"),
            result_condition=Asset.Condition.GOOD,
        )
        schedule.refresh_from_db()
        self.assertEqual(schedule.status, MaintenanceSchedule.Status.SCHEDULED)
        self.assertEqual(schedule.next_due_date, date(2027, 2, 28))
        self.assertIsNotNone(schedule.last_completed_at)
        self.assertEqual(result["log"].cost, Decimal("75000.00"))
        self.assertTrue(
            AuditLog.objects.filter(
                action="MAINTENANCE_SCHEDULE_EXECUTED",
                entity_type="MaintenanceSchedule",
                entity_id=str(schedule.pk),
            ).exists()
        )

    def test_execute_once_schedule_marks_completed(self):
        schedule = services.create_or_update_schedule(
            staff_user=self.admin,
            asset=self.asset,
            title="Penggantian Kabel Power",
            frequency=MaintenanceSchedule.Frequency.ONCE,
            next_due_date=timezone.localdate(),
            assigned_to=self.laboran,
        )
        services.execute_maintenance_schedule(
            schedule=schedule,
            staff_user=self.laboran,
            performed_date=timezone.localdate(),
            summary="Kabel power diganti.",
            cost=Decimal("50000.00"),
            result_condition=Asset.Condition.GOOD,
        )
        schedule.refresh_from_db()
        self.assertEqual(schedule.status, MaintenanceSchedule.Status.COMPLETED)


class MaintenanceViewAndRBACTests(MaintenanceTestBase):
    def test_borrower_can_report_and_view_damage_but_blocked_from_staff_endpoints(self):
        self.client.force_login(self.borrower)

        res_list = self.client.get(reverse("maintenance:damage_list"))
        self.assertEqual(res_list.status_code, 200)

        res_create = self.client.post(
            reverse("maintenance:damage_create"),
            {
                "asset": self.asset.pk,
                "severity": DamageReport.Severity.MEDIUM,
                "description": "Tombol power agak macet.",
            },
        )
        self.assertEqual(res_create.status_code, 302)
        report = DamageReport.objects.first()
        self.assertIsNotNone(report)

        res_detail = self.client.get(reverse("maintenance:damage_detail", args=[report.pk]))
        self.assertEqual(res_detail.status_code, 200)
        self.assertNotContains(res_detail, "Panel Tindak Lanjut Staf")

        # BORROWER forbidden on status update & schedules & logs
        self.assertEqual(
            self.client.post(
                reverse("maintenance:damage_update_status", args=[report.pk]),
                {"new_status": DamageReport.Status.VERIFIED},
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get(reverse("maintenance:schedule_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("maintenance:log_list")).status_code, 403)

    def test_staff_views_schedule_highlights_logs_total_and_qr_integration(self):
        today = timezone.localdate()
        overdue_sched = MaintenanceSchedule.objects.create(
            asset=self.asset,
            title="Kalibrasi Terlambat",
            frequency=MaintenanceSchedule.Frequency.MONTHLY,
            next_due_date=today - timedelta(days=3),
            status=MaintenanceSchedule.Status.SCHEDULED,
        )
        soon_sched = MaintenanceSchedule.objects.create(
            asset=self.asset,
            title="Cek Rutin H-7",
            frequency=MaintenanceSchedule.Frequency.ANNUAL,
            next_due_date=today + timedelta(days=3),
            status=MaintenanceSchedule.Status.SCHEDULED,
        )
        MaintenanceLog.objects.create(
            asset=self.asset,
            schedule=overdue_sched,
            performed_by=self.laboran,
            performed_date=today,
            summary="Servis berkala",
            cost=Decimal("150000.00"),
            result_condition=Asset.Condition.GOOD,
        )

        # Public QR scan must NOT show damage report action button
        pub_res = self.client.get(reverse("asset_qr_scan", args=[self.asset.asset_code]))
        self.assertEqual(pub_res.status_code, 200)
        self.assertNotContains(pub_res, "Laporkan Kerusakan Aset")

        # Staff sees schedule highlights, log total cost, asset detail links, and QR damage button
        self.client.force_login(self.laboran)
        sched_res = self.client.get(reverse("maintenance:schedule_list"))
        self.assertEqual(sched_res.status_code, 200)
        self.assertContains(sched_res, "Jadwal Terlambat (OVERDUE)")
        self.assertContains(sched_res, "Jadwal Jatuh Tempo H-7")
        self.assertContains(sched_res, soon_sched.title)

        log_res = self.client.get(reverse("maintenance:log_list"))
        self.assertEqual(log_res.status_code, 200)
        self.assertContains(log_res, "Rp 150.000")

        qr_staff_res = self.client.get(reverse("asset_qr_scan", args=[self.asset.asset_code]))
        self.assertEqual(qr_staff_res.status_code, 200)
        self.assertContains(qr_staff_res, "Laporkan Kerusakan Aset")
