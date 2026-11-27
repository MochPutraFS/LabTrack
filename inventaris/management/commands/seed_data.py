from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from inventaris.models import (
    Aset,
    JadwalPemeliharaan,
    KategoriAset,
    LaporanKerusakan,
    LokasiLab,
    Peminjaman,
    UserProfile,
)
from inventaris.services import generate_aset_qr


class Command(BaseCommand):
    help = 'Isi database dengan data sintetis awal LabTrack (idempotent).'

    @transaction.atomic
    def handle(self, *args, **options):
        today = date.today()

        # 1. Users & UserProfiles
        users_spec = [
            ('admin_lab', 'AdminLab123!', 'Budi Santoso', 'admin@labtrack.local', True, True, 'ADMIN', 'LAB-001', 'Laboratorium RPL', '0800-0000-0001'),
            ('teknisi_lab', 'TeknisiLab123!', 'Rina Kusuma', 'teknisi@labtrack.local', True, False, 'TEKNISI', 'LAB-002', 'Laboratorium Jaringan', '0800-0000-0002'),
            ('mhs_andi', 'Peminjam123!', 'Andi Pratama', 'andi@labtrack.local', False, False, 'PEMINJAM', 'H071240001', 'Sistem Informasi', '0800-0000-0003'),
            ('mhs_sari', 'Peminjam123!', 'Sari Wulandari', 'sari@labtrack.local', False, False, 'PEMINJAM', 'H071240002', 'Teknik Informatika', '0800-0000-0004'),
        ]
        users = {}
        for username, pwd, full_name, email, is_staff, is_super, role, nid, unit, telp in users_spec:
            first, last = full_name.split(' ', 1)
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'email': email,
                    'is_staff': is_staff,
                    'is_superuser': is_super,
                },
            )
            if created:
                user.set_password(pwd)
                user.save()
            UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'role': role,
                    'nomor_identitas': nid,
                    'unit_prodi': unit,
                    'no_telepon': telp,
                },
            )
            users[username] = user

        # 2. KategoriAset
        kategori_spec = [
            ('KOM', 'Komputer & PC', 'Workstation, PC desktop, laptop, dan monitor laboratorium'),
            ('JAR', 'Perangkat Jaringan', 'Router, switch managed, access point, dan alat ukur jaringan'),
            ('PRY', 'Proyektor & AV', 'Proyektor ruang kuliah/lab, layar, dan sistem audio'),
            ('KAM', 'Kamera & Multimedia', 'Kamera DSLR/mirrorless, tripod, dan perangkat produksi multimedia'),
            ('PRK', 'Peralatan Praktikum', 'Kit mikrokontroler, osiloskop, multimeter, dan perangkat praktikum'),
        ]
        kategori_map = {}
        for kode, nama, desc in kategori_spec:
            obj, _ = KategoriAset.objects.get_or_create(
                kode=kode, defaults={'nama': nama, 'deskripsi': desc}
            )
            kategori_map[kode] = obj

        # 3. LokasiLab
        lokasi_spec = [
            ('LAB-RPL', 'Lab Rekayasa Perangkat Lunak', 'Gedung FMIPA Lt. 2', 'Budi Santoso', 35),
            ('LAB-JAR', 'Lab Jaringan Komputer', 'Gedung FMIPA Lt. 2', 'Rina Kusuma', 30),
            ('LAB-DB', 'Lab Basis Data & AI', 'Gedung FMIPA Lt. 3', 'Dedi Hartono', 32),
            ('LAB-MM', 'Lab Multimedia', 'Gedung FMIPA Lt. 3', 'Maya Putri', 25),
        ]
        lokasi_map = {}
        for kode_ruang, nama_ruang, gedung, pj, cap in lokasi_spec:
            obj, _ = LokasiLab.objects.get_or_create(
                kode_ruang=kode_ruang,
                defaults={
                    'nama_ruang': nama_ruang,
                    'gedung': gedung,
                    'penanggung_jawab': pj,
                    'kapasitas': cap,
                },
            )
            lokasi_map[kode_ruang] = obj

        # 4. Aset (12 aset realistis lintas kategori, lokasi, tahun 2022-2026)
        aset_spec = [
            ('LAB-KOM-2022-001', 'PC Workstation Dell OptiPlex 7090', 'KOM', 'LAB-RPL', 'Dell OptiPlex 7090', 'SN-DL7090-01', 'Intel Core i7, RAM 16GB, SSD 512GB', date(2022, 3, 15), Decimal('14500000.00'), Decimal('1500000.00'), 5, 'BAIK', 'TERSEDIA'),
            ('LAB-KOM-2023-001', 'Laptop Praktikum Lenovo ThinkPad T14', 'KOM', 'LAB-DB', 'Lenovo ThinkPad T14', 'SN-LNT14-02', 'AMD Ryzen 7, RAM 16GB, SSD 512GB', date(2023, 6, 10), Decimal('16000000.00'), Decimal('2000000.00'), 5, 'BAIK', 'DIPINJAM'),
            ('LAB-KOM-2025-001', 'Workstation GPU NVIDIA RTX 4070', 'KOM', 'LAB-DB', 'Custom AI Rig', 'SN-AI4070-03', 'Ryzen 9, RAM 64GB, RTX 4070 12GB', date(2025, 2, 20), Decimal('28000000.00'), Decimal('3000000.00'), 5, 'BAIK', 'TERSEDIA'),
            ('LAB-JAR-2022-001', 'Router Mikrotik CCR1009', 'JAR', 'LAB-JAR', 'MikroTik CCR1009-7G-1C', 'SN-MK1009-01', '7x Gigabit Ethernet, 1x SFP+', date(2022, 8, 5), Decimal('7500000.00'), Decimal('750000.00'), 5, 'BAIK', 'TERSEDIA'),
            ('LAB-JAR-2024-001', 'Switch Managed Cisco Catalyst 2960', 'JAR', 'LAB-JAR', 'Cisco Catalyst 2960-X', 'SN-CS2960-02', '24 Port Gigabit PoE+', date(2024, 1, 18), Decimal('12000000.00'), Decimal('1000000.00'), 6, 'RUSAK_RINGAN', 'TERSEDIA'),
            ('LAB-JAR-2026-001', 'Access Point Ubiquiti UniFi U6 Pro', 'JAR', 'LAB-RPL', 'Ubiquiti U6-Pro', 'SN-UBU6-03', 'Wi-Fi 6 Dual-Band', date(2026, 2, 1), Decimal('3200000.00'), Decimal('300000.00'), 4, 'BAIK', 'TERSEDIA'),
            ('LAB-PRY-2022-001', 'Proyektor Epson EB-X500', 'PRY', 'LAB-RPL', 'Epson EB-X500', 'SN-EPX500-01', '3600 Lumens, XGA 3LCD', date(2022, 9, 12), Decimal('6800000.00'), Decimal('500000.00'), 5, 'PERBAIKAN', 'PEMELIHARAAN'),
            ('LAB-PRY-2024-001', 'Proyektor BenQ MH560 Full HD', 'PRY', 'LAB-MM', 'BenQ MH560', 'SN-BQ560-02', '3800 Lumens, 1080p', date(2024, 5, 22), Decimal('8500000.00'), Decimal('800000.00'), 5, 'BAIK', 'TERSEDIA'),
            ('LAB-KAM-2023-001', 'Kamera Mirrorless Sony A6400', 'KAM', 'LAB-MM', 'Sony Alpha A6400 + 16-50mm', 'SN-SN6400-01', '24.2MP APS-C, 4K Video', date(2023, 4, 14), Decimal('13500000.00'), Decimal('2000000.00'), 5, 'BAIK', 'DIPINJAM'),
            ('LAB-KAM-2025-001', 'Gimbal Stabilizer DJI RS 3 Mini', 'KAM', 'LAB-MM', 'DJI RS 3 Mini', 'SN-DJRS3-02', '3-Axis Gimbal, Payload 2kg', date(2025, 3, 8), Decimal('4500000.00'), Decimal('500000.00'), 4, 'RUSAK_RINGAN', 'TERSEDIA'),
            ('LAB-PRK-2022-001', 'Osiloskop Digital Rigol DS1054Z', 'PRK', 'LAB-JAR', 'Rigol DS1054Z', 'SN-RG1054-01', '50 MHz, 4 Channel, 1 GSa/s', date(2022, 11, 3), Decimal('6200000.00'), Decimal('600000.00'), 6, 'RUSAK_BERAT', 'PEMELIHARAAN'),
            ('LAB-PRK-2025-001', 'Kit IoT ESP32 & Sensor Pack', 'PRK', 'LAB-RPL', 'ESP32-S3 DevKit', 'SN-ESP32-10', 'Paket 10 board + sensor DHT22/ultrasonik', date(2025, 7, 19), Decimal('2400000.00'), Decimal('200000.00'), 3, 'BAIK', 'TERSEDIA'),
        ]
        aset_map = {}
        for kode, nama, kat, lok, merk, sn, spek, tgl, harga, residu, umur, kondisi, status in aset_spec:
            aset, _ = Aset.objects.get_or_create(
                kode_aset=kode,
                defaults={
                    'nama_aset': nama,
                    'kategori': kategori_map[kat],
                    'lokasi': lokasi_map[lok],
                    'merk_tipe': merk,
                    'nomor_seri': sn,
                    'spesifikasi': spek,
                    'tanggal_perolehan': tgl,
                    'harga_perolehan': harga,
                    'nilai_residu': residu,
                    'umur_ekonomis_tahun': umur,
                    'kondisi': kondisi,
                    'status': status,
                },
            )
            if not aset.qr_code:
                generate_aset_qr(aset)
            aset_map[kode] = aset

        # 5. Peminjaman (4 transaksi lintas status)
        peminjaman_spec = [
            ('PJM-202611-001', 'LAB-KOM-2023-001', 'mhs_andi', 'admin_lab', today - timedelta(days=3), today + timedelta(days=4), None, 'Praktikum pemrosesan data besar', 'DISETUJUI', '', 'Disetujui untuk kebutuhan praktikum.'),
            ('PJM-202611-002', 'LAB-KAM-2023-001', 'mhs_sari', 'admin_lab', today - timedelta(days=2), today + timedelta(days=2), None, 'Dokumentasi kegiatan seminar prodi', 'DISETUJUI', '', 'Harap kembalikan beserta tas kamera.'),
            ('PJM-202611-003', 'LAB-PRK-2025-001', 'mhs_andi', None, today + timedelta(days=1), today + timedelta(days=6), None, 'Uji coba prototipe sensor ruangan', 'MENUNGGU', '', ''),
            ('PJM-202610-001', 'LAB-PRY-2024-001', 'mhs_sari', 'admin_lab', today - timedelta(days=20), today - timedelta(days=17), today - timedelta(days=17), 'Presentasi tugas akhir kelompok', 'DIKEMBALIKAN', 'BAIK', 'Dikembalikan tepat waktu.'),
            ('PJM-202610-002', 'LAB-KOM-2025-001', 'mhs_andi', 'admin_lab', today - timedelta(days=10), today - timedelta(days=8), None, 'Training model pribadi di luar jadwal', 'DITOLAK', '', 'Workstation AI hanya untuk penggunaan di dalam Lab DB.'),
        ]
        for kode, aset_k, pem_u, app_u, tgl_p, tgl_rk, tgl_ka, kep, st, kond, cat in peminjaman_spec:
            Peminjaman.objects.get_or_create(
                kode_peminjaman=kode,
                defaults={
                    'aset': aset_map[aset_k],
                    'peminjam': users[pem_u],
                    'disetujui_oleh': users[app_u] if app_u else None,
                    'tanggal_pinjam': tgl_p,
                    'tanggal_rencana_kembali': tgl_rk,
                    'tanggal_kembali_aktual': tgl_ka,
                    'keperluan': kep,
                    'status': st,
                    'kondisi_saat_kembali': kond,
                    'catatan_admin': cat,
                },
            )

        # 6. LaporanKerusakan (3 laporan)
        kerusakan_spec = [
            ('RSK-202611-001', 'LAB-PRY-2022-001', 'mhs_andi', 'Lampu proyektor redup dan berkedip', 'Tampilan proyeksi redup setelah 10 menit menyala.', 'SEDANG', 'DIPROSES', 'teknisi_lab', 'Sedang dicek modul lampu dan ballast.'),
            ('RSK-202611-002', 'LAB-PRK-2022-001', 'teknisi_lab', 'Channel 2 osiloskop tidak membaca sinyal', 'Probe dan port CH2 tidak merespons kalibrasi internal.', 'BERAT', 'DILAPORKAN', None, ''),
            ('RSK-202611-003', 'LAB-JAR-2024-001', 'mhs_sari', 'Port 12 switch longgar', 'Konektor RJ45 pada port 12 mudah terlepas.', 'RINGAN', 'SELESAI', 'teknisi_lab', 'Klip port diperbaiki dan diuji normal.'),
        ]
        kerusakan_map = {}
        for kode, aset_k, pel_u, judul, desc, parah, st, dit_u, cat in kerusakan_spec:
            obj, _ = LaporanKerusakan.objects.get_or_create(
                kode_laporan=kode,
                defaults={
                    'aset': aset_map[aset_k],
                    'pelapor': users[pel_u],
                    'judul_kerusakan': judul,
                    'deskripsi': desc,
                    'tingkat_keparahan': parah,
                    'status': st,
                    'ditangani_oleh': users[dit_u] if dit_u else None,
                    'catatan_penanganan': cat,
                },
            )
            kerusakan_map[kode] = obj

        # 7. JadwalPemeliharaan (4 jadwal: termasuk <=7 hari ke depan & 1 SELESAI)
        jadwal_spec = [
            ('MNT-202611-001', 'LAB-PRY-2022-001', 'RSK-202611-001', 'KOREKTIF', today + timedelta(days=3), None, 'teknisi_lab', 'Penggantian modul lampu proyektor Epson EB-X500', Decimal('950000.00'), 'TERJADWAL', ''),
            ('MNT-202611-002', 'LAB-KOM-2022-001', None, 'PREVENTIF', today + timedelta(days=5), None, 'teknisi_lab', 'Pembersihan debu internal & pembaruan thermal paste', Decimal('150000.00'), 'TERJADWAL', ''),
            ('MNT-202611-003', 'LAB-PRK-2022-001', 'RSK-202611-002', 'KALIBRASI', today, None, 'teknisi_lab', 'Kalibrasi dan perbaikan port CH2 osiloskop Rigol', Decimal('1200000.00'), 'BERLANGSUNG', ''),
            ('MNT-202610-001', 'LAB-JAR-2024-001', 'RSK-202611-003', 'KOREKTIF', today - timedelta(days=12), today - timedelta(days=11), 'teknisi_lab', 'Perbaikan port RJ45 switch Cisco Catalyst', Decimal('250000.00'), 'SELESAI', 'Port berfungsi normal setelah perbaikan.'),
        ]
        for kode, aset_k, rsk_k, jenis, tgl_j, tgl_s, tek_u, desc, biaya, st, hasil in jadwal_spec:
            JadwalPemeliharaan.objects.get_or_create(
                kode_jadwal=kode,
                defaults={
                    'aset': aset_map[aset_k],
                    'laporan_kerusakan': kerusakan_map[rsk_k] if rsk_k else None,
                    'jenis': jenis,
                    'tanggal_jadwal': tgl_j,
                    'tanggal_selesai': tgl_s,
                    'teknisi': users[tek_u],
                    'deskripsi_kegiatan': desc,
                    'biaya': biaya,
                    'status': st,
                    'catatan_hasil': hasil,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f'Seeding selesai: {User.objects.count()} users, '
            f'{KategoriAset.objects.count()} kategori, '
            f'{LokasiLab.objects.count()} lokasi, '
            f'{Aset.objects.count()} aset, '
            f'{Peminjaman.objects.count()} peminjaman, '
            f'{LaporanKerusakan.objects.count()} kerusakan, '
            f'{JadwalPemeliharaan.objects.count()} jadwal.'
        ))
