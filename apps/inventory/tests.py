"""Automated tests for Session 2: RBAC, Accounts, Inventory CRUD, and QR Code."""

import tempfile
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import AuditLog
from apps.core.templatetags.labtrack_tags import format_rupiah, status_badge
from apps.inventory import services
from apps.inventory.models import Asset, AssetLocationHistory, Category, Location

User = get_user_model()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="labtrack_test_media_"))
class Session2Tests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_t",
            email="admin_t@labtrack.local",
            password="Password123!",
            full_name="Admin Test",
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.laboran = User.objects.create_user(
            username="laboran_t",
            email="laboran_t@labtrack.local",
            password="Password123!",
            full_name="Laboran Test",
            role=User.Role.LABORAN,
            is_staff=True,
        )
        self.borrower = User.objects.create_user(
            username="mhs_t",
            email="mhs_t@labtrack.local",
            password="Password123!",
            full_name="Mahasiswa Test",
            role=User.Role.BORROWER,
            identifier_number="H071241999",
        )
        self.cat = Category.objects.create(code="KOM", name="Komputer", default_useful_life_years=5)
        self.loc1 = Location.objects.create(code="LAB-RPL", name="Lab RPL")
        self.loc2 = Location.objects.create(code="LAB-JAR", name="Lab Jaringan")

        self.asset = services.create_asset(
            Asset(
                name="PC Workstation 01",
                category=self.cat,
                location=self.loc1,
                acquisition_date=date(2025, 1, 10),
                acquisition_cost=Decimal("15000000.00"),
                useful_life_years=5,
                salvage_value=Decimal("1500000.00"),
            ),
            actor=self.admin,
        )

    def test_template_tags(self):
        self.assertEqual(format_rupiah(Decimal("15000000.00")), "Rp 15.000.000")
        self.assertEqual(format_rupiah(None), "Rp 0")
        badge = status_badge("AVAILABLE")
        self.assertIn("Tersedia", badge)
        self.assertIn("#ECFDF5", badge)

    def test_rbac_enforcement(self):
        self.client.force_login(self.borrower)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("inventory:asset_create")).status_code, 403)
        self.assertEqual(self.client.post(reverse("inventory:asset_retire", args=[self.asset.pk]), {"reason": "x"}).status_code, 403)

        self.client.force_login(self.laboran)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("inventory:asset_create")).status_code, 200)
        self.assertEqual(self.client.post(reverse("inventory:asset_retire", args=[self.asset.pk]), {"reason": "x"}).status_code, 403)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 200)

    def test_login_by_email_and_post_logout(self):
        resp = self.client.post(
            reverse("accounts:login"),
            {"username": "mhs_t@labtrack.local", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 302)
        # Logout rejects GET and accepts POST
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("accounts:logout")).status_code, 302)

    def test_category_and_location_delete_prevented_when_in_use(self):
        self.client.force_login(self.laboran)
        self.client.post(reverse("inventory:category_delete", args=[self.cat.pk]))
        self.assertTrue(Category.objects.filter(pk=self.cat.pk).exists())

        self.client.post(reverse("inventory:location_delete", args=[self.loc1.pk]))
        self.assertTrue(Location.objects.filter(pk=self.loc1.pk).exists())

    def test_asset_create_validation_move_and_retire(self):
        # Auto-generated code, QR file, initial location history, and audit log
        self.assertTrue(self.asset.asset_code.startswith("LAB-KOM-2025-"))
        self.assertTrue(bool(self.asset.qr_code_image.name))
        self.assertEqual(AssetLocationHistory.objects.filter(asset=self.asset).count(), 1)

        # salvage_value > acquisition_cost rejected
        self.client.force_login(self.laboran)
        resp = self.client.post(
            reverse("inventory:asset_create"),
            {
                "name": "Invalid Asset",
                "category": self.cat.pk,
                "location": self.loc1.pk,
                "acquisition_date": "2026-01-01",
                "acquisition_cost": "1000000.00",
                "useful_life_years": 3,
                "salvage_value": "2000000.00",
                "condition": Asset.Condition.GOOD,
                "status": Asset.Status.AVAILABLE,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Nilai residu tidak boleh lebih besar")

        # Move location records history + audit
        resp = self.client.post(
            reverse("inventory:asset_move", args=[self.asset.pk]),
            {"to_location": self.loc2.pk, "reason": "Praktikum Jaringan"},
        )
        self.assertEqual(resp.status_code, 302)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.location, self.loc2)
        self.assertEqual(AssetLocationHistory.objects.filter(asset=self.asset).count(), 2)
        self.assertTrue(AuditLog.objects.filter(action="ASSET_LOCATION_MOVED", entity_id=str(self.asset.pk)).exists())

        # Retire asset (ADMIN only)
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("inventory:asset_retire", args=[self.asset.pk]),
            {"reason": "Rusak permanen"},
        )
        self.assertEqual(resp.status_code, 302)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.RETIRED)
        self.assertFalse(self.asset.is_active)
        self.assertTrue(AuditLog.objects.filter(action="ASSET_RETIRED", entity_id=str(self.asset.pk)).exists())

    def test_qr_download_print_and_public_scan_privacy(self):
        scan_url = reverse("asset_qr_scan", args=[self.asset.asset_code])

        # Anonymous public scan: 200, NO acquisition cost, NO staff panel
        anon_resp = self.client.get(scan_url)
        self.assertEqual(anon_resp.status_code, 200)
        self.assertContains(anon_resp, self.asset.asset_code)
        self.assertNotContains(anon_resp, "15.000.000")
        self.assertNotContains(anon_resp, "Panel Aksi Cepat Staf")

        # BORROWER scan: NO staff panel
        self.client.force_login(self.borrower)
        bor_resp = self.client.get(scan_url)
        self.assertEqual(bor_resp.status_code, 200)
        self.assertNotContains(bor_resp, "Panel Aksi Cepat Staf")

        # LABORAN scan: shows staff panel, can download PNG & open print page
        self.client.force_login(self.laboran)
        staff_resp = self.client.get(scan_url)
        self.assertEqual(staff_resp.status_code, 200)
        self.assertContains(staff_resp, "Panel Aksi Cepat Staf")

        dl_resp = self.client.get(reverse("inventory:asset_qr_download", args=[self.asset.pk]))
        self.assertEqual(dl_resp.status_code, 200)
        self.assertEqual(dl_resp["Content-Type"], "image/png")

        print_resp = self.client.get(reverse("inventory:asset_qr_print"))
        self.assertEqual(print_resp.status_code, 200)
        self.assertContains(print_resp, self.asset.asset_code)
