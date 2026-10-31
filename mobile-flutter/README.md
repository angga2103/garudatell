# GarudaTel iPay - Native Mobile Hybrid (Flutter POS)

[![Build & Release Android APK](https://github.com/angga2103/ipayHybirdapk/actions/workflows/build_apk.yml/badge.svg)](https://github.com/angga2103/ipayHybirdapk/actions/workflows/build_apk.yml)
[![GitHub Release](https://img.shields.io/github/v/release/angga2103/ipayHybirdapk?color=teal&label=Download%20APK)](https://github.com/angga2103/ipayHybirdapk/releases/latest)

Aplikasi Android Native Hybrid resmi untuk **GarudaTel PPOB (https://ipay.my.id)** dengan jembatan hardware printer thermal Bluetooth ala *DrinkPOS Lite*.

Setiap pembaruan kode yang di-push ke repositori ini akan **secara otomatis diuji dan dibuild oleh GitHub Actions**, dan file APK rilisnya dapat langsung diunduh dari halaman **[GitHub Releases](https://github.com/angga2103/ipayHybirdapk/releases)**.

---

## 📥 Download APK Terbaru

Anda dapat langsung mengunduh APK terbaru melalui tautan berikut:
- 🚀 **[Halaman Rilis GitHub (Daftar Semua Versi)](https://github.com/angga2103/ipayHybirdapk/releases)**
- 📲 **[Download Langsung IPAY-release.apk (Versi Terbaru)](https://github.com/angga2103/ipayHybirdapk/releases/latest/download/IPAY-release.apk)**

---

## 🚀 Fitur Utama & Jembatan Native

### 1. Bluetooth Thermal POS Printer (DrinkPOS Lite System)
- **Dukungan Multi-Brand Printer**: Mendukung berbagai printer thermal kasir (RPP02N, Goojprt, Panda, Iware, VSC, MiniPOS, Zjiang, dsb) secara *offline-first*.
- **Pilihan Ukuran Kertas**:
  - `58 mm` (Struk Kecil / Standar Kasir - 32 Karakter per baris).
  - `80 mm` (Struk Lebar / Restoran - 48 Karakter per baris).
- **Format Struk Presisi (`_formatTwoColumns`)**: Perataan dua kolom rata kiri-kanan dinamis dan rapi.
- **Cetak Hemat Kertas**: Feed 1 baris di akhir struk untuk menghemat konsumsi kertas thermal kasir.
- **Logo Toko Grayscale (`imageRaster`)**: Mendukung cetak logo toko hitam-putih presisi.
- **Koneksi Manual MAC Address**: Memungkinkan koneksi langsung ke printer yang menyembunyikan broadcast namanya (misal `66:02:BD:06:18:7B`).

### 2. Layar Pengaturan Printer Kasir Mandiri
- Status Card interaktif: Kotak hijau saat terhubung dengan tombol "Putuskan", kotak ramah saat belum terhubung.
- Tombol **Test Print** instan untuk pengujian cetak nota thermal.
- Tombol **Pindai Ulang Bluetooth** dengan animasi loading.
- Tombol pintas **[Kasir Web]** di pojok kanan atas untuk beralih kembali ke transaksi kasir PPOB.
- Bebas diakses kasir tanpa perlu memasukkan PIN Owner.

### 3. PPOB Fullscreen & WebView Bridge
- Memuat `https://ipay.my.id` secara penuh tanpa address bar browser.
- Sesi login aman dengan `WebViewCookieManager` dan DOM storage persisten.
- Interseptor tombol *Back* fisik HP (`PopScope`).
- Mendukung cetak struk via JavaScript Bridge `PrintChannel` dan penyimpanan native `StorageChannel`.

---

## 🛠️ Build & Development Lokal

Jika ingin membuild secara manual di komputer/laptop:

```bash
# 1. Ambil dependensi
flutter pub get

# 2. Jalankan unit test
flutter test

# 3. Build APK Rilis Universal
flutter build apk --release
```

Hasil build APK akan berada di:
`build/app/outputs/flutter-apk/app-release.apk`
