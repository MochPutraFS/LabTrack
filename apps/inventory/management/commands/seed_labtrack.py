"""Idempotent synthetic data seeder for LabTrack (docs/07-Seed-Data-Sintetis.md)."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.services import log_audit
from apps.inventory.models import Asset, AssetLocationHistory, Category, Location
from apps.loans.models import Loan, LoanItem
from apps.maintenance.models import DamageReport, MaintenanceLog, MaintenanceSchedule

User = get_user_model()


def _aware_dt(d: date, hour: int = 9, minute: int = 0) -> datetime:
    """Build a timezone-aware datetime from a date in the current project timezone."""
    return timezone.make_aware(datetime.combine(d, time(hour=hour, minute=minute)))


class Command(BaseCommand):
    help = "Seed synthetic demo data for LabTrack idempotently (safe to run multiple times)."

    @transaction.atomic
    def handle(self, *args, **options):
        today = timezone.localdate()

        users = self._seed_users()
        categories = self._seed_categories()
        locations = self._seed_locations()
        assets = self._seed_assets(categories, locations, users["admin_lab"])
        loans_count = self._seed_loans(users, assets, today)
        damages = self._seed_damage_reports(users, assets, today)
        schedules = self._seed_maintenance_schedules(users, assets, today)
        logs_count = self._seed_maintenance_logs(users, assets, schedules, damages, today)

        log_audit(
            actor=users["admin_lab"],
            action="SEED_LABTRACK_EXECUTED",
            entity_type="System",
            entity_id="seed_labtrack",
            metadata={
                "users": len(users),
                "categories": len(categories),
                "locations": len(locations),
                "assets": len(assets),
                "loans": loans_count,
                "damage_reports": len(damages),
                "maintenance_schedules": len(schedules),
                "maintenance_logs": logs_count,
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed LabTrack selesai: {len(users)} user, {len(categories)} kategori, "
                f"{len(locations)} lokasi, {len(assets)} aset (+QR PNG), {loans_count} transaksi pinjaman, "
                f"{len(damages)} laporan kerusakan, {len(schedules)} jadwal pemeliharaan, "
                f"{logs_count} log pemeliharaan."
            )
        )

    def _seed_users(self) -> dict[str, User]:
        specs = [
            {
                "username": "admin_lab",
                "full_name": "Dr. Hendra Wijaya",
                "email": "admin.lab@labtrack.local",
                "role": User.Role.ADMIN,
                "identifier_number": "NIP-19800101001",
                "phone_number": "0811-4000-0001",
                "department": "Kepala Laboratorium",
                "is_staff": True,
                "is_superuser": True,
            },
            {
                "username": "laboran_rpl",
                "full_name": "Rina Kartika",
                "email": "rina.laboran@labtrack.local",
                "role": User.Role.LABORAN,
                "identifier_number": "STF-202104002",
                "phone_number": "0811-4000-0002",
                "department": "Lab RPL & Basis Data",
                "is_staff": True,
                "is_superuser": False,
            },
            {
                "username": "laboran_jar",
                "full_name": "Dimas Pratama",
                "email": "dimas.laboran@labtrack.local",
                "role": User.Role.LABORAN,
                "identifier_number": "STF-202208003",
                "phone_number": "0811-4000-0003",
                "department": "Lab Jaringan & IoT",
                "is_staff": True,
                "is_superuser": False,
            },
            {
                "username": "mhs_andi",
                "full_name": "Andi Saputra",
                "email": "andi.mhs@labtrack.local",
                "role": User.Role.BORROWER,
                "identifier_number": "H071241001",
                "phone_number": "0812-4000-0004",
                "department": "Sistem Informasi",
                "is_staff": False,
                "is_superuser": False,
            },
            {
                "username": "dosen_sari",
                "full_name": "Sari Wulandari, M.Kom",
                "email": "sari.dosen@labtrack.local",
                "role": User.Role.BORROWER,
                "identifier_number": "NIP-19890512004",
                "phone_number": "0812-4000-0005",
                "department": "Sistem Informasi",
                "is_staff": False,
                "is_superuser": False,
            },
        ]

        result: dict[str, User] = {}
        for item in specs:
            username = item["username"]
            defaults = {k: v for k, v in item.items() if k != "username"}
            defaults["is_active"] = True
            user, created = User.objects.update_or_create(
                username=username,
                defaults=defaults,
            )
            if created or not user.check_password("LabTrack2026!"):
                user.set_password("LabTrack2026!")
                user.save(update_fields=["password"])
            result[username] = user
        return result

    def _seed_categories(self) -> dict[str, Category]:
        specs = [
            ("KOM", "Komputer & Workstation", 5, "PC desktop, laptop praktikum, monitor, server mini"),
            ("JAR", "Perangkat Jaringan", 5, "Router, managed switch, access point, kabel tester"),
            ("PRJ", "Proyektor & Audio Visual", 6, "Proyektor LCD/Laser, layar proyeksi, speaker ruang lab"),
            ("KAM", "Kamera & Dokumentasi", 5, "Kamera DSLR/Mirrorless, tripod, webcam konferensi"),
            ("PRK", "Peralatan Praktikum IoT", 4, "Microcontroller kit, sensor set, breadboard, robotika"),
            ("UKR", "Instrumen Pengukuran", 7, "Osiloskop digital, multimeter, power supply DC"),
        ]
        result: dict[str, Category] = {}
        for code, name, life, desc in specs:
            obj, _ = Category.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "default_useful_life_years": life,
                    "description": desc,
                },
            )
            result[code] = obj
        return result

    def _seed_locations(self) -> dict[str, Location]:
        specs = [
            ("LAB-RPL", "Lab Rekayasa Perangkat Lunak", "Gedung Sains Terpadu", "Lantai 2", "Rina Kartika"),
            ("LAB-JAR", "Lab Jaringan Komputer", "Gedung Sains Terpadu", "Lantai 2", "Dimas Pratama"),
            ("LAB-BD", "Lab Basis Data & Analitik", "Gedung Sains Terpadu", "Lantai 3", "Rina Kartika"),
            ("LAB-IOT", "Lab Multimedia & IoT", "Gedung Sains Terpadu", "Lantai 3", "Dimas Pratama"),
            ("GDG-UTM", "Ruang Penyimpanan Utama Lab", "Gedung Sains Terpadu", "Lantai 1", "Dr. Hendra Wijaya"),
        ]
        result: dict[str, Location] = {}
        for code, name, building, floor, pic in specs:
            obj, _ = Location.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "building": building,
                    "floor": floor,
                    "pic_name": pic,
                    "is_active": True,
                },
            )
            result[code] = obj
        return result

    def _seed_assets(
        self,
        categories: dict[str, Category],
        locations: dict[str, Location],
        admin_user: User,
    ) -> dict[str, Asset]:
        # (code, name, cat, loc, acq_date, cost, life, salvage, status, condition, brand, model, sn, specs)
        specs = [
            (
                "LAB-KOM-2024-0001",
                "PC Workstation Dell OptiPlex 7010",
                "KOM",
                "LAB-RPL",
                date(2024, 2, 15),
                Decimal("14500000.00"),
                5,
                Decimal("2000000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.GOOD,
                "Dell",
                "OptiPlex 7010 SFF",
                "DL-7010-24001",
                "Intel Core i7-13700, RAM 16GB DDR4, SSD NVMe 512GB, Monitor 24 inci",
            ),
            (
                "LAB-KOM-2024-0002",
                "PC Workstation Dell OptiPlex 7010 #2",
                "KOM",
                "LAB-RPL",
                date(2024, 2, 15),
                Decimal("14500000.00"),
                5,
                Decimal("2000000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.GOOD,
                "Dell",
                "OptiPlex 7010 SFF",
                "DL-7010-24002",
                "Intel Core i7-13700, RAM 16GB DDR4, SSD NVMe 512GB, Monitor 24 inci",
            ),
            (
                "LAB-KOM-2025-0003",
                "Laptop Praktikum Lenovo ThinkPad E14",
                "KOM",
                "LAB-RPL",
                date(2025, 1, 20),
                Decimal("13000000.00"),
                5,
                Decimal("2000000.00"),
                Asset.Status.BORROWED,
                Asset.Condition.GOOD,
                "Lenovo",
                "ThinkPad E14 Gen 5",
                "LN-E14-25003",
                "Intel Core i5-1335U, RAM 16GB, SSD 512GB, Layar 14 inci FHD",
            ),
            (
                "LAB-KOM-2025-0004",
                "Laptop Praktikum Lenovo ThinkPad E14 #2",
                "KOM",
                "LAB-BD",
                date(2025, 1, 20),
                Decimal("13000000.00"),
                5,
                Decimal("2000000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.MINOR_DAMAGE,
                "Lenovo",
                "ThinkPad E14 Gen 5",
                "LN-E14-25004",
                "Intel Core i5-1335U, RAM 16GB, SSD 512GB, Layar 14 inci FHD",
            ),
            (
                "LAB-KOM-2022-0005",
                "Mini Server Rack HP ProLiant Micro",
                "KOM",
                "LAB-BD",
                date(2022, 8, 10),
                Decimal("26000000.00"),
                6,
                Decimal("4000000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.GOOD,
                "HPE",
                "ProLiant MicroServer Gen10 Plus",
                "HP-MS10-22005",
                "Intel Xeon E-2224, RAM 32GB ECC, 4x 2TB Enterprise SATA RAID-10",
            ),
            (
                "LAB-JAR-2023-0001",
                "Cisco Catalyst 2960-X 24-Port Switch",
                "JAR",
                "LAB-JAR",
                date(2023, 3, 12),
                Decimal("11500000.00"),
                5,
                Decimal("1500000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.GOOD,
                "Cisco",
                "Catalyst 2960-X 24TS-L",
                "CS-2960X-23001",
                "24-Port Gigabit Ethernet Managed Switch, 4x SFP Uplink",
            ),
            (
                "LAB-JAR-2023-0002",
                "MikroTik RB4011iGS+ Router",
                "JAR",
                "LAB-JAR",
                date(2023, 3, 12),
                Decimal("4200000.00"),
                5,
                Decimal("500000.00"),
                Asset.Status.BORROWED,
                Asset.Condition.GOOD,
                "MikroTik",
                "RB4011iGS+RM",
                "MT-4011-23002",
                "10x Gigabit Ethernet, 1x SFP+ 10Gbps, Quad-core Cortex A15",
            ),
            (
                "LAB-JAR-2024-0003",
                "Ubiquiti UniFi U6 Pro Access Point",
                "JAR",
                "LAB-JAR",
                date(2024, 6, 5),
                Decimal("3100000.00"),
                5,
                Decimal("300000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.GOOD,
                "Ubiquiti",
                "UniFi U6-Pro",
                "UB-U6P-24003",
                "Dual-band Wi-Fi 6 (802.11ax), PoE+, 5.3 Gbps aggregate throughput",
            ),
            (
                "LAB-JAR-2021-0004",
                "Fluke Networks CableIQ Tester",
                "JAR",
                "LAB-JAR",
                date(2021, 5, 18),
                Decimal("8500000.00"),
                5,
                Decimal("1000000.00"),
                Asset.Status.MAINTENANCE,
                Asset.Condition.MINOR_DAMAGE,
                "Fluke Networks",
                "CableIQ Qualification Tester",
                "FL-CIQ-21004",
                "Penguji kualifikasi kabel UTP/STP Cat5e/Cat6/Cat6a hingga 1000BASE-T",
            ),
            (
                "LAB-PRJ-2023-0001",
                "Proyektor Epson EB-X51 XGA",
                "PRJ",
                "LAB-RPL",
                date(2023, 7, 1),
                Decimal("7800000.00"),
                6,
                Decimal("800000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.GOOD,
                "Epson",
                "EB-X51",
                "EP-X51-23001",
                "3LCD 3800 Lumens, Resolusi XGA, HDMI/VGA, Lamp life 12.000 jam",
            ),
            (
                "LAB-PRJ-2022-0002",
                "Proyektor BenQ MH560 Full HD",
                "PRJ",
                "LAB-BD",
                date(2022, 4, 14),
                Decimal("9200000.00"),
                6,
                Decimal("1000000.00"),
                Asset.Status.DAMAGED,
                Asset.Condition.MAJOR_DAMAGE,
                "BenQ",
                "MH560",
                "BQ-MH560-22002",
                "DLP 3800 Lumens, Full HD 1080p, Dual HDMI",
            ),
            (
                "LAB-PRJ-2025-0003",
                "Wireless Presentation Clicker Logitech R800",
                "PRJ",
                "GDG-UTM",
                date(2025, 2, 10),
                Decimal("1500000.00"),
                4,
                Decimal("150000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.GOOD,
                "Logitech",
                "R800 Professional Presenter",
                "LG-R800-25003",
                "Green laser pointer, LCD timer, jangkauan wireless 30 meter",
            ),
            (
                "LAB-KAM-2024-0001",
                "Kamera Mirrorless Sony Alpha A6400 Kit",
                "KAM",
                "LAB-IOT",
                date(2024, 3, 22),
                Decimal("16500000.00"),
                5,
                Decimal("3000000.00"),
                Asset.Status.BORROWED,
                Asset.Condition.GOOD,
                "Sony",
                "Alpha A6400 + 16-50mm OSS",
                "SN-A6400-24001",
                "Sensor APS-C 24.2MP, 4K HDR Video, Real-time Eye AF",
            ),
            (
                "LAB-KAM-2024-0002",
                "Tripod Profesional Manfrotto Compact",
                "KAM",
                "LAB-IOT",
                date(2024, 3, 22),
                Decimal("2100000.00"),
                6,
                Decimal("300000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.GOOD,
                "Manfrotto",
                "Compact Action Aluminum",
                "MF-CA-24002",
                "Tinggi maks 155cm, beban maks 1.5kg, joystick head + tas",
            ),
            (
                "LAB-KAM-2025-0003",
                "Webcam Konferensi Logitech Brio 4K",
                "KAM",
                "LAB-RPL",
                date(2025, 6, 15),
                Decimal("3400000.00"),
                4,
                Decimal("400000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.GOOD,
                "Logitech",
                "Brio 4K Ultra HD Pro",
                "LG-BRIO-25003",
                "4K 30fps / 1080p 60fps, RightLight 3 HDR, Dual Omni-directional Mic",
            ),
            (
                "LAB-PRK-2025-0001",
                "Raspberry Pi 5 8GB Starter Kit Set A",
                "PRK",
                "LAB-IOT",
                date(2025, 3, 1),
                Decimal("2800000.00"),
                4,
                Decimal("300000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.GOOD,
                "Raspberry Pi",
                "Model 5 8GB Starter Kit",
                "RP5-8G-25001",
                "BCM2712 Quad-core 2.4GHz, RAM 8GB, Active Cooler, PSU 27W, MicroSD 64GB",
            ),
            (
                "LAB-PRK-2025-0002",
                "Arduino Mega 2560 & 37-in-1 Sensor Kit",
                "PRK",
                "LAB-IOT",
                date(2025, 3, 1),
                Decimal("1850000.00"),
                4,
                Decimal("200000.00"),
                Asset.Status.BORROWED,
                Asset.Condition.GOOD,
                "Arduino",
                "Mega 2560 Rev3 Bundle",
                "AR-M2560-25002",
                "ATmega2560, 54 digital I/O, 37 modul sensor, breadboard & jumper set",
            ),
            (
                "LAB-PRK-2023-0003",
                "ESP32 IoT Trainer Board Modul B",
                "PRK",
                "LAB-IOT",
                date(2023, 9, 10),
                Decimal("2400000.00"),
                4,
                Decimal("250000.00"),
                Asset.Status.MAINTENANCE,
                Asset.Condition.MINOR_DAMAGE,
                "Espressif",
                "ESP32-WROOM-32 Trainer Kit",
                "ES-TRN-23003",
                "Wi-Fi + BLE Dual-core, OLED 0.96 inci, DHT22, Relay 4-Ch, MQTT ready",
            ),
            (
                "LAB-UKR-2022-0001",
                "Osiloskop Digital Rigol DS1054Z 4-Ch",
                "UKR",
                "LAB-IOT",
                date(2022, 11, 5),
                Decimal("7900000.00"),
                7,
                Decimal("1200000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.GOOD,
                "Rigol",
                "DS1054Z",
                "RG-1054Z-22001",
                "4 Channel, 50 MHz Bandwidth, 1 GSa/s Sample Rate, 4x Probe",
            ),
            (
                "LAB-UKR-2021-0002",
                "Multimeter Digital Fluke 117",
                "UKR",
                "GDG-UTM",
                date(2021, 9, 20),
                Decimal("4600000.00"),
                7,
                Decimal("600000.00"),
                Asset.Status.AVAILABLE,
                Asset.Condition.GOOD,
                "Fluke",
                "117 True-RMS",
                "FL-117-21002",
                "True-RMS Digital Multimeter, VoltAlert Non-Contact Voltage Detection",
            ),
        ]

        result: dict[str, Asset] = {}
        for (
            asset_code,
            name,
            cat_code,
            loc_code,
            acq_date,
            cost,
            life,
            salvage,
            status,
            condition,
            brand,
            model_name,
            serial_number,
            specifications,
        ) in specs:
            asset, _ = Asset.objects.update_or_create(
                asset_code=asset_code,
                defaults={
                    "name": name,
                    "category": categories[cat_code],
                    "location": locations[loc_code],
                    "brand": brand,
                    "model_name": model_name,
                    "serial_number": serial_number,
                    "acquisition_date": acq_date,
                    "acquisition_cost": cost,
                    "useful_life_years": life,
                    "salvage_value": salvage,
                    "status": status,
                    "condition": condition,
                    "specifications": specifications,
                    "is_active": True,
                },
            )
            asset.generate_qr_code()
            if not asset.location_histories.exists():
                AssetLocationHistory.objects.create(
                    asset=asset,
                    from_location=None,
                    to_location=asset.location,
                    moved_by=admin_user,
                    moved_at=_aware_dt(acq_date, hour=10),
                    reason="Penempatan awal registrasi inventaris laboratorium.",
                )
            result[asset_code] = asset
        return result

    def _seed_loans(
        self,
        users: dict[str, User],
        assets: dict[str, Asset],
        today: date,
    ) -> int:
        loan_specs = [
            {
                "loan_number": "LOAN-20261120-0001",
                "loan_channel": Loan.Channel.ONLINE,
                "borrower_user": users["mhs_andi"],
                "borrower_name": users["mhs_andi"].full_name,
                "borrower_identifier": users["mhs_andi"].identifier_number or "H071241001",
                "borrower_contact": users["mhs_andi"].phone_number,
                "purpose": "Pengembangan proyek praktikum Rekayasa Perangkat Lunak.",
                "borrow_date": today - timedelta(days=3),
                "due_date": today + timedelta(days=4),
                "handed_over_at": _aware_dt(today - timedelta(days=3), hour=9, minute=30),
                "returned_at": None,
                "status": Loan.Status.ACTIVE,
                "processed_by": users["laboran_rpl"],
                "received_by": None,
                "notes": "Disetujui dan diserahkan lengkap dengan adaptor charger.",
                "items": [
                    ("LAB-KOM-2025-0003", Asset.Condition.GOOD, "", ""),
                ],
            },
            {
                "loan_number": "LOAN-20261115-0002",
                "loan_channel": Loan.Channel.WALK_IN,
                "borrower_user": None,
                "borrower_name": "Budi Santoso",
                "borrower_identifier": "H071231088",
                "borrower_contact": "0812-0000-1122",
                "purpose": "Simulasi routing OSPF dan VLAN untuk tugas akhir.",
                "borrow_date": today - timedelta(days=10),
                "due_date": today - timedelta(days=3),
                "handed_over_at": _aware_dt(today - timedelta(days=10), hour=13, minute=15),
                "returned_at": None,
                "status": Loan.Status.OVERDUE,
                "processed_by": users["laboran_jar"],
                "received_by": None,
                "notes": "Peminjaman walk-in tanpa akun. Telah melewati batas jatuh tempo.",
                "items": [
                    ("LAB-JAR-2023-0002", Asset.Condition.GOOD, "", ""),
                ],
            },
            {
                "loan_number": "LOAN-20261125-0003",
                "loan_channel": Loan.Channel.WALK_IN,
                "borrower_user": users["dosen_sari"],
                "borrower_name": users["dosen_sari"].full_name,
                "borrower_identifier": users["dosen_sari"].identifier_number or "NIP-19890512004",
                "borrower_contact": users["dosen_sari"].phone_number,
                "purpose": "Dokumentasi dan demo prototipe IoT kuliah Sistem Embedded.",
                "borrow_date": today - timedelta(days=2),
                "due_date": today + timedelta(days=5),
                "handed_over_at": _aware_dt(today - timedelta(days=2), hour=10, minute=0),
                "returned_at": None,
                "status": Loan.Status.ACTIVE,
                "processed_by": users["laboran_rpl"],
                "received_by": None,
                "notes": "Walk-in terhubung akun dosen.",
                "items": [
                    ("LAB-KAM-2024-0001", Asset.Condition.GOOD, "", ""),
                    ("LAB-PRK-2025-0002", Asset.Condition.GOOD, "", ""),
                ],
            },
            {
                "loan_number": "LOAN-20261127-0004",
                "loan_channel": Loan.Channel.ONLINE,
                "borrower_user": users["mhs_andi"],
                "borrower_name": users["mhs_andi"].full_name,
                "borrower_identifier": users["mhs_andi"].identifier_number or "H071241001",
                "borrower_contact": users["mhs_andi"].phone_number,
                "purpose": "Uji coba edge computing untuk tugas kelompok IoT.",
                "borrow_date": today + timedelta(days=1),
                "due_date": today + timedelta(days=6),
                "handed_over_at": None,
                "returned_at": None,
                "status": Loan.Status.PENDING,
                "processed_by": None,
                "received_by": None,
                "notes": "Menunggu persetujuan laboran.",
                "items": [
                    ("LAB-PRK-2025-0001", Asset.Condition.GOOD, "", ""),
                ],
            },
            {
                "loan_number": "LOAN-20261010-0005",
                "loan_channel": Loan.Channel.ONLINE,
                "borrower_user": users["dosen_sari"],
                "borrower_name": users["dosen_sari"].full_name,
                "borrower_identifier": users["dosen_sari"].identifier_number or "NIP-19890512004",
                "borrower_contact": users["dosen_sari"].phone_number,
                "purpose": "Seminar hasil penelitian mahasiswa Sistem Informasi.",
                "borrow_date": date(2026, 10, 10),
                "due_date": date(2026, 10, 15),
                "handed_over_at": _aware_dt(date(2026, 10, 10), hour=8, minute=30),
                "returned_at": _aware_dt(date(2026, 10, 14), hour=15, minute=45),
                "status": Loan.Status.RETURNED,
                "processed_by": users["laboran_rpl"],
                "received_by": users["laboran_rpl"],
                "notes": "Dikembalikan tepat waktu dengan kelengkapan remote dan tas.",
                "items": [
                    (
                        "LAB-PRJ-2023-0001",
                        Asset.Condition.GOOD,
                        Asset.Condition.GOOD,
                        "Unit bersih dan berfungsi normal.",
                    ),
                ],
            },
            {
                "loan_number": "LOAN-20260918-0006",
                "loan_channel": Loan.Channel.WALK_IN,
                "borrower_user": None,
                "borrower_name": "Nadia Putri",
                "borrower_identifier": "H071241045",
                "borrower_contact": "0813-0000-3344",
                "purpose": "Pengukuran sinyal PWM untuk praktikum rangkaian digital.",
                "borrow_date": date(2026, 9, 18),
                "due_date": date(2026, 9, 22),
                "handed_over_at": _aware_dt(date(2026, 9, 18), hour=11, minute=0),
                "returned_at": _aware_dt(date(2026, 9, 21), hour=16, minute=10),
                "status": Loan.Status.RETURNED,
                "processed_by": users["laboran_jar"],
                "received_by": users["laboran_jar"],
                "notes": "Seluruh 4 probe osiloskop kembali lengkap.",
                "items": [
                    (
                        "LAB-UKR-2022-0001",
                        Asset.Condition.GOOD,
                        Asset.Condition.GOOD,
                        "Kalibrasi dan layar dalam kondisi baik.",
                    ),
                ],
            },
        ]

        for spec in loan_specs:
            items = spec["items"]
            defaults = {k: v for k, v in spec.items() if k not in ("loan_number", "items")}
            loan, _ = Loan.objects.update_or_create(
                loan_number=spec["loan_number"],
                defaults=defaults,
            )
            for asset_code, cond_out, cond_ret, ret_notes in items:
                LoanItem.objects.update_or_create(
                    loan=loan,
                    asset=assets[asset_code],
                    defaults={
                        "condition_on_checkout": cond_out,
                        "condition_on_return": cond_ret,
                        "return_notes": ret_notes,
                    },
                )
        return len(loan_specs)

    def _seed_damage_reports(
        self,
        users: dict[str, User],
        assets: dict[str, Asset],
        today: date,
    ) -> dict[str, DamageReport]:
        specs = [
            {
                "report_number": "DMG-20261101-0001",
                "asset": assets["LAB-PRJ-2022-0002"],
                "reported_by": users["dosen_sari"],
                "handled_by": users["laboran_rpl"],
                "severity": DamageReport.Severity.HIGH,
                "description": "Lampu proyektor mati total & modul power rusak berat",
                "status": DamageReport.Status.UNREPAIRABLE,
                "resolution_notes": "Hasil diagnosa teknisi: mainboard power terbakar dan suku cadang tidak ekonomis; direkomendasikan penghapusbukuan.",
                "resolved_at": _aware_dt(today - timedelta(days=12), hour=14),
            },
            {
                "report_number": "DMG-20261110-0002",
                "asset": assets["LAB-JAR-2021-0004"],
                "reported_by": users["laboran_jar"],
                "handled_by": users["laboran_jar"],
                "severity": DamageReport.Severity.MEDIUM,
                "description": "Port RJ45 utama longgar, sedang kalibrasi & penggantian konektor",
                "status": DamageReport.Status.IN_REPAIR,
                "resolution_notes": "Menunggu proses soldering konektor RJ45 baru dan uji kalibrasi ulang.",
                "resolved_at": None,
            },
            {
                "report_number": "DMG-20261118-0003",
                "asset": assets["LAB-PRK-2023-0003"],
                "reported_by": users["mhs_andi"],
                "handled_by": users["laboran_jar"],
                "severity": DamageReport.Severity.LOW,
                "description": "Regulator tegangan 3.3V tidak stabil",
                "status": DamageReport.Status.IN_REPAIR,
                "resolution_notes": "Penggantian IC regulator AMS1117 sedang dikerjakan di meja teknisi.",
                "resolved_at": None,
            },
            {
                "report_number": "DMG-20261124-0004",
                "asset": assets["LAB-KOM-2025-0004"],
                "reported_by": users["mhs_andi"],
                "handled_by": None,
                "severity": DamageReport.Severity.LOW,
                "description": "Engsel layar kiri sedikit longgar, perangkat masih berfungsi normal",
                "status": DamageReport.Status.REPORTED,
                "resolution_notes": "",
                "resolved_at": None,
            },
        ]

        result: dict[str, DamageReport] = {}
        for spec in specs:
            defaults = {k: v for k, v in spec.items() if k != "report_number"}
            obj, _ = DamageReport.objects.update_or_create(
                report_number=spec["report_number"],
                defaults=defaults,
            )
            result[spec["report_number"]] = obj
        return result

    def _seed_maintenance_schedules(
        self,
        users: dict[str, User],
        assets: dict[str, Asset],
        today: date,
    ) -> dict[str, MaintenanceSchedule]:
        specs = [
            # 2 schedules due within H+3 and H+5 (trigger H-7 dashboard reminder)
            (
                "due_h3",
                assets["LAB-PRJ-2023-0001"],
                "Pembersihan Filter Udara & Kalibrasi Warna Proyektor",
                "Bersihkan filter debu, cek jam lampu, dan verifikasi fokus proyeksi.",
                MaintenanceSchedule.Frequency.QUARTERLY,
                today + timedelta(days=3),
                users["laboran_rpl"],
                MaintenanceSchedule.Status.SCHEDULED,
                None,
            ),
            (
                "due_h5",
                assets["LAB-JAR-2023-0001"],
                "Pembaruan Firmware & Audit Port Switch Cisco",
                "Backup konfigurasi VLAN, cek status PoE/port, dan bersihkan ventilasi rak.",
                MaintenanceSchedule.Frequency.SEMI_ANNUAL,
                today + timedelta(days=5),
                users["laboran_jar"],
                MaintenanceSchedule.Status.SCHEDULED,
                None,
            ),
            # 1 overdue schedule (H-2, OVERDUE) on LAB-KOM-2022-0005
            (
                "overdue_server",
                assets["LAB-KOM-2022-0005"],
                "Pemeriksaan Kesehatan RAID & Pembersihan Debu Mini Server",
                "Cek SMART disk, suhu prosesor, pembaruan patch keamanan OS, dan backup sistem.",
                MaintenanceSchedule.Frequency.MONTHLY,
                today - timedelta(days=2),
                users["laboran_rpl"],
                MaintenanceSchedule.Status.OVERDUE,
                _aware_dt(today - timedelta(days=32), hour=10),
            ),
            # 2 schedules next month (QUARTERLY & SEMI_ANNUAL)
            (
                "next_month_q",
                assets["LAB-KOM-2024-0001"],
                "Pemeliharaan Berkala Workstation & Thermal Paste Check",
                "Pembersihan debu casing, update driver, dan cek kesehatan SSD.",
                MaintenanceSchedule.Frequency.QUARTERLY,
                today + timedelta(days=30),
                users["laboran_rpl"],
                MaintenanceSchedule.Status.SCHEDULED,
                None,
            ),
            (
                "next_month_sa",
                assets["LAB-UKR-2022-0001"],
                "Kalibrasi Probe & Self-Calibration Osiloskop Rigol",
                "Jalankan auto-calibration internal dan inspeksi kelengkapan 4 probe.",
                MaintenanceSchedule.Frequency.SEMI_ANNUAL,
                today + timedelta(days=35),
                users["laboran_jar"],
                MaintenanceSchedule.Status.SCHEDULED,
                None,
            ),
            # 1 ONCE schedule that is COMPLETED
            (
                "once_completed",
                assets["LAB-JAR-2024-0003"],
                "Pemasangan Bracket & Uji Sinyal Awal Access Point U6 Pro",
                "Inspeksi mounting plafon, uji kekuatan sinyal Wi-Fi 6 seluruh ruang Lab Jaringan.",
                MaintenanceSchedule.Frequency.ONCE,
                today - timedelta(days=20),
                users["laboran_jar"],
                MaintenanceSchedule.Status.COMPLETED,
                _aware_dt(today - timedelta(days=20), hour=15, minute=30),
            ),
        ]

        result: dict[str, MaintenanceSchedule] = {}
        for key, asset, title, desc, freq, due, assignee, status, completed_at in specs:
            obj, _ = MaintenanceSchedule.objects.update_or_create(
                asset=asset,
                title=title,
                defaults={
                    "description": desc,
                    "frequency": freq,
                    "next_due_date": due,
                    "assigned_to": assignee,
                    "status": status,
                    "last_completed_at": completed_at,
                },
            )
            result[key] = obj
        return result

    def _seed_maintenance_logs(
        self,
        users: dict[str, User],
        assets: dict[str, Asset],
        schedules: dict[str, MaintenanceSchedule],
        damages: dict[str, DamageReport],
        today: date,
    ) -> int:
        # 5 historical logs spread over the last 4 months (costs Rp 150.000 - Rp 750.000)
        specs = [
            {
                "asset": assets["LAB-KOM-2022-0005"],
                "schedule": schedules["overdue_server"],
                "damage_report": None,
                "performed_by": users["laboran_rpl"],
                "performed_date": today - timedelta(days=105),
                "summary": "Penggantian kipas pendingin belakang server dan pembersihan debu internal.",
                "cost": Decimal("650000.00"),
                "result_condition": Asset.Condition.GOOD,
            },
            {
                "asset": assets["LAB-PRJ-2023-0001"],
                "schedule": schedules["due_h3"],
                "damage_report": None,
                "performed_by": users["laboran_rpl"],
                "performed_date": today - timedelta(days=80),
                "summary": "Pembersihan filter udara proyektor dan penggantian kabel HDMI 5 meter.",
                "cost": Decimal("250000.00"),
                "result_condition": Asset.Condition.GOOD,
            },
            {
                "asset": assets["LAB-UKR-2021-0002"],
                "schedule": None,
                "damage_report": None,
                "performed_by": users["laboran_jar"],
                "performed_date": today - timedelta(days=52),
                "summary": "Penggantian sekring pengaman dan kabel test lead multimeter Fluke 117.",
                "cost": Decimal("420000.00"),
                "result_condition": Asset.Condition.GOOD,
            },
            {
                "asset": assets["LAB-JAR-2024-0003"],
                "schedule": schedules["once_completed"],
                "damage_report": None,
                "performed_by": users["laboran_jar"],
                "performed_date": today - timedelta(days=20),
                "summary": "Pemasangan bracket plafon, crimping ulang kabel Cat6 PoE, dan uji throughput.",
                "cost": Decimal("150000.00"),
                "result_condition": Asset.Condition.GOOD,
            },
            {
                "asset": assets["LAB-JAR-2021-0004"],
                "schedule": None,
                "damage_report": damages["DMG-20261110-0002"],
                "performed_by": users["laboran_jar"],
                "performed_date": today - timedelta(days=8),
                "summary": "Diagnosa awal port RJ45 Fluke CableIQ dan pemesanan modul konektor pengganti.",
                "cost": Decimal("750000.00"),
                "result_condition": Asset.Condition.MINOR_DAMAGE,
            },
        ]

        for spec in specs:
            MaintenanceLog.objects.update_or_create(
                asset=spec["asset"],
                performed_date=spec["performed_date"],
                summary=spec["summary"],
                defaults={
                    "schedule": spec["schedule"],
                    "damage_report": spec["damage_report"],
                    "performed_by": spec["performed_by"],
                    "cost": spec["cost"],
                    "result_condition": spec["result_condition"],
                },
            )
        return len(specs)
