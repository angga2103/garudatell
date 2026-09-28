# GARUDATEL MOBILE NATIVE (FLUTTER) - MASTER BLUEPRINT & INITIATION PACKAGE

Dokumen ini adalah paket lengkap cetak biru (*blueprint*), panduan arsitektur, aturan bisnis (*rules.md*), dan **Master Prompt** siap pakai untuk membangun aplikasi mobile native **GarudaTel PPOB** menggunakan Flutter dari nol pada project terpisah di masa mendatang.

---

# BAGIAN 1: MASTER PROMPT (COPY & PASTE KE PROJECT BARU)

> **PETUNJUK PENGGUNAAN:**
> Buat folder project baru (misal: `garudatel_mobile`), inisialisasi Flutter (`flutter create .`), lalu salin teks prompt di bawah ini ke dalam sesi Antigravity pertama Anda.

```markdown
Halo! Kita akan membangun aplikasi mobile native resmi **GarudaTel** (Platform PPOB & Top Up Terpercaya) berbasis **Flutter** untuk Android & iOS.

Aplikasi ini akan berkomunikasi dengan backend server Python Flask + MySQL/SQLite yang sudah berjalan di VPS kami (`https://api.garudatel.com` atau URL produksi kami). 

Saya ingin kamu bertindak sebagai **Lead Mobile Architect & Senior Flutter Developer** yang memahami secara mendalam selera, filosofi desain, dan alur bisnis GarudaTel yang telah kami bangun sebelumnya.

Sebelum mulai menulis kode produksi, baca dan pelajari dokumen cetak biru yang disertakan di bawah ini:
1. **`rules.md`**: Aturan baku desain, keamanan single-session, validasi input, dan defensive coding.
2. **`arsitektur.md`**: Struktur folder Feature-First (Clean Architecture), State Management (Riverpod / Bloc), Dio HTTP Client, dan Local Storage (Hive).
3. **`api_spec.md`**: Kontrak API REST dengan server Flask (Auth, Transaksi, Produk, Saldo, Mutasi).
4. **`taste_and_ux_guidelines.md`**: Selera tampilan GarudaTel (Teal Palette, 5 Pilar Transaksi, Initial Guide State, Cetak Struk Bluetooth Thermal).

### TUGAS UTAMA FASE 1:
1. Setup arsitektur dasar project, `pubspec.yaml` (dependencies wajib), struktur direktori, theme & color palette GarudaTel, dan Dio Client dengan interceptor token sesi.
2. Implementasikan sistem keamanan **1 Akun 1 HP (Single Active Session)** dengan deteksi Hardware Device ID (`device_info_plus`) dan alur **Adaptive Emergency Switch**.
3. Bangun halaman **Dashboard / Home** kasir yang mewah, modern, dan seringan kilat dengan floating button Moeslim Daily Tracker.
4. Bangun modul transaksi berstandar **5 Pilar GarudaTel** untuk Pulsa Reguler & Paket Data dengan deteksi operator otomatis via prefix nomor HP.
5. Bangun modul **Cetak Struk Kasir Bluetooth Thermal (58mm/80mm)** dengan fitur ubah harga jual (markup margin kasir).

Bekerjalah secara bertahap, terstruktur, dan konfirmasikan rencana implementasi sebelum mengeksekusi fitur besar. Mari kita mulai!
```

---

# BAGIAN 2: `rules.md` (ATURAN BAKU SISTEM & STANDAR CODING)

File ini mendefinisikan aturan keras yang **WAJIB** dipatuhi oleh developer / AI agent:

```markdown
# RULES.MD - STANDAR ATURAN SISTEM GARUDATEL NATIVE FLUTTER

## 1. ATURAN KEAMANAN & SESI (SINGLE ACTIVE SESSION)
- **1 Akun 1 Perangkat:** Setiap akun hanya boleh aktif pada 1 perangkat fisik dalam satu waktu.
- **Hardware Device UUID:** Wajib membaca `AndroidId` / Hardware Identifier asli via `device_info_plus`, bukan sekadar random UUID yang bisa hilang saat clear cache.
- **Pencegatan Pre-OTP (Conflict Interception):** Jika akun sedang aktif di HP-A, HP-B yang mencoba login WAJIB dicegat SEBELUM OTP dikirim. Berikan peringatan: *"Akun sedang login di HP [Nama Perangkat]. Ingin pindah perangkat darurat?"*.
- **Pindah Perangkat Mandiri (Emergency Switch):** 
  - Jika akun memiliki PIN transaksi: Verifikasi OTP WhatsApp + PIN Transaksi.
  - Jika akun belum pasang PIN: Verifikasi OTP WhatsApp + Konfirmasi Password Akun.
  - Setelah sukses, sesi di HP lama otomatis gugur (*invalidated*).
- **Inactivity Timeout (23 Jam):** Sesi lokal otomatis meminta login ulang jika tidak ada aktivitas transaksi/eksplorasi selama 23 jam berturut-turut.

## 2. ATURAN TRANSAKSI (5 PILAR GARUDATEL)
- **Pilar 1 - Deteksi Otomatis Prefix:** Begitu kasir mengetik 4 digit pertama (0812, 0857, 0896, 0817, dll.), sistem harus otomatis mendeteksi provider dan mengaktifkan tab provider tersebut tanpa perlu ditekan manual.
- **Pilar 2 - Initial Guide State (Anti-DOM Flooding):** Layar produk TIDAK BOLEH langsung menampilkan ratusan kartu produk saat baru dibuka. Tampilkan ilustrasi panduan bersih (*Guide State*) hingga nomor HP diisi atau tab provider dipilih.
- **Pilar 3 - Filter & Search Cepat:** Menyediakan pencarian nominal cepat (contoh: "10" atau "5.000"), pengurutan harga terendah/tertinggi, dan toggle mode tampilan (Daftar List vs Grid Kartu).
- **Pilar 4 - Virtualized Scrolling / Lazy Rendering:** Wajib menggunakan `ListView.builder` / `SliverList` dengan `itemExtent` atau cache extend yang efisien agar HP RAM 2GB dapat melakukan scroll 60 FPS tanpa jeda (*zero stuttering*).
- **Pilar 5 - Status Layanan & Cut-Off Guard:**
  - Produk status gangguan: Card diberi styling khusus dan tombol dinonaktifkan / diberi label GANGGUAN.
  - PLN Cut-Off Guard: Antara jam 23:30 - 01:00 WIB, wajib menampilkan banner peringatan cut-off maintenance harian PLN.

## 3. ATURAN HARDWARE & KASIR (BLUETOOTH PRINTER)
- Mendukung koneksi langsung Bluetooth SPP ke Printer Thermal kasir ukuran 58mm dan 80mm.
- Struk wajib memiliki opsi:
  - **Ubah Harga Jual:** Kasir dapat menaikkan harga dari harga modal ke harga jual pelanggan untuk menghitung laba konter.
  - **Header & Footer Kustom:** Nama Toko, Slogan, Alamat, Pesan Penutup, dan SN (Serial Number) resmi dari provider.
  - **Share Struk:** Bisa dibagikan sebagai Gambar (PNG/JPEG) ke WhatsApp pelanggan.

## 4. DEFENSIVE PROGRAMMING & ERROR HANDLING
- Tidak boleh ada *crash / Red Screen of Death* pada Flutter. Gunakan `try-catch` dan error widget yang ramah pengguna.
- Tangani kondisi *No Internet* dengan elegan: jangan biarkan layar kosong, tampilkan banner *"Menghubungkan ke server..."* dan pertahankan data lokal terakhir dari Hive.
- Format uang rupiah wajib konsisten: `Rp 10.000` (menggunakan titik pemisah ribuan).
```

---

# BAGIAN 3: `arsitektur.md` (STRUKTUR TEKNIKAL & ARSITEKTUR CODEBASE)

```markdown
# ARSITEKTUR.MD - STRUKTUR PROYEK FLUTTER GARUDATEL

Aplikasi menggunakan pendekatan **Feature-First Clean Architecture** yang modular, mudah diuji, dan skalabel.

```
lib/
├── core/
│   ├── constants/
│   │   ├── api_endpoints.dart
│   │   ├── app_colors.dart
│   │   └── app_assets.dart
│   ├── network/
│   │   ├── dio_client.dart
│   │   ├── api_interceptors.dart
│   │   └── network_exceptions.dart
│   ├── storage/
│   │   ├── local_storage_service.dart  (Hive / SecureStorage)
│   │   └── session_manager.dart
│   ├── theme/
│   │   ├── app_theme.dart
│   │   └── text_styles.dart
│   └── utils/
│       ├── currency_formatter.dart
│       ├── phone_number_helper.dart (Prefix detector)
│       └── date_helper.dart (WIB conversion)
│
├── features/
│   ├── auth/
│   │   ├── data/
│   │   ├── domain/
│   │   └── presentation/ (LoginScreen, OtpScreen, EmergencySwitchScreen)
│   │
│   ├── dashboard/
│   │   ├── data/
│   │   ├── domain/
│   │   └── presentation/ (HomeScreen, Widgets: BalanceCard, CategoryMenu, TrackerFab)
│   │
│   ├── transaction/
│   │   ├── data/
│   │   ├── domain/
│   │   └── presentation/
│   │       ├── screens/ (PulsaScreen, DataScreen, PlnScreen, CheckoutDialog)
│   │       └── widgets/ (ProductCard, GuideStateView, OperatorTabs)
│   │
│   ├── history/
│   │   ├── data/
│   │   └── presentation/ (HistoryScreen, TransactionDetailScreen)
│   │
│   ├── printer/
│   │   ├── services/ (BluetoothThermalService, EscPosBuilder)
│   │   └── presentation/ (PrinterSettingsScreen, ReceiptPreviewDialog)
│   │
│   ├── deposit/
│   │   ├── data/
│   │   └── presentation/ (DepositScreen, ManualTransferScreen)
│   │
│   └── profile/
│       ├── data/
│       └── presentation/ (ProfileScreen, SecurityPinScreen, DownlineScreen)
│
└── main.dart
```

### PILIHAN STACK & DEPENDENCIES WAJIB:
- **State Management:** `flutter_riverpod` (v2+) atau `flutter_bloc`
- **Network & API:** `dio` + `pretty_dio_logger`
- **Local Storage:** `hive_flutter` (Cepat untuk caching katalog offline) + `flutter_secure_storage` (Untuk token sesi)
- **Hardware Integration:**
  - Device Info: `device_info_plus`
  - Bluetooth Printer: `print_bluetooth_thermal` / `blue_thermal_printer`
  - Contacts Picker: `flutter_contacts`
  - Screenshot/Share Struk: `screenshot` + `share_plus`
- **UI & UX Enhancements:**
  - Fonts: `google_fonts` (Nunito)
  - Icons: `font_awesome_flutter`
  - Shimmer Loading: `shimmer`
  - Toast/Alerts: `cherry_toast` atau custom bottom snackbar
```

---

# BAGIAN 4: `api_spec.md` (KONTRAK REST API FLASK BACKEND)

Spesifikasi endpoint Flask yang digunakan oleh aplikasi Flutter:

```markdown
# API_SPEC.MD - KONTRAK REST API FLASK GARUDATEL

Base URL: `https://api.garudatel.com`
Header Wajib:
- `Content-Type: application/json`
- `X-Device-UUID: [Hardware Android ID]`
- `Authorization: Bearer [Session Token]` (jika sudah login)

### 1. AUTENTIKASI & KEAMANAN SESI
- `POST /api/v1/auth/pre-login`
  - Request: `{ "phone": "08123456789", "device_uuid": "...", "device_name": "Redmi Note 10" }`
  - Response:
    - Status 200 (Bebas Login): `{ "status": "ok", "requires_otp": true }`
    - Status 409 (Conflict): `{ "status": "device_conflict", "active_device_name": "Samsung A52", "has_pin": true }`
- `POST /api/v1/auth/verify-otp`
  - Request: `{ "phone": "...", "otp_code": "123456", "device_uuid": "..." }`
  - Response: `{ "status": "success", "session_token": "...", "user": { ... } }`
- `POST /api/v1/auth/emergency-switch`
  - Request: `{ "phone": "...", "otp_code": "...", "security_key": "123456", "auth_type": "pin|password", "device_uuid": "..." }`
  - Response: `{ "status": "success", "session_token": "..." }`

### 2. PRODUK & KATALOG
- `GET /api/v1/products?category=pulsa`
  - Headers: User session token (untuk auto-calculate diskon tier VIP/Reseller)
  - Response:
    ```json
    {
      "status": "success",
      "data": [
        {
          "sku_code": "TSEL10",
          "name": "Telkomsel 10.000",
          "provider": "TELKOMSEL",
          "price": 10200,
          "normal_price": 10400,
          "is_discounted": true,
          "is_active": true,
          "description": "Menambah masa aktif 15 hari"
        }
      ]
    }
    ```

### 3. TRANSAKSI
- `POST /api/v1/transaction/checkout`
  - Request: `{ "sku_code": "TSEL10", "target_number": "081234567890", "pin": "123456" }`
  - Response: `{ "status": "success", "trx_id": "GT20260928001", "status_trx": "PROCESSING|SUCCESS", "sn": "12345..." }`

### 4. SALDO & PROFIL
- `GET /api/v1/user/profile` -> Mengembalikan saldo, tier (Member/Reseller/VIP), poin, dan info toko.
- `GET /api/v1/user/history` -> Riwayat transaksi dengan paginasi.
```

---

# BAGIAN 5: `taste_and_ux_guidelines.md` (SELERA TAMPILAN & PENGALAMAN KASIR)

```markdown
# TASTE_AND_UX_GUIDELINES.MD - IDENTITAS VISUAL & "RASA KASIR" GARUDATEL

Aplikasi ini dibangun untuk **kasir konter pulsa nyata di Indonesia**, bukan sekadar aplikasi showcase. Kasir butuh aplikasi yang **cepat, jelas, informatif, dan tidak membingungkan**.

### 1. PALET WARNA RESMI GARUDATEL
- **Primary Teal:** `#008779` (Hijau Tosika Segar Khas GarudaTel)
- **Primary Dark:** `#006b5f` (Untuk header melengkung & kontras)
- **Background Light:** `#F5F8FA` (Abu-abu kebiruan sangat lembut, ramah di mata)
- **Surface / Card:** `#FFFFFF` (Putih bersih dengan radius melengkung 16px - 22px)
- **Accent / Points:** `#F59E0B` (Kuning keemasan elegan)
- **Danger / Gangguan:** `#EF4444` (Merah tegas untuk status pemeliharaan)

### 2. HEADER MELENGKUNG & KARTU MELAYANG (SIGNATURE GARUDATEL)
- Bagian atas layar (Top Bar) menggunakan gradien teal gelap dengan sudut melengkung di bawah (*border-bottom-radius: 30px*).
- Menampilkan sapaan kasir, tanggal, dan saldo yang melayang (*floating balance card*) dengan tombol cepat **Top Up Saldo** dan **Transfer Saldo**.
- Di bagian navbar bawah, sematkan **Floating Action Button (FAB) Moeslim Daily Tracker** di tengah dengan lingkaran timbul yang khas.

### 3. PRINTER STRUK: ELEMEN WAJIB KASIR
- Form cetak struk harus memiliki kolom input cepat: **"Harga Jual ke Pelanggan"**.
  - Misal harga beli modal: `Rp 10.200`
  - Kasir cukup ketik `12000`
  - Di kertas struk yang dicetak, hanya tertulis `Rp 12.000` (harga modal tidak pernah bocor ke pelanggan).
- Cetak struk harus otomatis merapikan titik-titik pemisah (monospace font ESC/POS), nama pelanggan, tanggal transaksi, nomor SN resmi, dan ucapan penutup: *"Terima kasih atas kunjungan Anda"*.

### 4. PENGALAMAN INPUT NOMOR HP (ERGONOMI JARI)
- Tombol tempel nomor (*Paste*) dan tombol pilih kontak telepon (*Phonebook*) diletakkan tepat di samping kanan kotak input no HP agar mudah dijangkau satu jempol kasir.
```
