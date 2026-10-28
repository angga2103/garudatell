import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:print_bluetooth_thermal/print_bluetooth_thermal.dart';
import 'package:printing/printing.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:url_launcher/url_launcher.dart';
import '../config/app_config.dart';
import '../screens/printer_settings_screen.dart';
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
  });

  factory StrukPayload.fromMessage(String raw) {
    try {
      final dynamic decoded = jsonDecode(raw);
      if (decoded is Map<String, dynamic>) {
        final rawTextVal = decoded['raw_text']?.toString() ?? decoded['text']?.toString();
        final cleanRawText = (rawTextVal != null && !rawTextVal.trim().startsWith('{')) ? rawTextVal : '';
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
        );
      }
    } catch (_) {
      // Jika dikirim plain text / ESC-POS string langsung
    }

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

  /// Menghasilkan teks struk terformat rapi untuk RawBT atau printer thermal tanpa karakter acak
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
    buffer.writeln('Simpan struk ini sebagai bukti sah\n\n\n');

    return buffer.toString();
  }
}

/// Layanan Jembatan Printer Thermal Bluetooth & Laser / PDF
class PrintService {
  static PrintService? _instance;
  PrintService._();

  static PrintService get instance {
    _instance ??= PrintService._();
    return _instance!;
  }

  /// Memeriksa izin Bluetooth (Android 12+ butuh Scan/Connect, Android 11 ke bawah butuh Location)
  Future<bool> checkAndRequestPermissions() async {
    try {
      // 1. Android 12+ (API 31+) membutuhkan Bluetooth Scan & Connect
      final scanStatus = await Permission.bluetoothScan.request();
      final connectStatus = await Permission.bluetoothConnect.request();

      // 2. Android 11 ke bawah (API <= 30) membutuhkan Location
      // Di Android 12+, permission ini dibatasi oleh maxSdkVersion="30" sehingga tidak wajib
      if (!await Permission.location.isRestricted && !await Permission.location.isPermanentlyDenied) {
        try {
          await Permission.locationWhenInUse.request();
        } catch (_) {}
      }

      return (scanStatus.isGranted || scanStatus.isLimited) &&
          (connectStatus.isGranted || connectStatus.isLimited);
    } catch (e) {
      debugPrint('[PrintService] checkAndRequestPermissions error: $e');
      return true;
    }
  }

  /// Mengambil daftar printer bluetooth yang sudah dipasangkan (paired)
  Future<List<BluetoothInfo>> getPairedPrinters() async {
    try {
      final bool isEnabled = await PrintBluetoothThermal.bluetoothEnabled;
      if (!isEnabled) {
        return [];
      }
      return await PrintBluetoothThermal.pairedBluetooths;
    } catch (e) {
      debugPrint('[PrintService] getPairedPrinters error: $e');
      return [];
    }
  }

  /// Memutuskan koneksi printer bluetooth
  Future<void> disconnect() async {
    try {
      await PrintBluetoothThermal.disconnect;
    } catch (_) {}
  }

  /// Menghubungkan ke printer bluetooth berdasarkan MAC Address dengan auto-retry & handshake delay
  Future<bool> connectPrinter(String macAddress) async {
    try {
      // 1. Putuskan socket lama yang mungkin masih tersisa di Bluetooth stack
      await disconnect();
      await Future.delayed(const Duration(milliseconds: 400));

      // 2. Hubungkan ke printer
      final bool connected = await PrintBluetoothThermal.connect(
        macPrinterAddress: macAddress,
      );

      // 3. Jeda inisialisasi agar buffer printer siap menerima data ESC/POS
      if (connected) {
        await Future.delayed(const Duration(milliseconds: 500));
        await StorageService.instance.setSavedPrinterMac(macAddress);
      }
      return connected;
    } catch (e) {
      debugPrint('[PrintService] Connection error: $e');
      return false;
    }
  }

  /// Mengonversi data struk transaksi ke byte ESC/POS Uint8List siap cetak
  Uint8List generateEscPosBytes(StrukPayload payload, {int? customWidth, int? customFeed}) {
    final List<int> bytes = [];

    // Reset printer ESC @
    bytes.addAll([0x1B, 0x40]);

    if (payload.rawText.isNotEmpty &&
        !payload.rawText.trim().startsWith('{') &&
        (payload.rawText.contains('\x1b') || payload.rawText.contains('---'))) {
      // Data sudah diformat ESC/POS di Web (seperti di invoice.html)
      bytes.addAll(payload.rawText.codeUnits);
    } else {
      final width = customWidth ?? 32;
      final divider = '-' * (width <= 32 ? 32 : 48);

      void text(String s) => bytes.addAll(utf8.encode(s));
      void feed(int n) => bytes.addAll(List.filled(n, 0x0A));
      void alignCenter() => bytes.addAll([0x1B, 0x61, 1]);
      void alignLeft() => bytes.addAll([0x1B, 0x61, 0]);
      void boldOn() => bytes.addAll([0x1B, 0x45, 1]);
      void boldOff() => bytes.addAll([0x1B, 0x45, 0]);

      alignCenter();
      boldOn();
      text('${(payload.storeName ?? "IPAY").toUpperCase()}\n');
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
        boldOn();
        text('TOTAL   : ${payload.amount}\n');
        boldOff();
        text('$divider\n');
      }

      alignCenter();
      text('${payload.footer ?? "Terima kasih !"}\n');
      text('Simpan struk ini sebagai bukti sah\n');
      feed(customFeed ?? 4);
    }

    // Cut paper (jika printer mendukung autocut)
    bytes.addAll([0x1D, 0x56, 0x41, 0x00]);
    return Uint8List.fromList(bytes);
  }

  /// Cetak langsung via Bluetooth Thermal Printer dengan auto-reconnect cerdas
  Future<bool> printThermal(StrukPayload payload, {String? targetMac}) async {
    try {
      final mac = targetMac ?? await StorageService.instance.getSavedPrinterMac();
      if (mac == null || mac.isEmpty) {
        debugPrint('[PrintService] printThermal: MAC address printer kosong.');
        return false;
      }

      // Pastikan izin Bluetooth aktif
      await checkAndRequestPermissions();

      // 1. Cek status koneksi aktif
      bool isConnected = await PrintBluetoothThermal.connectionStatus;
      if (!isConnected) {
        isConnected = await connectPrinter(mac);
      }

      if (!isConnected) {
        debugPrint('[PrintService] Gagal menyambungkan ke printer $mac');
        return false;
      }

      final paperWidth = await StorageService.instance.getPaperWidth();
      final feedMargin = await StorageService.instance.getFeedMargin();
      final bytes = generateEscPosBytes(payload, customWidth: paperWidth, customFeed: feedMargin);

      // 2. Coba cetak ke printer
      bool result = await PrintBluetoothThermal.writeBytes(bytes);

      // 3. JIKA GAGAL: Soket Bluetooth mungkin stale/tertutup idle oleh printer thermal.
      // Lakukan disconnect bersih, jeda, reconnect, dan kirim ulang!
      if (!result) {
        debugPrint('[PrintService] writeBytes awal gagal. Mencoba reconnect otomatis ke $mac...');
        await disconnect();
        await Future.delayed(const Duration(milliseconds: 500));
        final reconnected = await connectPrinter(mac);
        if (reconnected) {
          result = await PrintBluetoothThermal.writeBytes(bytes);
          debugPrint('[PrintService] Hasil retry writeBytes: $result');
        }
      }

      return result;
    } catch (e) {
      debugPrint('[PrintService] Print thermal error: $e');
      return false;
    }
  }

  /// Mencetak Struk Uji Coba (Test Print) langsung dari menu Pengaturan Printer
  Future<bool> testPrint({String? targetMac}) async {
    try {
      final mac = targetMac ?? await StorageService.instance.getSavedPrinterMac();
      if (mac == null || mac.isEmpty) {
        return false;
      }

      bool isConnected = await PrintBluetoothThermal.connectionStatus;
      if (!isConnected) {
        isConnected = await connectPrinter(mac);
      }

      if (!isConnected) {
        return false;
      }

      final paperWidth = await StorageService.instance.getPaperWidth();
      final header1 = await StorageService.instance.getHeader1();
      final header2 = await StorageService.instance.getHeader2();
      final header3 = await StorageService.instance.getHeader3();
      final footer = await StorageService.instance.getFooter();
      final feedMargin = await StorageService.instance.getFeedMargin();
      final divider = '-' * (paperWidth <= 32 ? 32 : 48);

      final List<int> bytes = [];
      bytes.addAll([0x1B, 0x40]); // Reset

      void text(String s) => bytes.addAll(s.codeUnits);
      void feed(int n) => bytes.addAll(List.filled(n, 0x0A));
      void alignCenter() => bytes.addAll([0x1B, 0x61, 1]);
      void alignLeft() => bytes.addAll([0x1B, 0x61, 0]);
      void boldOn() => bytes.addAll([0x1B, 0x45, 1]);
      void boldOff() => bytes.addAll([0x1B, 0x45, 0]);

      alignCenter();
      boldOn();
      text('$header1\n');
      boldOff();
      if (header2.isNotEmpty) text('$header2\n');
      if (header3.isNotEmpty) text('$header3\n');
      text('$divider\n');

      alignCenter();
      boldOn();
      text('*** TEST PRINT BERHASIL ***\n');
      boldOff();
      text('$divider\n');

      alignLeft();
      text('Status   : KONEKSI SUKSES\n');
      text('Printer  : $mac\n');
      text('Format   : $paperWidth Karakter (58mm/80mm)\n');
      text('Waktu    : ${DateTime.now().toString().substring(0, 19)}\n');
      text('$divider\n');

      alignCenter();
      text('$footer\n');
      text('Aplikasi Kasir Native IPAY\n');
      feed(feedMargin);

      bytes.addAll([0x1D, 0x56, 0x41, 0x00]); // Cut
      final result = await PrintBluetoothThermal.writeBytes(bytes);
      return result;
    } catch (e) {
      debugPrint('[PrintService] testPrint error: $e');
      return false;
    }
  }

  /// Kerangka Dasar Cetak via Printer Laser / Ekspor PDF resmi bawaan Android
  Future<void> printLaserOrPdf(BuildContext context, StrukPayload payload) async {
    try {
      await Printing.layoutPdf(
        onLayout: (PdfPageFormat format) async {
          final doc = pw.Document();

          doc.addPage(
            pw.Page(
              pageFormat: PdfPageFormat.roll57,
              build: (pw.Context ctx) {
                return pw.Container(
                  padding: const pw.EdgeInsets.all(8),
                  child: pw.Column(
                    crossAxisAlignment: pw.CrossAxisAlignment.center,
                    children: [
                      pw.Text(
                        (payload.storeName ?? "GARUDATEL IPAY").toUpperCase(),
                        style: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 13),
                      ),
                      pw.Text('Pusat Pembayaran PPOB Terpercaya', style: const pw.TextStyle(fontSize: 8)),
                      pw.Divider(thickness: 0.5),
                      pw.Align(
                        alignment: pw.Alignment.centerLeft,
                        child: pw.Column(
                          crossAxisAlignment: pw.CrossAxisAlignment.start,
                          children: [
                            if (payload.refId != null) pw.Text('No. Ref: ${payload.refId}', style: const pw.TextStyle(fontSize: 8)),
                            if (payload.time != null) pw.Text('Waktu: ${payload.time}', style: const pw.TextStyle(fontSize: 8)),
                            pw.Text('Status: ${payload.status ?? "BERHASIL"}', style: const pw.TextStyle(fontSize: 8)),
                            pw.Divider(thickness: 0.5),
                            if (payload.productName != null) pw.Text('Produk: ${payload.productName}', style: const pw.TextStyle(fontSize: 8)),
                            if (payload.targetNumber != null) pw.Text('Tujuan: ${payload.targetNumber}', style: const pw.TextStyle(fontSize: 8)),
                            if (payload.sn != null) pw.Text('SN: ${payload.sn}', style: const pw.TextStyle(fontSize: 8)),
                            pw.Divider(thickness: 0.5),
                            if (payload.amount != null)
                              pw.Text('TOTAL: ${payload.amount}', style: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 10)),
                          ],
                        ),
                      ),
                      pw.Divider(thickness: 0.5),
                      pw.Text(payload.footer ?? 'Terima kasih atas kunjungan Anda', style: const pw.TextStyle(fontSize: 7)),
                    ],
                  ),
                );
              },
            ),
          );

          return doc.save();
        },
        name: 'Struk_${payload.refId ?? "GarudaTel"}',
      );
    } catch (e) {
      debugPrint('[PrintService] printLaserOrPdf error: $e');
    }
  }

  /// Mengirim struk langsung ke aplikasi RawBT POS (1-Klik via Intent) dengan format rapi
  Future<bool> printViaRawBt(StrukPayload payload) async {
    try {
      final paperWidth = await StorageService.instance.getPaperWidth();
      final header1 = await StorageService.instance.getHeader1();
      final footer = await StorageService.instance.getFooter();

      // Format teks struk secara rapi agar tidak mencetak JSON mentah
      final String text = payload.buildReceiptText(
        paperWidth: paperWidth,
        headerStore: header1.isNotEmpty ? header1 : null,
        footerText: footer.isNotEmpty ? footer : null,
      );

      final base64Data = base64Encode(utf8.encode(text));
      final url = 'rawbt:data:text/plain;base64,$base64Data';
      final uri = Uri.parse(url);
      return await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (e) {
      debugPrint('[PrintService] printViaRawBt error: $e');
      return false;
    }
  }

  /// Menampilkan Modal Dialog Kasir untuk memilih Printer Thermal atau Laser/PDF
  void showPrintSelectionModal(BuildContext context, StrukPayload payload) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => _PrintDialogWidget(payload: payload),
    );
  }
}

class _PrintDialogWidget extends StatefulWidget {
  final StrukPayload payload;
  const _PrintDialogWidget({required this.payload});

  @override
  State<_PrintDialogWidget> createState() => _PrintDialogWidgetState();
}

class _PrintDialogWidgetState extends State<_PrintDialogWidget> {
  List<BluetoothInfo> _printers = [];
  bool _isLoading = true;
  String? _savedMac;
  bool _isPrinting = false;

  @override
  void initState() {
    super.initState();
    _loadPrinters();
  }

  Future<void> _loadPrinters() async {
    if (!mounted) return;
    setState(() => _isLoading = true);
    try {
      await PrintService.instance.checkAndRequestPermissions();
      _savedMac = await StorageService.instance.getSavedPrinterMac();
      final list = await PrintService.instance.getPairedPrinters();
      if (!mounted) return;
      setState(() {
        _printers = list;
        _isLoading = false;
      });
    } catch (e) {
      debugPrint('[PrintDialog] _loadPrinters error: $e');
      if (!mounted) return;
      setState(() {
        _printers = [];
        _isLoading = false;
      });
    }
  }

  Future<void> _doPrintThermal(String mac) async {
    if (_isPrinting) return;
    setState(() => _isPrinting = true);
    bool success = false;
    try {
      success = await PrintService.instance.printThermal(widget.payload, targetMac: mac);
    } catch (e) {
      debugPrint('[PrintDialog] _doPrintThermal error: $e');
      success = false;
    }
    if (!mounted) return;
    setState(() => _isPrinting = false);

    Navigator.pop(context);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(success ? '✅ Struk berhasil dicetak!' : '❌ Gagal mencetak. Periksa koneksi printer atau gunakan RawBT.'),
        backgroundColor: success ? AppConfig.primaryTeal : Colors.red,
        action: success
            ? null
            : SnackBarAction(
                label: 'Buka RawBT',
                textColor: Colors.white,
                onPressed: () => PrintService.instance.printViaRawBt(widget.payload),
              ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Center(
            child: Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.grey[300],
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'Cetak Struk Kasir',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: AppConfig.textDark),
              ),
              Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.settings_outlined, color: AppConfig.primaryTeal),
                    onPressed: () {
                      Navigator.pop(context);
                      Navigator.push(
                        context,
                        MaterialPageRoute(builder: (_) => const PrinterSettingsScreen()),
                      );
                    },
                    tooltip: 'Pengaturan Printer',
                  ),
                  IconButton(
                    icon: const Icon(Icons.refresh, color: AppConfig.primaryTeal),
                    onPressed: _loadPrinters,
                    tooltip: 'Pindai Ulang',
                  ),
                ],
              ),
            ],
          ),
          const Text(
            'Pilih printer thermal bluetooth kasir atau gunakan aplikasi RawBT / PDF:',
            style: TextStyle(fontSize: 13, color: AppConfig.textMuted),
          ),
          const SizedBox(height: 16),

          // Tombol 1: Buka di Aplikasi RawBT POS
          ListTile(
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: BorderSide(color: Colors.blueGrey.shade200),
            ),
            tileColor: Colors.blueGrey.shade50,
            leading: CircleAvatar(
              backgroundColor: Colors.blueGrey.shade700,
              child: const Icon(Icons.phone_android_rounded, color: Colors.white, size: 20),
            ),
            title: const Text('Buka di Aplikasi RawBT POS', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
            subtitle: const Text('Cetak instan 1-klik via driver RawBT Printer', style: TextStyle(fontSize: 12)),
            trailing: const Icon(Icons.arrow_forward_ios_rounded, size: 14),
            onTap: () {
              Navigator.pop(context);
              PrintService.instance.printViaRawBt(widget.payload);
            },
          ),
          const SizedBox(height: 8),

          // Tombol 2: Cetak Laser / Simpan PDF
          ListTile(
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: const BorderSide(color: AppConfig.primaryTeal, width: 1.2),
            ),
            tileColor: AppConfig.primaryLight,
            leading: const CircleAvatar(
              backgroundColor: AppConfig.primaryTeal,
              child: Icon(Icons.picture_as_pdf_rounded, color: Colors.white, size: 20),
            ),
            title: const Text('Cetak via Printer Laser / PDF', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
            subtitle: const Text('Gunakan sistem cetak bawaan Android', style: TextStyle(fontSize: 12)),
            trailing: const Icon(Icons.arrow_forward_ios_rounded, size: 14, color: AppConfig.primaryTeal),
            onTap: () {
              Navigator.pop(context);
              PrintService.instance.printLaserOrPdf(context, widget.payload);
            },
          ),
          const SizedBox(height: 14),

          const Text(
            'Printer Bluetooth Tersedia:',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppConfig.textDark),
          ),
          const SizedBox(height: 8),

          if (_isLoading)
            const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: CircularProgressIndicator(color: AppConfig.primaryTeal),
              ),
            )
          else if (_printers.isEmpty)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.amber.shade50,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.amber.shade200),
              ),
              child: const Row(
                children: [
                  Icon(Icons.bluetooth_searching, color: Colors.amber),
                  SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'Tidak ada printer bluetooth yang terhubung. Pastikan printer thermal sudah dipasangkan (pair) di Pengaturan Bluetooth HP.',
                      style: TextStyle(fontSize: 12, color: Colors.black87),
                    ),
                  ),
                ],
              ),
            )
          else
            Flexible(
              child: ListView.separated(
                shrinkWrap: true,
                itemCount: _printers.length,
                separatorBuilder: (_, _) => const SizedBox(height: 8),
                itemBuilder: (ctx, i) {
                  final p = _printers[i];
                  final isSaved = p.macAdress == _savedMac;

                  return ListTile(
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                      side: BorderSide(color: isSaved ? AppConfig.primaryTeal : Colors.grey.shade200),
                    ),
                    tileColor: isSaved ? AppConfig.primaryLight.withAlpha(80) : Colors.grey.shade50,
                    leading: Icon(Icons.print_rounded, color: isSaved ? AppConfig.primaryTeal : Colors.grey),
                    title: Text(p.name.isNotEmpty ? p.name : 'Printer Thermal', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
                    subtitle: Text(p.macAdress, style: const TextStyle(fontSize: 12, color: Colors.grey)),
                    trailing: ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppConfig.primaryTeal,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                      ),
                      onPressed: _isPrinting ? null : () => _doPrintThermal(p.macAdress),
                      child: _isPrinting
                          ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                          : const Text('Cetak'),
                    ),
                  );
                },
              ),
            ),
        ],
      ),
    );
  }
}
