# GarudaTel iPay - Native Mobile Flutter (Hybrid Bridge)

Aplikasi Native Android untuk **GarudaTel PPOB (https://ipay.my.id)** berbasis Flutter WebView dengan jembatan perangkat keras (Hardware Native Bridge).

Aplikasi ini dibuat secara terisolasi di dalam sub-folder `/mobile-flutter` tanpa mengubah atau mengganggu file web aplikasi produksi `ipay.my.id`.

---

## 🚀 Fitur Utama & Jembatan Native (Bridge)

### 1. WebView Layar Penuh (PPOB Fullscreen)
- Memuat `https://ipay.my.id` secara penuh tanpa App Bar.
- **Manajemen Sesi & Cookie Flask:**
  - Mengaktifkan DOM Storage (`localStorage` & `sessionStorage`).
  - Mengelola cookie sesi `session` dan `gt_device_token` agar login kasir/agen tidak mudah ter-logout.
  - Interseptor tombol *Back* fisik HP (`PopScope`): jika kasir menekan tombol kembali di HP, halaman web akan mundur ke riwayat sebelumnya (`controller.goBack()`), bukan langsung keluar aplikasi.

---

### 2. Jembatan Cetak Struk (`PrintChannel`)
Ketika halaman web (misal `invoice.html` atau `pos.html`) memanggil:
```javascript
if (window.PrintChannel) {
    PrintChannel.postMessage(JSON.stringify({
        storeName: "KONTER GARUDA",
        refId: "TRX-100234",
        product: "Pulsa Telkomsel 10K",
        target: "08123456789",
        amount: "Rp 12.000",
        sn: "1234567890",
        time: "23-10-2026 17:30",
        status: "BERHASIL",
        footer: "Terima kasih atas kunjungan Anda"
    }));
} else {
    window.print(); // Fallback untuk browser laptop/PC
}
```
Aplikasi Flutter akan:
1. Menangkap data struk tersebut secara instan.
2. Membuka **Modal Dialog Kasir** di layar HP yang menampilkan daftar printer bluetooth yang terpasang (*paired devices*).
3. **Cetak Thermal Bluetooth:** Mengirim byte ESC/POS langsung ke printer thermal mini 58mm / 80mm kasir tanpa perlu aplikasi pihak ketiga seperti RawBT.
4. **Cetak Laser / PDF:** Menyediakan tombol *"Cetak via Printer Laser / PDF"* yang memanfaatkan sistem cetak bawaan Android (`Printing.layoutPdf`) untuk mencetak ke printer WiFi/LAN atau menyimpan sebagai file PDF.

---

### 3. Jembatan Penyimpanan Permanen (`StorageChannel`)
Frontend web dapat menyimpan preferensi kasir, MAC address printer langganan, atau backup data Muslim Daily Tracker langsung ke memori internal native HP Android (`SharedPreferences`), bebas dari risiko terhapus saat pembersihan cache browser:

```javascript
// 1. Menyimpan Data
StorageChannel.postMessage(JSON.stringify({
    action: "set",
    key: "favorite_printer_mac",
    value: "00:11:22:33:44:55"
}));

// 2. Mengambil Data (dengan fungsi callback JS)
function onGetPrinterResult(value, key) {
    console.log("Printer tersimpan:", value);
}

StorageChannel.postMessage(JSON.stringify({
    action: "get",
    key: "favorite_printer_mac",
    callback: "onGetPrinterResult"
}));

// 3. Menghapus Data
StorageChannel.postMessage(JSON.stringify({
    action: "remove",
    key: "favorite_printer_mac"
}));
```

---

### 4. Push Notification (FCM) & Sinkronisasi Token
- Modul `FcmService` membaca token perangkat `FCM_TOKEN`.
- Begitu halaman web selesai dimuat (`onPageFinished`), token secara otomatis disuntikkan ke JavaScript web:
  - Tersedia di variabel global: `window.GARUDATEL_FCM_TOKEN`
  - Memicu fungsi: `window.onReceiveFcmToken(token)`
  - Memicu event DOM: `window.dispatchEvent(new CustomEvent('fcm_token_ready', { detail: { token: token } }))`
- **Konfigurasi Firebase:**
  Cukup unduh file `google-services.json` dari Firebase Console Anda (package name: `com.garudatel.ipay.mobile_flutter`), lalu letakkan di:
  `mobile-flutter/android/app/google-services.json`.

---

### 5. Ikon Aplikasi & Izin Lengkap Android
- **Ikon Aplikasi:** Dibuat otomatis dari file master logo `app/static/img/icons/icon-512x512.png` ke seluruh varian mipmap Android (`xxxhdpi`, `xxhdpi`, `xhdpi`, `hdpi`, `mdpi`) via `flutter_launcher_icons`.
- **Izin `AndroidManifest.xml`:**
  - `INTERNET` & `ACCESS_NETWORK_STATE`
  - `BLUETOOTH` & `BLUETOOTH_ADMIN` (Legacy Android)
  - `BLUETOOTH_SCAN` & `BLUETOOTH_CONNECT` (Android 12+) dengan atribut `neverForLocation` agar tidak memaksa menyalakan GPS.
  - `POST_NOTIFICATIONS` (Android 13+).

---

## 🛠️ Cara Menjalankan & Menguji

Masuk ke folder `mobile-flutter`:
```powershell
cd c:\garudatelv2\garudatel\mobile-flutter
```

### 1. Menjalankan Pengujian Otomatis (Unit Tests)
```powershell
C:\src\flutter\bin\flutter.bat test
```
*Hasil: 7 of 7 unit tests PASSED (100%).*

### 2. Menjalankan Analisis Statis Kode
```powershell
C:\src\flutter\bin\flutter.bat analyze --no-fatal-infos
```
*Hasil: No issues found! 0 errors, 0 warnings.*

### 3. Menjalankan di HP Android Kasir via USB
Hubungkan HP Android kasir dengan kabel USB (aktifkan USB Debugging), lalu jalankan:
```powershell
C:\src\flutter\bin\flutter.bat run
```

### 4. Mengkompilasi APK Release
Buka folder `mobile-flutter/android` di Android Studio, atau jalankan:
```powershell
C:\src\flutter\bin\flutter.bat build apk --release
```
File APK siap instal akan berada di `build/app/outputs/flutter-apk/app-release.apk`.
