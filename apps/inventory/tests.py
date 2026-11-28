"""Automated tests for Module B — Master Asset, Category, Location & QR Code (TC-07 to TC-15)."""

import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.templatetags.labtrack_tags import format_rupiah, status_badge
from apps.inventory import services
from apps.inventory.models import Asset, AssetLocationHistory, Category, Location
from apps.loans import services as loan_services

User = get_user_model()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="labtrack_test_media_"))
class ModuleBInventoryAndQRTests(TestCase):
    """Covers TC-07 through TC-15 from docs/08-Test-Plan-dan-QA.md."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_inv",
            email="admin_inv@labtrack.local",
            password="Password123!",
            full_name="Admin Inventaris",
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.laboran = User.objects.create_user(
            username="laboran_inv",
            email="laboran_inv@labtrack.local",
            password="Password123!",
            full_name="Laboran Inventaris",
            role=User.Role.LABORAN,
            is_staff=True,
        )
        self.borrower = User.objects.create_user(
            username="mhs_inv",
            email="mhs_inv@labtrack.local",
            password="Password123!",
            full_name="Mahasiswa Rahasia Peminjam",
            role=User.Role.BORROWER,
            identifier_number="H071241999",
            phone_number="081288887777",
        )
        self.cat = Category.objects.create(code="KOM", name="Komputer", default_useful_life_years=5)
        self.loc_rpl = Location.objects.create(code="LAB-RPL", name="Lab RPL")
        self.loc_bd = Location.objects.create(code="LAB-BD", name="Lab Basis Data")

        self.asset = services.create_asset(
            Asset(
                name="PC Workstation 01",
                category=self.cat,
                location=self.loc_rpl,
                acquisition_date=date(2025, 1, 10),
                acquisition_cost=Decimal("15000000.00"),
                useful_life_years=5,
                salvage_value=Decimal("1500000.00"),
            ),
            actor=self.admin,
        )

    def test_template_tags_and_asset_list_query_efficiency(self):
        """Helper tags format Rupiah & badges; asset_list avoids N+1 queries."""
        self.assertEqual(format_rupiah(Decimal("15000000.00")), "Rp 15.000.000")
        self.assertEqual(format_rupiah(None), "Rp 0")
        badge = status_badge("AVAILABLE")
        self.assertIn("Tersedia", badge)

        self.client.force_login(self.laboran)
        with self.assertNumQueries(6):
            resp = self.client.get(reverse("inventory:asset_list"))
        self.assertEqual(resp.status_code, 200)

    def test_tc07_create_asset_generates_code_qr_and_initial_location_history(self):
        """TC-07: LABORAN creates asset -> AVAILABLE, QR PNG generated, initial location history logged."""
        self.client.force_login(self.laboran)
        resp = self.client.post(
            reverse("inventory:asset_create"),
            {
                "name": "Monitor Dell UltraSharp 27",
                "category": self.cat.pk,
                "location": self.loc_rpl.pk,
                "acquisition_date": "2026-02-15",
                "acquisition_cost": "6500000.00",
                "useful_life_years": 5,
                "salvage_value": "500000.00",
                "condition": Asset.Condition.GOOD,
                "status": Asset.Status.AVAILABLE,
            },
        )
        self.assertEqual(resp.status_code, 302)
        created = Asset.objects.get(name="Monitor Dell UltraSharp 27")
        self.assertEqual(created.status, Asset.Status.AVAILABLE)
        self.assertTrue(created.asset_code.startswith("LAB-KOM-2026-"))
        self.assertTrue(bool(created.qr_code_image.name))
        self.assertEqual(AssetLocationHistory.objects.filter(asset=created).count(), 1)
        self.assertTrue(
            AuditLog.objects.filter(action="ASSET_CREATED", entity_id=str(created.pk)).exists()
        )

    def test_tc08_reject_salvage_value_greater_than_acquisition_cost(self):
        """TC-08: Form rejects salvage_value > acquisition_cost with clear validation message."""
        self.client.force_login(self.laboran)
        resp = self.client.post(
            reverse("inventory:asset_create"),
            {
                "name": "Aset Tidak Valid",
                "category": self.cat.pk,
                "location": self.loc_rpl.pk,
                "acquisition_date": "2026-01-01",
                "acquisition_cost": "1000000.00",
                "useful_life_years": 3,
                "salvage_value": "1500000.00",
                "condition": Asset.Condition.GOOD,
                "status": Asset.Status.AVAILABLE,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Nilai residu tidak boleh lebih besar")
        self.assertFalse(Asset.objects.filter(name="Aset Tidak Valid").exists())

    def test_tc09_move_asset_location_records_history(self):
        """TC-09: Moving asset from LAB-RPL to LAB-BD updates location and appends history."""
        self.client.force_login(self.laboran)
        resp = self.client.post(
            reverse("inventory:asset_move", args=[self.asset.pk]),
            {"to_location": self.loc_bd.pk, "reason": "Kebutuhan Praktikum Basis Data"},
        )
        self.assertEqual(resp.status_code, 302)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.location, self.loc_bd)
        self.assertEqual(AssetLocationHistory.objects.filter(asset=self.asset).count(), 2)
        latest = AssetLocationHistory.objects.filter(asset=self.asset).first()
        self.assertEqual(latest.from_location, self.loc_rpl)
        self.assertEqual(latest.to_location, self.loc_bd)
        self.assertTrue(
            AuditLog.objects.filter(action="ASSET_LOCATION_MOVED", entity_id=str(self.asset.pk)).exists()
        )

    def test_tc10_prevent_delete_category_in_use(self):
        """TC-10: Deleting a Category (or Location) referenced by assets is rejected cleanly."""
        self.client.force_login(self.laboran)
        resp = self.client.post(reverse("inventory:category_delete", args=[self.cat.pk]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Category.objects.filter(pk=self.cat.pk).exists())
        self.assertContains(resp, "tidak dapat dihapus")

        loc_resp = self.client.post(reverse("inventory:location_delete", args=[self.loc_rpl.pk]), follow=True)
        self.assertEqual(loc_resp.status_code, 200)
        self.assertTrue(Location.objects.filter(pk=self.loc_rpl.pk).exists())

    def test_tc11_admin_retire_asset_marks_inactive_and_audits(self):
        """TC-11: ADMIN retiring an asset sets status=RETIRED, is_active=False, and logs audit."""
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("inventory:asset_retire", args=[self.asset.pk]),
            {"reason": "Kerusakan permanen melewati umur ekonomis"},
        )
        self.assertEqual(resp.status_code, 302)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.RETIRED)
        self.assertFalse(self.asset.is_active)
        self.assertTrue(
            AuditLog.objects.filter(action="ASSET_RETIRED", entity_id=str(self.asset.pk)).exists()
        )

    def test_tc12_laboran_forbidden_to_retire_asset(self):
        """TC-12: LABORAN attempting POST /inventory/assets/<id>/retire/ receives HTTP 403."""
        self.client.force_login(self.laboran)
        resp = self.client.post(
            reverse("inventory:asset_retire", args=[self.asset.pk]),
            {"reason": "Tidak berwenang"},
        )
        self.assertEqual(resp.status_code, 403)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.AVAILABLE)

    def test_tc13_public_qr_scan_hides_borrower_cost_and_edit_controls(self):
        """TC-13: Anonymous/BORROWER /scan/<code>/ shows identity only; never leaks borrower, cost, or edit links."""
        # Create an active walk-in loan so borrower data exists in DB for this asset
        today = timezone.localdate()
        loan_services.create_walk_in_loan(
            staff_user=self.laboran,
            asset_ids=[self.asset.pk],
            borrow_date=today,
            due_date=today + timedelta(days=2),
            purpose="Uji Privasi QR",
            borrower_user=self.borrower,
        )
        scan_url = reverse("asset_qr_scan", args=[self.asset.asset_code])

        # Public anonymous viewer
        anon_resp = self.client.get(scan_url)
        self.assertEqual(anon_resp.status_code, 200)
        self.assertContains(anon_resp, self.asset.asset_code)
        self.assertContains(anon_resp, self.asset.name)
        self.assertNotContains(anon_resp, "Mahasiswa Rahasia Peminjam")
        self.assertNotContains(anon_resp, "081288887777")
        self.assertNotContains(anon_resp, "15.000.000")
        self.assertNotContains(anon_resp, "Panel Aksi Cepat Staf")
        self.assertNotContains(anon_resp, reverse("inventory:asset_edit", args=[self.asset.pk]))

        # Logged-in BORROWER also must not see staff quick-action panel
        self.client.force_login(self.borrower)
        bor_resp = self.client.get(scan_url)
        self.assertEqual(bor_resp.status_code, 200)
        self.assertNotContains(bor_resp, "Panel Aksi Cepat Staf")
        self.assertNotContains(bor_resp, "15.000.000")

    def test_tc14_staff_qr_scan_displays_quick_action_panel(self):
        """TC-14: Logged-in LABORAN scanning /scan/<code>/ sees Staff Quick Actions panel."""
        self.client.force_login(self.laboran)
        resp = self.client.get(reverse("asset_qr_scan", args=[self.asset.asset_code]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Panel Aksi Cepat Staf")
        self.assertContains(resp, f"?asset={self.asset.pk}")
        self.assertContains(resp, "Laporkan Kerusakan Aset")
        self.assertContains(resp, reverse("inventory:asset_detail", args=[self.asset.pk]))

    def test_tc15_qr_png_download_and_bulk_print_page(self):
        """TC-15: LABORAN downloads valid PNG QR and renders bulk QR print grid."""
        self.client.force_login(self.laboran)
        dl_resp = self.client.get(reverse("inventory:asset_qr_download", args=[self.asset.pk]))
        self.assertEqual(dl_resp.status_code, 200)
        self.assertEqual(dl_resp["Content-Type"], "image/png")
        self.assertIn("attachment;", dl_resp["Content-Disposition"])
        self.assertTrue(dl_resp.content.startswith(b"\x89PNG\r\n\x1a\n"))

        print_resp = self.client.get(reverse("inventory:asset_qr_print"))
        self.assertEqual(print_resp.status_code, 200)
        self.assertContains(print_resp, self.asset.asset_code)
