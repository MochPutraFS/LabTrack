# AGENTS.md — Panduan Utama Pengembangan AI untuk LabTrack

Dokumen ini adalah kontrak teknis tunggal (*single source of truth*) bagi setiap AI Coding Agent (Antigravity, Claude, Gemini, dll.) yang mengerjakan repositori **LabTrack** (Sistem Manajemen Inventaris dan Pemeliharaan Aset Laboratorium Berbasis Web — Proyek RPL Kelompok 3).

**WAJIB DIBACA SEBELUM MENULIS KODE APA PUN.**

---

## 1. Identitas & Tujuan Proyek
* **Nama Proyek**: LabTrack
* **Judul Formal**: Rancang Bangun Sistem Manajemen Inventaris dan Pemeliharaan Aset Laboratorium Berbasis Web
* **Kelompok**: Kelompok 3 — Mata Kuliah Rekayasa Perangkat Lunak 2026 (Sistem Informasi, FMIPA UNHAS)
* **Tujuan**: Membangun aplikasi web manajemen aset laboratorium yang terstruktur, *auditable*, dan siap didemonstrasikan beserta dokumentasi teknis untuk pengumpulan SIKOLA.

---

## 2. Kunci Tech Stack (Dilarang Mengganti Tanpa Izin)
* **Bahasa Pemrograman**: Python 3.11+ (direkomendasikan 3.12)
* **Framework Backend & Web**: Django 5.1+ (Arsitektur MVT + Service Layer)
* **Database**: PostgreSQL 15+ (menggunakan driver `psycopg[binary]`)
* **Frontend & Styling**: Django Templates + Tailwind CSS (via Tailwind Play CDN atau standalone CSS terkompilasi agar ringan di Windows tanpa dependensi Node kompleks) + Alpine.js (opsional untuk interaksi ringan seperti modal/dropdown)
* **Visualisasi Grafik**: Chart.js 4.x (via CDN/lokal statis)
* **QR Code Generator**: `qrcode[pil]` + `Pillow`
* **Ekspor Laporan**:
  * CSV: modul standar Python `csv`
  * PDF: `reportlab` (dipilih agar 100% stabil di Windows tanpa memerlukan dependensi native GTK/Cairo seperti WeasyPrint)
* **Konfigurasi Lingkungan**: `python-dotenv` (membaca file `.env`)
* **Testing**: Django `TestCase` (`python manage.py test`)

---

## 3. Konfigurasi Database Lokal (PostgreSQL)
Gunakan variabel lingkungan melalui file `.env` (dan sediakan `.env.example` di repositori, **jangan commit `.env` ke Git**).

Konfigurasi default untuk lingkungan pengembangan lokal proyek ini:
```env
DEBUG=True
SECRET_KEY=django-insecure-labtrack-dev-key-change-in-production
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=labtrack_db
DB_USER=postgres
DB_PASSWORD=orion6
DB_HOST=localhost
DB_PORT=5432
```

---

## 4. Peta Dokumen Spesifikasi (`docs/`)
Setiap implementasi HARUS merujuk pada dokumen terkait sebelum mulai mengedit kode:

| File | Cakupan Utama |
| :--- | :--- |
| `docs/01-PRD-dan-SRS.md` | Ruang lingkup, RBAC 3 peran, kebutuhan fungsional (`FR-01` s.d. `FR-10`), NFR, dan kriteria penerimaan |
| `docs/02-Business-Flowchart.md` | Alur proses bisnis (Mermaid), mekanisme peminjaman Hybrid, dan aturan State Machine |
| `docs/03-UML-Diagrams.md` | Use Case, Activity, Sequence, dan Class Diagram (Mermaid) |
| `docs/04-Database-ERD-Schema.md` | ERD, spesifikasi 11 tabel PostgreSQL, indeks, constraint, dan rumus penyusutan Garis Lurus |
| `docs/05-Architecture-dan-API.md` | Struktur folder Django modular, Service Layer, daftar URL/endpoint, kontrak JSON, dan keamanan |
| `docs/06-UI-UX-Design-System.md` | Palet warna lembut, tipografi, layout, komponen UI, sitemap per role, dan halaman cetak QR |
| `docs/07-Seed-Data-Sintetis.md` | Spesifikasi perintah `seed_labtrack` (akun demo, kategori, lokasi, 20 aset, transaksi, jadwal) |
| `docs/08-Test-Plan-dan-QA.md` | 32 kasus uji (`TC-01` s.d. `TC-32`) untuk pengujian otomatis & manual |
| `docs/09-Execution-Prompts.md` | Playbook prompt eksekusi bertahap Sesi 1 hingga Sesi 6 |

---

## 5. Arsitektur & Konvensi Kode Wajib
1. **Struktur Modular**: Semua aplikasi Django ditempatkan di dalam folder `apps/`:
   * `apps/core/` — model dasar (`TimeStampedModel`), mixin RBAC, utilitas audit log, helper format Rupiah.
   * `apps/accounts/` — Custom User model (`AUTH_USER_MODEL = 'accounts.User'`), autentikasi, manajemen user oleh Admin.
   * `apps/inventory/` — `Category`, `Location`, `Asset`, `AssetLocationHistory`, generator & pemindai QR Code.
   * `apps/loans/` — `Loan`, `LoanItem`, layanan peminjaman Hybrid (`ONLINE` & `WALK_IN`) dan pengembalian.
   * `apps/maintenance/` — `DamageReport`, `MaintenanceSchedule`, `MaintenanceLog`.
   * `apps/reports/` — Dashboard analitik, kalkulator penyusutan Garis Lurus, ekspor CSV & PDF.
2. **Service Layer**: Logika bisnis kompleks (persetujuan pinjaman, pencatatan walk-in, pengembalian & sinkronisasi status aset, mutasi lokasi, perhitungan penyusutan) WAJIB ditempatkan di file `services.py` pada masing-masing app dan dibungkus dengan `@transaction.atomic` bila memodifikasi lebih dari satu tabel. **Dilarang menaruh logika bisnis berat langsung di `views.py` atau template.**
3. **Konvensi Penamaan**:
   * Python/Django: `snake_case` untuk variabel/fungsi/field/URL name, `PascalCase` untuk kelas/Model/Form.
   * Kode Aset: format terstruktur `LAB-<KODE_KAT>-<TAHUN>-<URUT4>` (contoh: `LAB-KOM-2025-0001`).
   * Nomor Peminjaman: `LOAN-<YYYYMMDD>-<URUT4>` (contoh: `LOAN-20261128-0001`).
   * Bahasa UI: **Bahasa Indonesia** yang profesional dan konsisten. Bahasa kode (variabel, model, method, komentar teknis): **Bahasa Inggris**.
4. **Presisi Keuangan**: Selalu gunakan `Decimal` (`DecimalField(max_digits=14, decimal_places=2)`) untuk harga perolehan, nilai residu, biaya pemeliharaan, dan kalkulasi penyusutan. **Dilarang menggunakan `float` untuk perhitungan nilai aset.**

---

## 6. Aturan Bisnis Kritis (Invarian yang Tidak Boleh Dilanggar)
1. **Mekanisme Peminjaman Hybrid (Opsi C)**:
   * Jalur `ONLINE`: Peminjam login → ajukan pinjaman (`PENDING`) → Laboran/Admin menyetujui (`APPROVED`) → saat serah terima menjadi `ACTIVE` (atau langsung `ACTIVE` jika Laboran memilih *Setujui & Serahkan*).
   * Jalur `WALK_IN`: Peminjam datang langsung ke lab tanpa perlu login → Laboran/Admin mengisi form Walk-In (bisa menautkan akun existing atau input manual Nama, NIM/NIP, No. Kontak) → transaksi langsung berstatus `ACTIVE` tanpa tahap `PENDING`.
   * **Anti Double-Booking**: Aset HANYA boleh dipinjam jika `status == AVAILABLE` dan `condition != MAJOR_DAMAGE`. Saat pinjaman berstatus `ACTIVE`, status aset wajib berubah menjadi `BORROWED` dalam satu transaksi atomik.
2. **Privasi Scan QR Publik**:
   * Halaman `/scan/<asset_code>/` dapat diakses tanpa login (*read-only*).
   * Halaman publik HANYA menampilkan identitas aset, kategori, lokasi, status ketersediaan, dan kondisi umum. **DILARANG** menampilkan nama/kontak peminjam aktif, harga beli, atau tombol modifikasi kepada pengguna yang belum login atau berstatus `BORROWER`.
3. **Larangan Hard Delete**:
   * Aset yang sudah memiliki riwayat peminjaman, kerusakan, atau pemeliharaan **tidak boleh dihapus permanen (`DELETE`)**. Gunakan fitur **Hapusbukukan (`RETIRED`)** dengan `is_active = False` agar integritas audit tetap terjaga.
4. **Data Sintetis**:
   * Seluruh data *seeder* dan pengujian wajib menggunakan data fiktif/sintetis yang dianonimkan. Tidak boleh menggunakan data pribadi asli mahasiswa/dosen.

---

## 7. Aturan Eksekusi Terminal & Workflow Agen AI
* **JANGAN menjalankan server interaktif/blocking** (`python manage.py runserver`) secara otomatis yang menggantung proses.
* Setelah selesai menulis atau mengubah kode pada suatu sesi:
  1. Pastikan tidak ada kesalahan sintaks Python atau template.
  2. Jika menjalankan pengecekan non-blocking seperti `python manage.py check`, tampilkan ringkasannya.
  3. **Berikan daftar perintah terminal yang bersih** (`makemigrations`, `migrate`, `seed_labtrack`, `test`, `runserver`) agar pengembang menjalankannya secara manual di terminal lokal.
* Kerjakan implementasi **sesuai cakupan sesi yang diminta** (lihat `docs/09-Execution-Prompts.md`). Jangan melompat atau menulis ulang modul di luar cakupan sesi kecuali diperlukan untuk memperbaiki integrasi.
