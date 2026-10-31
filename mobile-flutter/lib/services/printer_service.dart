import 'dart:convert';
import 'dart:io';
import 'package:esc_pos_utils_plus/esc_pos_utils_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:image/image.dart' as img;
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:permission_handler/permission_handler.dart';
import 'package:print_bluetooth_thermal/print_bluetooth_thermal.dart';
import 'package:printing/printing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';
import '../config/app_config.dart';
import 'storage_service.dart';

/// Model Struk Transaksi yang dikirim dari Web via PrintChannel
class StrukPayload {
  final String rawText;
  final String? storeName;
  final String? refId;
  final String? productName;
  final String? targetNumber;
  final String? amount;
  final String? sn;
  final String? time;
  final String? status;
  final String? footer;
  final String? logoBase64;
  final String? logoUrl;
  final bool hasLogo;
  Uint8List? cachedLogoBytes;

  StrukPayload({
    required this.rawText,
    this.storeName,
    this.refId,
    this.productName,
    this.targetNumber,
    this.amount,
    this.sn,
    this.time,
    this.status,
    this.footer,
    this.logoBase64,
    this.logoUrl,
    this.hasLogo = true,
    this.cachedLogoBytes,
  });

  factory StrukPayload.fromMessage(String raw) {
    try {
      final dynamic decoded = jsonDecode(raw);
      if (decoded is Map<String, dynamic>) {
        final rawTextVal = decoded['raw_text']?.toString() ?? decoded['text']?.toString();
        final cleanRawText = (rawTextVal != null && !rawTextVal.trim().startsWith('{')) ? rawTextVal : '';
        final logoB64 = decoded['logo_base64']?.toString() ?? decoded['logoBase64']?.toString() ?? decoded['logo']?.toString();
        final logoUrlVal = decoded['logo_url']?.toString() ?? decoded['logoUrl']?.toString();
        final hasLogoVal = decoded['has_logo'] != false;

        return StrukPayload(
          rawText: cleanRawText,
          storeName: decoded['storeName']?.toString() ?? decoded['store_name']?.toString(),
          refId: decoded['refId']?.toString() ?? decoded['ref_id']?.toString(),
          productName: decoded['product']?.toString() ?? decoded['product_name']?.toString(),
          targetNumber: decoded['target']?.toString() ?? decoded['target_number']?.toString(),
          amount: decoded['amount']?.toString() ?? decoded['price']?.toString(),
          sn: decoded['sn']?.toString(),
          time: decoded['time']?.toString() ?? decoded['date']?.toString(),
          status: decoded['status']?.toString() ?? 'BERHASIL',
          footer: decoded['footer']?.toString(),
          logoBase64: logoB64,
          logoUrl: logoUrlVal,
          hasLogo: hasLogoVal,
        );
      }
    } catch (_) {}

    if (raw.trim().startsWith('{')) {
      return StrukPayload(rawText: '');
    }
    return StrukPayload(rawText: raw);
  }

  factory StrukPayload.fromPlainText(String raw) {
    if (raw.trim().startsWith('{')) {
      return StrukPayload.fromMessage(raw);
    }
    return StrukPayload(rawText: raw);
  }

  /// Mengambil byte gambar logo dari Base64, URL download, atau cache lokal
  Future<Uint8List?> getLogoBytes() async {
    if (cachedLogoBytes != null && cachedLogoBytes!.isNotEmpty) {
      return cachedLogoBytes;
    }

    // 1. Ekstrak dari Base64 jika tersedia (instan & 100% offline-ready)
    if (logoBase64 != null && logoBase64!.isNotEmpty) {
      try {
        String cleanB64 = logoBase64!;
        if (cleanB64.contains(',')) {
          cleanB64 = cleanB64.split(',').last;
        }
        final bytes = base64Decode(cleanB64.trim());
        if (bytes.isNotEmpty) {
          cachedLogoBytes = bytes;
          await PrinterService.instance.cacheStoreLogo(bytes);
          return bytes;
        }
      } catch (e) {
        debugPrint('[StrukPayload] Error decode logoBase64: $e');
      }
    }

    // 2. Unduh dari URL jika ada
    if (logoUrl != null && logoUrl!.isNotEmpty) {
      try {
        final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
        final request = await client.getUrl(Uri.parse(logoUrl!));
        final response = await request.close();
        if (response.statusCode == 200) {
          final bytes = await consolidateHttpClientResponseBytes(response);
          if (bytes.isNotEmpty) {
            cachedLogoBytes = bytes;
            await PrinterService.instance.cacheStoreLogo(bytes);
            return bytes;
          }
        }
      } catch (e) {
        debugPrint('[StrukPayload] Error download logoUrl: $e');
      }
    }

    // 3. Fallback ke logo toko yang tersimpan di cache lokal
    if (hasLogo) {
      final cached = await PrinterService.instance.getCachedStoreLogo();
      if (cached != null && cached.isNotEmpty) {
        cachedLogoBytes = cached;
        return cached;
      }
    }

    return null;
  }

  String buildReceiptText({int paperWidth = 32, String? headerStore, String? footerText}) {
    if (rawText.isNotEmpty && !rawText.trim().startsWith('{')) {
      return rawText.replaceAll(RegExp(r'\x1b[a-zA-Z0-9\x00-\x20]'), '');
    }

    final width = paperWidth <= 32 ? 32 : 48;
    final divider = '-' * width;
    final buffer = StringBuffer();

    final store = (headerStore ?? storeName ?? 'IPAY').toUpperCase();
    buffer.writeln(store);
    buffer.writeln('Pusat Pembayaran PPOB Terpercaya');
    buffer.writeln(divider);

    if (refId != null && refId!.isNotEmpty) buffer.writeln('No. Ref : $refId');
    if (time != null && time!.isNotEmpty) buffer.writeln('Waktu   : $time');
    buffer.writeln('Status  : [ ${status ?? "BERHASIL"} ]');
    buffer.writeln(divider);

    if (productName != null && productName!.isNotEmpty) buffer.writeln('PRODUK  : $productName');
    if (targetNumber != null && targetNumber!.isNotEmpty) buffer.writeln('TUJUAN  : $targetNumber');
    if (sn != null && sn!.isNotEmpty) buffer.writeln('SN      : $sn');
    buffer.writeln(divider);

    if (amount != null && amount!.isNotEmpty) {
      buffer.writeln('TOTAL   : $amount');
      buffer.writeln(divider);
    }

    buffer.writeln(footerText ?? footer ?? 'Terima kasih !');
    buffer.writeln('Simpan struk ini sebagai bukti sah\n');

    return buffer.toString();
  }
}

/// Layanan Bluetooth Thermal POS Printer Singleton
/// Terinspirasi dari DrinkPOS Lite: Cepat, handal, hemat kertas, dan offline-first.
class PrinterService {
  static PrinterService? _instance;
  PaperSize _paperSize = PaperSize.mm58;

  PrinterService._() {
    loadSavedPaperSize();
  }

  static PrinterService get instance {
    _instance ??= PrinterService._();
    return _instance!;
  }

  PaperSize get paperSize => _paperSize;
  int get maxCharsPerLine => _paperSize == PaperSize.mm58 ? 32 : 48;

  // ==========================================
  // 1. MANAJEMEN KONEKSI BLUETOOTH
  // ==========================================

  /// Memeriksa dan meminta izin Bluetooth runtime untuk Android 11 maupun Android 12+ (API 31+)
  Future<bool> checkAndRequestPermissions() async {
    try {
      final scanStatus = await Permission.bluetoothScan.request();
      final connectStatus = await Permission.bluetoothConnect.request();

      if (scanStatus.isGranted && connectStatus.isGranted) {
        return true;
      }

      await Permission.bluetooth.request();
      await Permission.location.request();

      final hasPermission = await PrintBluetoothThermal.isPermissionBluetoothGranted;
      return hasPermission;
    } catch (e) {
      debugPrint('[PrinterService] Error checkAndRequestPermissions: $e');
      return false;
    }
  }

  /// Mengambil daftar printer Bluetooth yang sudah dipasangkan (paired)
  Future<List<BluetoothInfo>> getPairedDevices() async {
    try {
      await checkAndRequestPermissions();
      final List<BluetoothInfo> devices = await PrintBluetoothThermal.pairedBluetooths;
      return devices;
    } catch (e) {
      debugPrint('[PrinterService] Error getPairedDevices: $e');
      return [];
    }
  }

  /// Menghubungkan ke printer via MAC Address dengan error-handling aman
  Future<bool> connect(String macAddress) async {
    try {
      await checkAndRequestPermissions();

      final cleanMac = macAddress.trim().toUpperCase();
      if (cleanMac.isEmpty) {
        debugPrint('[PrinterService] MAC Address kosong');
        return false;
      }

      final isAlreadyConnected = await checkConnectionStatus();
      if (isAlreadyConnected) {
        final currentMac = await getSavedMac();
        if (currentMac?.toUpperCase() == cleanMac) {
          debugPrint('[PrinterService] Sudah terhubung ke $cleanMac');
          return true;
        }
        await disconnect();
      }

      final bool connected = await PrintBluetoothThermal.connect(macPrinterAddress: cleanMac);

      if (connected) {
        debugPrint('[PrinterService] Berhasil terhubung ke $cleanMac');
        await saveMac(cleanMac);
        return true;
      } else {
        debugPrint('[PrinterService] Gagal terhubung ke $cleanMac');
        return false;
      }
    } catch (e) {
      debugPrint('[PrinterService] Error connect to $macAddress: $e');
      return false;
    }
  }

  /// Memeriksa status koneksi aktif
  Future<bool> checkConnectionStatus() async {
    try {
      return await PrintBluetoothThermal.connectionStatus;
    } catch (e) {
      debugPrint('[PrinterService] Error checkConnectionStatus: $e');
      return false;
    }
  }

  /// Memutuskan koneksi printer
  Future<bool> disconnect() async {
    try {
      return await PrintBluetoothThermal.disconnect;
    } catch (e) {
      debugPrint('[PrinterService] Error disconnect: $e');
      return false;
    }
  }

  // ==========================================
  // 2. KUSTOMISASI KERTAS, LOGO & STORAGE
  // ==========================================

  Future<void> loadSavedPaperSize() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final savedWidth = prefs.getInt('printer_paper_width') ?? 58;
      _paperSize = savedWidth == 80 ? PaperSize.mm80 : PaperSize.mm58;
    } catch (_) {
      _paperSize = PaperSize.mm58;
    }
  }

  Future<void> setPaperSize(PaperSize size) async {
    _paperSize = size;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt('printer_paper_width', size == PaperSize.mm80 ? 80 : 58);
      await StorageService.instance.setPaperWidth(size == PaperSize.mm80 ? 48 : 32);
    } catch (e) {
      debugPrint('[PrinterService] Error setPaperSize: $e');
    }
  }

  Future<void> saveMac(String mac) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('printer_saved_mac', mac);
    await StorageService.instance.setSavedPrinterMac(mac);
  }

  Future<String?> getSavedMac() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('printer_saved_mac') ?? await StorageService.instance.getSavedPrinterMac();
  }

  /// Cache logo toko lokal untuk mendukung cetak offline permanen
  Future<void> cacheStoreLogo(Uint8List bytes) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('cached_store_logo_b64', base64Encode(bytes));
    } catch (e) {
      debugPrint('[PrinterService] Error cacheStoreLogo: $e');
    }
  }

  /// Mengambil logo toko dari cache lokal
  Future<Uint8List?> getCachedStoreLogo() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final b64 = prefs.getString('cached_store_logo_b64');
      if (b64 != null && b64.isNotEmpty) {
        return base64Decode(b64);
      }
    } catch (e) {
      debugPrint('[PrinterService] Error getCachedStoreLogo: $e');
    }
    return null;
  }

  /// Cek apakah fitur cetak logo di struk sedang diaktifkan pengguna
  Future<bool> isLogoPrintEnabled() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getBool('printer_print_logo_enabled') ?? true;
    } catch (_) {
      return true;
    }
  }

  /// Mengubah toggle fitur cetak logo
  Future<void> setLogoPrintEnabled(bool enabled) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool('printer_print_logo_enabled', enabled);
    } catch (e) {
      debugPrint('[PrinterService] Error setLogoPrintEnabled: $e');
    }
  }

  // ==========================================
  // 3. FORMAT STRUK ESC/POS
  // ==========================================

  /// Memformat baris 2 kolom secara rata kiri-kanan presisi menggunakan perhitungan spasi dinamis
  String formatTwoColumns(String left, String right, {int? maxChars}) {
    final int max = maxChars ?? maxCharsPerLine;
    String cleanLeft = left.trim();
    String cleanRight = right.trim();

    if (cleanLeft.length + cleanRight.length >= max) {
      final maxLeftLen = max - cleanRight.length - 1;
      if (maxLeftLen > 0 && cleanLeft.length > maxLeftLen) {
        cleanLeft = cleanLeft.substring(0, maxLeftLen);
      }
    }

    final int spacesCount = max - cleanLeft.length - cleanRight.length;
    final String spaceStr = ' ' * (spacesCount > 0 ? spacesCount : 1);
    return '$cleanLeft$spaceStr$cleanRight';
  }

  /// Garis pemisah otomatis
  String get dividerLine => '-' * maxCharsPerLine;

  /// Memproses dan merasterisasi logo toko ke format thermal hitam-putih
  /// Dilengkapi penanganan transparansi PNG ke putih agar tidak menjadi blok hitam pekat
  List<int> processLogoRaster(Uint8List logoBytes, Generator generator) {
    try {
      img.Image? decoded = img.decodeImage(logoBytes);
      if (decoded == null) return [];

      // 1. Flatten transparansi PNG ke background putih solid
      if (decoded.hasAlpha) {
        final whiteBg = img.Image(
          width: decoded.width,
          height: decoded.height,
          numChannels: 3,
        )..clear(img.ColorRgb8(255, 255, 255));
        decoded = img.compositeImage(whiteBg, decoded);
      }

      // 2. Resize proporsional: 58mm (lebar ideal 240-280px) & 80mm (lebar ideal 384px)
      final int targetWidth = _paperSize == PaperSize.mm58 ? 256 : 384;
      final img.Image resized = img.copyResize(
        decoded,
        width: targetWidth,
        interpolation: img.Interpolation.linear,
      );

      // 3. Konversi ke Grayscale monokrom
      final img.Image gray = img.grayscale(resized);

      // 4. Buat raster ESC/POS bytes (GS v 0)
      List<int> bytes = [];
      bytes += generator.imageRaster(
        gray,
        align: PosAlign.center,
        highDensityHorizontal: true,
        highDensityVertical: true,
      );
      bytes += generator.feed(1);
      return bytes;
    } catch (e) {
      debugPrint('[PrinterService] Error processLogoRaster: $e');
      return [];
    }
  }

  // ==========================================
  // 4. FUNGSI CETAK (TEST & TRANSAKSI)
  // ==========================================

  /// Cetak struk uji coba koneksi untuk memastikan printer mencetak dengan jelas (termasuk Logo)
  Future<bool> printTestReceipt({Map<String, dynamic>? storeInfo}) async {
    try {
      final isConnected = await checkConnectionStatus();
      if (!isConnected) {
        final savedMac = await getSavedMac();
        if (savedMac == null || savedMac.isEmpty) {
          debugPrint('[PrinterService] Belum ada printer tersimpan untuk test print');
          return false;
        }
        final ok = await connect(savedMac);
        if (!ok) return false;
      }

      final profile = await CapabilityProfile.load();
      final generator = Generator(_paperSize, profile);
      List<int> bytes = [];

      // Reset
      bytes += generator.reset();

      // 1. Logo Toko (Jika Ada & Aktif)
      final logoEnabled = await isLogoPrintEnabled();
      if (logoEnabled) {
        Uint8List? logoBytes = await getCachedStoreLogo();
        if (logoBytes == null || logoBytes.isEmpty) {
          try {
            final byteData = await rootBundle.load('assets/icon/app_logo.png');
            logoBytes = byteData.buffer.asUint8List();
          } catch (_) {}
        }
        if (logoBytes != null && logoBytes.isNotEmpty) {
          final logoRaster = processLogoRaster(logoBytes, generator);
          if (logoRaster.isNotEmpty) {
            bytes += logoRaster;
          }
        }
      }

      // 2. Header Toko
      final storeName = (storeInfo?['store_name'] ?? 'GARUDATEL POS').toString().toUpperCase();
      final address = (storeInfo?['address'] ?? 'Pusat Pembayaran PPOB & Kasir').toString();

      bytes += generator.text(
        storeName,
        styles: const PosStyles(
          align: PosAlign.center,
          bold: true,
          height: PosTextSize.size2,
          width: PosTextSize.size2,
        ),
      );
      bytes += generator.text(
        address,
        styles: const PosStyles(align: PosAlign.center),
      );
      bytes += generator.text(dividerLine, styles: const PosStyles(align: PosAlign.center));

      // Info Pengujian
      bytes += generator.text(
        '*** UJI COBA PRINTER POS ***',
        styles: const PosStyles(align: PosAlign.center, bold: true),
      );
      bytes += generator.text(dividerLine, styles: const PosStyles(align: PosAlign.center));

      final now = DateTime.now();
      final dateStr = '${now.day.toString().padLeft(2, '0')}/${now.month.toString().padLeft(2, '0')}/${now.year} ${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}';

      bytes += generator.text(formatTwoColumns('Waktu Uji', dateStr));
      bytes += generator.text(formatTwoColumns('Kertas', _paperSize == PaperSize.mm58 ? '58 mm' : '80 mm'));
      bytes += generator.text(formatTwoColumns('Karakter/Baris', '$maxCharsPerLine Chars'));
      bytes += generator.text(formatTwoColumns('Status', 'BERHASIL KONEK [OK]'));
      bytes += generator.text(dividerLine, styles: const PosStyles(align: PosAlign.center));

      // Contoh Item Nota Kasir
      bytes += generator.text(formatTwoColumns('1x Kopi Susu Aren', 'Rp 18.000'));
      bytes += generator.text(formatTwoColumns('1x Croissant Butter', 'Rp 22.000'));
      bytes += generator.text(dividerLine, styles: const PosStyles(align: PosAlign.center));
      bytes += generator.text(
        formatTwoColumns('TOTAL TRANSAKSI', 'Rp 40.000'),
        styles: const PosStyles(bold: true),
      );
      bytes += generator.text(formatTwoColumns('Bayar (Tunai)', 'Rp 50.000'));
      bytes += generator.text(formatTwoColumns('Kembalian', 'Rp 10.000'));
      bytes += generator.text(dividerLine, styles: const PosStyles(align: PosAlign.center));

      // Footer
      bytes += generator.text(
        'Printer Berfungsi Sangat Baik!',
        styles: const PosStyles(align: PosAlign.center, bold: true),
      );
      bytes += generator.text(
        'Siap melayani transaksi kasir harian',
        styles: const PosStyles(align: PosAlign.center),
      );

      // Hemat Kertas: feed 1 baris saja di akhir struk agar tidak boros
      bytes += generator.feed(1);
      if (_paperSize == PaperSize.mm80) {
        bytes += generator.cut();
      }

      return await PrintBluetoothThermal.writeBytes(bytes);
    } catch (e) {
      debugPrint('[PrinterService] Error printTestReceipt: $e');
      return false;
    }
  }

  /// Cetak struk transaksi kasir lengkap (Offline-first POS Receipt)
  Future<bool> printReceipt({
    String? storeName,
    String? address,
    String? phone,
    String? orderNo,
    String? date,
    String? cashierName,
    required List<Map<String, dynamic>> items,
    String? subtotal,
    String? discount,
    required String total,
    String? paymentMethod,
    String? cashReceived,
    String? change,
    String? footerMessage,
    Uint8List? logoBytes,
  }) async {
    try {
      final isConnected = await checkConnectionStatus();
      if (!isConnected) {
        final savedMac = await getSavedMac();
        if (savedMac != null && savedMac.isNotEmpty) {
          final ok = await connect(savedMac);
          if (!ok) return false;
        } else {
          return false;
        }
      }

      final profile = await CapabilityProfile.load();
      final generator = Generator(_paperSize, profile);
      List<int> bytes = [];

      bytes += generator.reset();

      // Logo Toko (opsional)
      if (logoBytes != null && logoBytes.isNotEmpty) {
        final logoRaster = processLogoRaster(logoBytes, generator);
        if (logoRaster.isNotEmpty) {
          bytes += logoRaster;
        }
      }

      // Header Toko
      final name = (storeName ?? 'GARUDATEL POS').toUpperCase();
      bytes += generator.text(
        name,
        styles: const PosStyles(
          align: PosAlign.center,
          bold: true,
          height: PosTextSize.size2,
          width: PosTextSize.size2,
        ),
      );

      if (address != null && address.isNotEmpty) {
        bytes += generator.text(address, styles: const PosStyles(align: PosAlign.center));
      }
      if (phone != null && phone.isNotEmpty) {
        bytes += generator.text('Telp: $phone', styles: const PosStyles(align: PosAlign.center));
      }
      bytes += generator.text(dividerLine, styles: const PosStyles(align: PosAlign.center));

      // Info Nota
      if (orderNo != null && orderNo.isNotEmpty) {
        bytes += generator.text(formatTwoColumns('No. Nota', orderNo));
      }
      if (date != null && date.isNotEmpty) {
        bytes += generator.text(formatTwoColumns('Tanggal', date));
      }
      if (cashierName != null && cashierName.isNotEmpty) {
        bytes += generator.text(formatTwoColumns('Kasir', cashierName));
      }
      bytes += generator.text(dividerLine, styles: const PosStyles(align: PosAlign.center));

      // Daftar Item Pesanan
      for (final item in items) {
        final itemName = item['name']?.toString() ?? 'Item';
        final itemQty = item['qty']?.toString() ?? '1';
        final itemPrice = item['price']?.toString() ?? '0';
        final variantOrNote = item['note']?.toString() ?? item['variant']?.toString();

        bytes += generator.text(formatTwoColumns('${itemQty}x $itemName', itemPrice));
        if (variantOrNote != null && variantOrNote.isNotEmpty) {
          bytes += generator.text('   ($variantOrNote)', styles: const PosStyles(fontType: PosFontType.fontB));
        }
      }
      bytes += generator.text(dividerLine, styles: const PosStyles(align: PosAlign.center));

      // Ringkasan Pembayaran
      if (subtotal != null && subtotal.isNotEmpty) {
        bytes += generator.text(formatTwoColumns('Subtotal', subtotal));
      }
      if (discount != null && discount.isNotEmpty && discount != '0') {
        bytes += generator.text(formatTwoColumns('Diskon', discount));
      }
      bytes += generator.text(
        formatTwoColumns('TOTAL', total),
        styles: const PosStyles(bold: true),
      );
      if (paymentMethod != null && paymentMethod.isNotEmpty) {
        bytes += generator.text(formatTwoColumns('Metode', paymentMethod));
      }
      if (cashReceived != null && cashReceived.isNotEmpty) {
        bytes += generator.text(formatTwoColumns('Tunai', cashReceived));
      }
      if (change != null && change.isNotEmpty) {
        bytes += generator.text(formatTwoColumns('Kembalian', change));
      }
      bytes += generator.text(dividerLine, styles: const PosStyles(align: PosAlign.center));

      // Footer
      final foot = footerMessage ?? 'Terima Kasih Atas Kunjungan Anda!';
      bytes += generator.text(foot, styles: const PosStyles(align: PosAlign.center));

      // Hemat Kertas: feed 1 baris saja di akhir struk agar tidak boros
      bytes += generator.feed(1);
      if (_paperSize == PaperSize.mm80) {
        bytes += generator.cut();
      }

      return await PrintBluetoothThermal.writeBytes(bytes);
    } catch (e) {
      debugPrint('[PrinterService] Error printReceipt: $e');
      return false;
    }
  }

  /// Cetak StrukPayload dari Web Invoice / PPOB
  Future<bool> printThermal(StrukPayload payload, {String? targetMac}) async {
    return printStrukPayload(payload, targetMac: targetMac);
  }

  Future<bool> printStrukPayload(StrukPayload payload, {String? targetMac}) async {
    try {
      final mac = targetMac ?? await getSavedMac();
      if (mac == null || mac.isEmpty) {
        debugPrint('[PrinterService] Tidak ada printer MAC tersimpan');
        return false;
      }

      final isConnected = await checkConnectionStatus();
      if (!isConnected) {
        final ok = await connect(mac);
        if (!ok) return false;
      }

      final bytes = await generateEscPosBytesAsync(payload);
      return await PrintBluetoothThermal.writeBytes(bytes);
    } catch (e) {
      debugPrint('[PrinterService] Error printStrukPayload: $e');
      return false;
    }
  }

  /// Menghasilkan ESC/POS bytes asinkron lengkap dengan raster Logo Toko
  Future<List<int>> generateEscPosBytesAsync(
    StrukPayload payload, {
    int? customWidth,
    int? customFeed,
    bool forceNoLogo = false,
  }) async {
    final profile = await CapabilityProfile.load();
    final generator = Generator(_paperSize, profile);
    final List<int> bytes = [];

    // 1. Reset ESC @
    bytes.addAll(generator.reset());

    // 2. Cetak Logo Toko (Jika Aktif & Tersedia)
    final logoEnabled = await isLogoPrintEnabled();
    if (!forceNoLogo && logoEnabled && payload.hasLogo) {
      final logoBytes = await payload.getLogoBytes();
      if (logoBytes != null && logoBytes.isNotEmpty) {
        final logoRaster = processLogoRaster(logoBytes, generator);
        if (logoRaster.isNotEmpty) {
          bytes.addAll(logoRaster);
        }
      }
    }

    // 3. Cetak Isi Teks Struk
    if (payload.rawText.contains('\x1b') || payload.rawText.contains('---')) {
      bytes.addAll(payload.rawText.codeUnits);
    } else if (payload.storeName != null || payload.refId != null || payload.productName != null) {
      final width = customWidth ?? maxCharsPerLine;
      final divider = '-' * (width <= 32 ? 32 : 48);

      void text(String s) => bytes.addAll(s.codeUnits);
      void feed(int n) => bytes.addAll(List.filled(n, 0x0A));
      void alignCenter() => bytes.addAll([0x1B, 0x61, 1]);
      void alignLeft() => bytes.addAll([0x1B, 0x61, 0]);
      void boldOn() => bytes.addAll([0x1B, 0x45, 1]);
      void boldOff() => bytes.addAll([0x1B, 0x45, 0]);

      alignCenter();
      boldOn();
      text('${(payload.storeName ?? "GARUDATEL IPAY").toUpperCase()}\n');
      boldOff();
      text('Pusat Pembayaran PPOB Terpercaya\n');
      text('$divider\n');

      alignLeft();
      if (payload.refId != null && payload.refId!.isNotEmpty) text('No. Ref : ${payload.refId}\n');
      if (payload.time != null && payload.time!.isNotEmpty) text('Waktu   : ${payload.time}\n');
      text('Status  : [ ${payload.status ?? "BERHASIL"} ]\n');
      text('$divider\n');

      if (payload.productName != null && payload.productName!.isNotEmpty) text('PRODUK  : ${payload.productName}\n');
      if (payload.targetNumber != null && payload.targetNumber!.isNotEmpty) text('TUJUAN  : ${payload.targetNumber}\n');
      if (payload.sn != null && payload.sn!.isNotEmpty) text('SN      : ${payload.sn}\n');
      text('$divider\n');

      if (payload.amount != null && payload.amount!.isNotEmpty) {
        text('TOTAL   : ${payload.amount}\n');
        text('$divider\n');
      }

      alignCenter();
      text('${payload.footer ?? "Terima kasih!"}\n');
      feed(customFeed ?? 1);
    } else {
      bytes.addAll(payload.rawText.codeUnits);
      bytes.addAll([0x0A]);
    }

    if (_paperSize == PaperSize.mm80) {
      bytes.addAll([0x1D, 0x56, 0x42, 0x00]);
    }

    return bytes;
  }

  /// Menghasilkan ESC/POS bytes sinkron (kompatibel unit tests & direct raw)
  List<int> generateEscPosBytes(StrukPayload payload, {int? customWidth, int? customFeed}) {
    final List<int> bytes = [];

    // ESC @: Inisialisasi printer
    bytes.addAll([0x1B, 0x40]);

    if (payload.rawText.contains('\x1b') || payload.rawText.contains('---')) {
      bytes.addAll(payload.rawText.codeUnits);
    } else if (payload.storeName != null || payload.refId != null || payload.productName != null) {
      final width = customWidth ?? maxCharsPerLine;
      final divider = '-' * (width <= 32 ? 32 : 48);

      void text(String s) => bytes.addAll(s.codeUnits);
      void feed(int n) => bytes.addAll(List.filled(n, 0x0A));
      void alignCenter() => bytes.addAll([0x1B, 0x61, 1]);
      void alignLeft() => bytes.addAll([0x1B, 0x61, 0]);
      void boldOn() => bytes.addAll([0x1B, 0x45, 1]);
      void boldOff() => bytes.addAll([0x1B, 0x45, 0]);

      alignCenter();
      boldOn();
      text('${(payload.storeName ?? "GARUDATEL IPAY").toUpperCase()}\n');
      boldOff();
      text('Pusat Pembayaran PPOB Terpercaya\n');
      text('$divider\n');

      alignLeft();
      if (payload.refId != null && payload.refId!.isNotEmpty) text('No. Ref : ${payload.refId}\n');
      if (payload.time != null && payload.time!.isNotEmpty) text('Waktu   : ${payload.time}\n');
      text('Status  : [ ${payload.status ?? "BERHASIL"} ]\n');
      text('$divider\n');

      if (payload.productName != null && payload.productName!.isNotEmpty) text('PRODUK  : ${payload.productName}\n');
      if (payload.targetNumber != null && payload.targetNumber!.isNotEmpty) text('TUJUAN  : ${payload.targetNumber}\n');
      if (payload.sn != null && payload.sn!.isNotEmpty) text('SN      : ${payload.sn}\n');
      text('$divider\n');

      if (payload.amount != null && payload.amount!.isNotEmpty) {
        text('TOTAL   : ${payload.amount}\n');
        text('$divider\n');
      }

      alignCenter();
      text('${payload.footer ?? "Terima kasih!"}\n');
      feed(customFeed ?? 1);
    } else {
      bytes.addAll(payload.rawText.codeUnits);
      bytes.addAll([0x0A]);
    }

    if (_paperSize == PaperSize.mm80) {
      bytes.addAll([0x1D, 0x56, 0x42, 0x00]);
    }

    return bytes;
  }

  // ==========================================
  // 5. FALLBACK & MODAL INTERAKSI PENGGUNA
  // ==========================================

  /// Cetak via Printer Laser / PDF bawaan Android
  Future<void> printLaserOrPdf(BuildContext context, StrukPayload payload) async {
    try {
      final doc = pw.Document();
      final receiptContent = payload.buildReceiptText(paperWidth: 48);

      doc.addPage(
        pw.Page(
          pageFormat: PdfPageFormat.roll80,
          margin: const pw.EdgeInsets.all(12),
          build: (pw.Context ctx) {
            return pw.Center(
              child: pw.Text(
                receiptContent,
                style: const pw.TextStyle(
                  fontSize: 9,
                  lineSpacing: 1.2,
                ),
              ),
            );
          },
        ),
      );

      await Printing.layoutPdf(
        onLayout: (PdfPageFormat format) async => doc.save(),
        name: 'Struk_${payload.refId ?? "Transaksi"}.pdf',
      );
    } catch (e) {
      debugPrint('[PrinterService] Error printLaserOrPdf: $e');
    }
  }

  /// Cetak via aplikasi pihak ketiga RawBT POS Printer
  Future<bool> printViaRawBt(StrukPayload payload) async {
    try {
      final text = payload.rawText.isNotEmpty ? payload.rawText : payload.buildReceiptText();
      final base64String = base64Encode(utf8.encode(text));
      final rawBtUri = Uri.parse('rawbt:data:text/plain;base64,$base64String');

      if (await canLaunchUrl(rawBtUri)) {
        await launchUrl(rawBtUri, mode: LaunchMode.externalApplication);
        return true;
      }
      return false;
    } catch (e) {
      debugPrint('[PrinterService] Error printViaRawBt: $e');
      return false;
    }
  }

  /// Menampilkan modal pemilih printer jika belum ada printer tersimpan
  void showPrintSelectionModal(BuildContext context, StrukPayload payload) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Pilih Metode Cetak Struk',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 12),
                ListTile(
                  leading: const Icon(Icons.bluetooth_audio, color: AppConfig.primaryTeal),
                  title: const Text('Printer Bluetooth Thermal (POS)'),
                  subtitle: const Text('Cetak langsung ke printer kasir 58mm/80mm'),
                  onTap: () {
                    Navigator.pop(ctx);
                    printStrukPayload(payload);
                  },
                ),
                ListTile(
                  leading: const Icon(Icons.picture_as_pdf, color: Colors.blueAccent),
                  title: const Text('Sistem Cetak Android / PDF'),
                  subtitle: const Text('Gunakan printer WiFi, Laser, atau Simpan PDF'),
                  onTap: () {
                    Navigator.pop(ctx);
                    printLaserOrPdf(context, payload);
                  },
                ),
                ListTile(
                  leading: const Icon(Icons.print, color: Colors.deepPurple),
                  title: const Text('Cetak via RawBT App'),
                  subtitle: const Text('Kirim data langsung ke aplikasi RawBT'),
                  onTap: () {
                    Navigator.pop(ctx);
                    printViaRawBt(payload);
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
