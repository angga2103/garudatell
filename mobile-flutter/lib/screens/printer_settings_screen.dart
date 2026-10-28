import 'package:flutter/material.dart';
import '../config/app_config.dart';
import '../services/print_service.dart';
import '../services/storage_service.dart';
import 'webview_screen.dart';

class PrinterSettingsScreen extends StatefulWidget {
  const PrinterSettingsScreen({super.key});

  @override
  State<PrinterSettingsScreen> createState() => _PrinterSettingsScreenState();
}

class _PrinterSettingsScreenState extends State<PrinterSettingsScreen> {
  String? _savedMac;
  String? _savedName;
  String _printMethod = 'direct';
  int _paperWidth = 32;
  int _feedMargin = 4;

  final TextEditingController _header1Controller = TextEditingController();
  final TextEditingController _header2Controller = TextEditingController();
  final TextEditingController _header3Controller = TextEditingController();
  final TextEditingController _footerController = TextEditingController();

  bool _isLoading = true;
  bool _isTestingPrint = false;

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  @override
  void dispose() {
    _header1Controller.dispose();
    _header2Controller.dispose();
    _header3Controller.dispose();
    _footerController.dispose();
    super.dispose();
  }

  Future<void> _loadSettings() async {
    final storage = StorageService.instance;
    final mac = await storage.getSavedPrinterMac();
    final name = await storage.getSavedPrinterName();
    final method = await storage.getPrintMethod();
    final width = await storage.getPaperWidth();
    final feed = await storage.getFeedMargin();
    final h1 = await storage.getHeader1();
    final h2 = await storage.getHeader2();
    final h3 = await storage.getHeader3();
    final foot = await storage.getFooter();

    if (mounted) {
      setState(() {
        _savedMac = mac;
        _savedName = name;
        _printMethod = method;
        _paperWidth = width;
        _feedMargin = feed;
        _header1Controller.text = h1;
        _header2Controller.text = h2;
        _header3Controller.text = h3;
        _footerController.text = foot;
        _isLoading = false;
      });
    }
  }

  Future<void> _saveSettings() async {
    final storage = StorageService.instance;
    await storage.setPrintMethod(_printMethod);
    await storage.setPaperWidth(_paperWidth);
    await storage.setFeedMargin(_feedMargin);
    await storage.setHeader1(_header1Controller.text.trim());
    await storage.setHeader2(_header2Controller.text.trim());
    await storage.setHeader3(_header3Controller.text.trim());
    await storage.setFooter(_footerController.text.trim());

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('✅ Pengaturan printer kasir berhasil disimpan!'),
          backgroundColor: AppConfig.primaryTeal,
          duration: Duration(seconds: 2),
        ),
      );
    }
  }

  Future<void> _doTestPrint() async {
    if (_savedMac == null || _savedMac!.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Pilih printer Bluetooth kasir terlebih dahulu.'),
          backgroundColor: Colors.orange,
        ),
      );
      return;
    }

    setState(() => _isTestingPrint = true);
    final success = await PrintService.instance.testPrint(targetMac: _savedMac);
    if (!mounted) return;
    setState(() => _isTestingPrint = false);

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(
          children: [
            Icon(
              success ? Icons.check_circle_rounded : Icons.error_outline_rounded,
              color: success ? AppConfig.primaryTeal : Colors.red,
            ),
            const SizedBox(width: 8),
            Text(
              success ? 'Test Print Berhasil!' : 'Test Print Gagal',
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
            ),
          ],
        ),
        content: Text(
          success
              ? 'Data ESC/POS berhasil dikirim ke printer $_savedName ($_savedMac). Periksa kertas struk Anda.'
              : 'Gagal menghubungkan ke printer $_savedName ($_savedMac).\n\nTips:\n1. Pastikan printer menyala.\n2. Pastikan printer tidak sedang terhubung ke aplikasi lain (seperti RawBT).\n3. Coba matikan dan hidupkan kembali Bluetooth HP.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Tutup', style: TextStyle(fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
  }

  void _showSelectPrinterModal() async {
    await PrintService.instance.checkAndRequestPermissions();
    final printers = await PrintService.instance.getPairedPrinters();

    if (!mounted) return;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => Container(
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
            const Text(
              'Pilih Printer Bluetooth',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: AppConfig.textDark),
            ),
            const SizedBox(height: 6),
            const Text(
              'Pilih printer kasir Anda dari daftar perangkat yang sudah dipasangkan di HP:',
              style: TextStyle(fontSize: 12, color: AppConfig.textMuted),
            ),
            const SizedBox(height: 16),
            if (printers.isEmpty)
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.amber.shade50,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.amber.shade200),
                ),
                child: const Text(
                  'Tidak ada perangkat Bluetooth yang terpasang (paired). Pasangkan printer kasir Anda terlebih dahulu di menu Pengaturan Bluetooth HP.',
                  style: TextStyle(fontSize: 12, color: Colors.black87),
                ),
              )
            else
              Flexible(
                child: ListView.separated(
                  shrinkWrap: true,
                  itemCount: printers.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final p = printers[index];
                    final isCurrent = p.macAdress == _savedMac;

                    return ListTile(
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                        side: BorderSide(
                          color: isCurrent ? AppConfig.primaryTeal : Colors.grey.shade200,
                          width: isCurrent ? 2 : 1,
                        ),
                      ),
                      tileColor: isCurrent ? AppConfig.primaryLight : Colors.grey.shade50,
                      leading: Icon(
                        Icons.print_rounded,
                        color: isCurrent ? AppConfig.primaryTeal : Colors.grey,
                      ),
                      title: Text(
                        p.name.isNotEmpty ? p.name : 'Printer Thermal',
                        style: TextStyle(
                          fontWeight: isCurrent ? FontWeight.w800 : FontWeight.w600,
                          fontSize: 14,
                        ),
                      ),
                      subtitle: Text(p.macAdress, style: const TextStyle(fontSize: 12, color: Colors.grey)),
                      trailing: isCurrent
                          ? const Icon(Icons.check_circle, color: AppConfig.primaryTeal)
                          : const Icon(Icons.radio_button_unchecked, color: Colors.grey),
                      onTap: () async {
                        final storage = StorageService.instance;
                        final mac = p.macAdress;
                        final name = p.name;
                        Navigator.pop(ctx);
                        await storage.setSavedPrinterMac(mac);
                        await storage.setSavedPrinterName(name);
                        if (!mounted) return;
                        setState(() {
                          _savedMac = mac;
                          _savedName = name;
                        });
                      },
                    );
                  },
                ),
              ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator(color: AppConfig.primaryTeal)),
      );
    }

    return Scaffold(
      backgroundColor: const Color(0xFFF8FAFC),
      appBar: AppBar(
        title: const Text(
          'Pengaturan Printer Kasir',
          style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: Colors.white),
        ),
        backgroundColor: AppConfig.primaryTeal,
        elevation: 0,
        centerTitle: true,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white),
          onPressed: () {
            if (Navigator.canPop(context)) {
              Navigator.pop(context);
            } else {
              Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => const WebViewScreen()));
            }
          },
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 8.0),
            child: TextButton.icon(
              style: TextButton.styleFrom(
                backgroundColor: Colors.white.withAlpha(40),
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
              ),
              icon: const Icon(Icons.storefront_rounded, size: 16, color: Colors.white),
              label: const Text(
                'Kasir Web',
                style: TextStyle(fontWeight: FontWeight.w800, fontSize: 12, color: Colors.white),
              ),
              onPressed: () {
                Navigator.push(context, MaterialPageRoute(builder: (_) => const WebViewScreen()));
              },
            ),
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // KARTU 1: PRINTER BLUETOOTH TERPILIH
            _buildPrinterCard(),
            const SizedBox(height: 16),

            // KARTU 2: METODE / JALUR CETAK
            _buildMethodCard(),
            const SizedBox(height: 16),

            // KARTU 3: FORMAT KERTAS & STRUK
            _buildPaperCard(),
            const SizedBox(height: 16),

            // KARTU 4: NAMA TOKO & FOOTER
            _buildReceiptIdentityCard(),
            const SizedBox(height: 24),

            // TOMBOL SIMPAN
            SizedBox(
              width: double.infinity,
              height: 50,
              child: ElevatedButton.icon(
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppConfig.primaryTeal,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                  elevation: 2,
                ),
                icon: const Icon(Icons.save_rounded),
                label: const Text(
                  'SIMPAN PENGATURAN',
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, letterSpacing: 0.5),
                ),
                onPressed: _saveSettings,
              ),
            ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  Widget _buildPrinterCard() {
    final hasPrinter = _savedMac != null && _savedMac!.isNotEmpty;

    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: hasPrinter ? AppConfig.primaryTeal.withAlpha(80) : Colors.grey.shade300),
      ),
      color: Colors.white,
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: AppConfig.primaryLight,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Icon(Icons.print_rounded, color: AppConfig.primaryTeal, size: 24),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Printer Kasir Utama',
                        style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: AppConfig.textMuted),
                      ),
                      Text(
                        hasPrinter ? (_savedName ?? 'Printer Thermal') : 'Belum Ada Printer',
                        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: AppConfig.textDark),
                      ),
                      if (hasPrinter)
                        Text(
                          _savedMac!,
                          style: const TextStyle(fontSize: 11, color: AppConfig.textMuted),
                        ),
                    ],
                  ),
                ),
                if (hasPrinter)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: Colors.green.shade50,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.green.shade200),
                    ),
                    child: const Text('Aktif', style: TextStyle(color: Colors.green, fontSize: 11, fontWeight: FontWeight.w700)),
                  ),
              ],
            ),
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppConfig.primaryTeal,
                      side: const BorderSide(color: AppConfig.primaryTeal),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      padding: const EdgeInsets.symmetric(vertical: 11),
                    ),
                    icon: const Icon(Icons.bluetooth_searching, size: 18),
                    label: Text(
                      hasPrinter ? 'Ganti Printer' : 'Pilih Printer',
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
                    ),
                    onPressed: _showSelectPrinterModal,
                  ),
                ),
                if (hasPrinter) ...[
                  const SizedBox(width: 10),
                  Expanded(
                    child: ElevatedButton.icon(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppConfig.primaryTeal,
                        foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                        padding: const EdgeInsets.symmetric(vertical: 11),
                      ),
                      icon: _isTestingPrint
                          ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                          : const Icon(Icons.receipt_long_rounded, size: 18),
                      label: const Text('Test Print', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
                      onPressed: _isTestingPrint ? null : _doTestPrint,
                    ),
                  ),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMethodCard() {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: Colors.grey.shade200),
      ),
      color: Colors.white,
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Metode / Jalur Cetak Struk',
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: AppConfig.textDark),
            ),
            const SizedBox(height: 4),
            const Text(
              'Pilih bagaimana aplikasi mengirim struk transaksi saat tombol Cetak ditekan:',
              style: TextStyle(fontSize: 12, color: AppConfig.textMuted),
            ),
            const SizedBox(height: 12),
            _buildMethodTile(
              value: 'direct',
              title: 'Bluetooth Thermal Langsung (Direct Native)',
              subtitle: 'Cetak langsung ke printer kasir tanpa aplikasi pihak ketiga (cepat & instan).',
              icon: Icons.bluetooth_connected_rounded,
            ),
            _buildMethodTile(
              value: 'rawbt',
              title: 'Aplikasi RawBT POS (1-Klik via Intent)',
              subtitle: 'Gunakan jika printer bluetooth memiliki pembatasan soket oleh sistem HP.',
              icon: Icons.phone_android_rounded,
            ),
            _buildMethodTile(
              value: 'pdf',
              title: 'Sistem Cetak Android (PDF / Laser)',
              subtitle: 'Buka print spooler resmi Android atau simpan bukti transaksi sebagai PDF.',
              icon: Icons.picture_as_pdf_rounded,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMethodTile({
    required String value,
    required String title,
    required String subtitle,
    required IconData icon,
  }) {
    final isSelected = _printMethod == value;
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: () => setState(() => _printMethod = value),
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: isSelected ? AppConfig.primaryLight : Colors.grey.shade50,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isSelected ? AppConfig.primaryTeal : Colors.grey.shade200,
            width: isSelected ? 1.8 : 1,
          ),
        ),
        child: Row(
          children: [
            Icon(icon, color: isSelected ? AppConfig.primaryTeal : Colors.grey, size: 22),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: TextStyle(
                      fontWeight: isSelected ? FontWeight.w800 : FontWeight.w600,
                      fontSize: 13,
                      color: isSelected ? AppConfig.primaryTeal : AppConfig.textDark,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(subtitle, style: const TextStyle(fontSize: 11, color: AppConfig.textMuted)),
                ],
              ),
            ),
            Icon(
              isSelected ? Icons.check_circle : Icons.radio_button_unchecked,
              color: isSelected ? AppConfig.primaryTeal : Colors.grey,
              size: 20,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildPaperCard() {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: Colors.grey.shade200),
      ),
      color: Colors.white,
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Format Kertas & Spasi Baris',
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: AppConfig.textDark),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: InkWell(
                    onTap: () => setState(() => _paperWidth = 32),
                    child: Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: _paperWidth == 32 ? AppConfig.primaryLight : Colors.grey.shade50,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(
                          color: _paperWidth == 32 ? AppConfig.primaryTeal : Colors.grey.shade200,
                          width: _paperWidth == 32 ? 2 : 1,
                        ),
                      ),
                      child: Column(
                        children: [
                          Text(
                            '58 mm',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w800,
                              color: _paperWidth == 32 ? AppConfig.primaryTeal : AppConfig.textDark,
                            ),
                          ),
                          const SizedBox(height: 4),
                          const Text('32 Karakter / Baris', style: TextStyle(fontSize: 11, color: AppConfig.textMuted)),
                          const Text('(Kasir Portable)', style: TextStyle(fontSize: 10, color: AppConfig.textMuted)),
                        ],
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: InkWell(
                    onTap: () => setState(() => _paperWidth = 48),
                    child: Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: _paperWidth == 48 ? AppConfig.primaryLight : Colors.grey.shade50,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(
                          color: _paperWidth == 48 ? AppConfig.primaryTeal : Colors.grey.shade200,
                          width: _paperWidth == 48 ? 2 : 1,
                        ),
                      ),
                      child: Column(
                        children: [
                          Text(
                            '80 mm',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w800,
                              color: _paperWidth == 48 ? AppConfig.primaryTeal : AppConfig.textDark,
                            ),
                          ),
                          const SizedBox(height: 4),
                          const Text('48 Karakter / Baris', style: TextStyle(fontSize: 11, color: AppConfig.textMuted)),
                          const Text('(Kasir Desktop)', style: TextStyle(fontSize: 10, color: AppConfig.textMuted)),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Margin Bawah (Feed Spacing)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
                    Text('Jumlah baris kosong sebelum potong kertas', style: TextStyle(fontSize: 11, color: AppConfig.textMuted)),
                  ],
                ),
                DropdownButton<int>(
                  value: _feedMargin,
                  items: [2, 3, 4, 5, 6].map((n) {
                    return DropdownMenuItem(value: n, child: Text('$n Baris'));
                  }).toList(),
                  onChanged: (val) {
                    if (val != null) setState(() => _feedMargin = val);
                  },
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildReceiptIdentityCard() {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: Colors.grey.shade200),
      ),
      color: Colors.white,
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Identitas Konter / Toko di Struk',
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: AppConfig.textDark),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _header1Controller,
              decoration: const InputDecoration(
                labelText: 'Header 1 (Nama Toko / Konter)',
                hintText: 'Contoh: WARUNG BU YAYUK / IPAY',
                border: OutlineInputBorder(),
                isDense: true,
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _header2Controller,
              decoration: const InputDecoration(
                labelText: 'Header 2 (Slogan / Alamat)',
                hintText: 'Contoh: Pusat Pembayaran PPOB Terpercaya',
                border: OutlineInputBorder(),
                isDense: true,
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _header3Controller,
              decoration: const InputDecoration(
                labelText: 'Header 3 (No. HP / WA Konter)',
                hintText: 'Contoh: 08123456789',
                border: OutlineInputBorder(),
                isDense: true,
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _footerController,
              decoration: const InputDecoration(
                labelText: 'Catatan Footer Struk',
                hintText: 'Contoh: Terima kasih atas kunjungan Anda',
                border: OutlineInputBorder(),
                isDense: true,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
