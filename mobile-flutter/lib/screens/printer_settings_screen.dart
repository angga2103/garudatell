import 'package:esc_pos_utils_plus/esc_pos_utils_plus.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../config/app_config.dart';
import '../providers/printer_provider.dart';
import 'webview_screen.dart';

/// Halaman Pengaturan Bluetooth Thermal POS Printer
/// Bersih, elegan, offline-first, dan ramah kasir (DrinkPOS Lite style)
class PrinterSettingsScreen extends StatefulWidget {
  const PrinterSettingsScreen({super.key});

  @override
  State<PrinterSettingsScreen> createState() => _PrinterSettingsScreenState();
}

class _PrinterSettingsScreenState extends State<PrinterSettingsScreen> {
  final TextEditingController _manualMacController = TextEditingController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<PrinterProvider>().init();
    });
  }

  @override
  void dispose() {
    _manualMacController.dispose();
    super.dispose();
  }

  void _navigateToWeb() {
    if (Navigator.canPop(context)) {
      Navigator.pop(context);
    } else {
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (_) => const WebViewScreen()),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<PrinterProvider>(
      builder: (context, provider, _) {
        return Scaffold(
          backgroundColor: const Color(0xFFF6F8FA),
          appBar: AppBar(
            elevation: 0,
            backgroundColor: AppConfig.primaryTeal,
            foregroundColor: Colors.white,
            leading: IconButton(
              icon: const Icon(Icons.arrow_back_rounded),
              onPressed: _navigateToWeb,
              tooltip: 'Kembali ke Kasir',
            ),
            title: const Text(
              'Pengaturan Printer Kasir',
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
            ),
            actions: [
              // Tombol Pintas Akses Mandiri Kasir ke Web Kasir PPOB
              Padding(
                padding: const EdgeInsets.only(right: 12),
                child: ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.white,
                    foregroundColor: AppConfig.primaryTeal,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                  ),
                  icon: const Icon(Icons.point_of_sale_rounded, size: 18),
                  label: const Text(
                    'Kasir Web',
                    style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
                  ),
                  onPressed: _navigateToWeb,
                ),
              ),
            ],
          ),
          body: RefreshIndicator(
            color: AppConfig.primaryTeal,
            onRefresh: () => provider.scanDevices(),
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                // 1. STATUS CARD DI BAGIAN ATAS
                _buildStatusCard(context, provider),
                const SizedBox(height: 16),

                // Error Banner bila ada
                if (provider.errorMessage != null) ...[
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFECEB),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: const Color(0xFFFFB4AE)),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.error_outline, color: Colors.red, size: 22),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            provider.errorMessage!,
                            style: const TextStyle(color: Color(0xFF900000), fontSize: 13),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                ],

                // 2. PILIHAN UKURAN KERTAS
                _buildPaperSizeSection(context, provider),
                const SizedBox(height: 16),

                // 3. TOMBOL TINDAKAN UTAMA
                _buildActionButtons(context, provider),
                const SizedBox(height: 20),

                // 4. DAFTAR PRINTER BLUETOOTH DITEMUKAN
                _buildDeviceListSection(context, provider),
                const SizedBox(height: 20),

                // 5. KONEKSI MANUAL
                _buildManualConnectionSection(context, provider),
                const SizedBox(height: 30),
              ],
            ),
          ),
        );
      },
    );
  }

  // ==========================================
  // 1. STATUS CARD
  // ==========================================
  Widget _buildStatusCard(BuildContext context, PrinterProvider provider) {
    final bool isConnected = provider.isConnected;
    final String printerName = provider.connectedName ?? 'Printer POS';
    final String? mac = provider.connectedMac;

    if (isConnected) {
      return Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: const Color(0xFFE8F5E9),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: const Color(0xFFA5D6A7), width: 1.5),
          boxShadow: [
            BoxShadow(
              color: Colors.green.withValues(alpha: 0.1),
              blurRadius: 10,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(12),
              decoration: const BoxDecoration(
                color: Color(0xFF2E7D32),
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.print_rounded, color: Colors.white, size: 28),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 8,
                        height: 8,
                        decoration: const BoxDecoration(
                          color: Color(0xFF2E7D32),
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 6),
                      const Text(
                        'STATUS: TERHUBUNG',
                        style: TextStyle(
                          color: Color(0xFF2E7D32),
                          fontWeight: FontWeight.w800,
                          fontSize: 12,
                          letterSpacing: 0.5,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    printerName,
                    style: const TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.bold,
                      color: Color(0xFF1B5E20),
                    ),
                  ),
                  if (mac != null) ...[
                    const SizedBox(height: 2),
                    Text(
                      'MAC: $mac',
                      style: TextStyle(
                        fontSize: 12,
                        fontFamily: 'monospace',
                        color: Colors.grey.shade700,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                foregroundColor: const Color(0xFFC62828),
                side: const BorderSide(color: Color(0xFFEF9A9A)),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              ),
              onPressed: () => provider.disconnect(),
              child: const Text('Putuskan', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
            ),
          ],
        ),
      );
    }

    // Kotak abu-abu jika belum terhubung
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.grey.shade300),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.03),
            blurRadius: 8,
            offset: const Offset(0, 3),
          ),
        ],
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.grey.shade100,
              shape: BoxShape.circle,
            ),
            child: Icon(Icons.print_disabled_rounded, color: Colors.grey.shade600, size: 28),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(
                        color: Colors.grey.shade500,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      'STATUS: BELUM TERHUBUNG',
                      style: TextStyle(
                        color: Colors.grey.shade700,
                        fontWeight: FontWeight.w800,
                        fontSize: 12,
                        letterSpacing: 0.5,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                const Text(
                  'Printer Belum Dipilih',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.black87),
                ),
                const SizedBox(height: 2),
                Text(
                  'Pilih printer di daftar bawah atau masukkan MAC',
                  style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ==========================================
  // 2. PILIHAN UKURAN KERTAS
  // ==========================================
  Widget _buildPaperSizeSection(BuildContext context, PrinterProvider provider) {
    final is58 = provider.paperSize == PaperSize.mm58;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.grey.shade200),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.receipt_long_rounded, color: AppConfig.primaryTeal, size: 22),
              const SizedBox(width: 8),
              const Text(
                'Ukuran Kertas Struk',
                style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: Colors.black87),
              ),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: AppConfig.primaryTeal.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  is58 ? '32 Karakter/Baris' : '48 Karakter/Baris',
                  style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    color: AppConfig.primaryTeal,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: _buildPaperSizeOption(
                  title: '58 mm',
                  subtitle: 'Struk Kecil (Standar Kasir)',
                  selected: is58,
                  onTap: () => provider.setPaperSize(PaperSize.mm58),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildPaperSizeOption(
                  title: '80 mm',
                  subtitle: 'Struk Lebar / Resto',
                  selected: !is58,
                  onTap: () => provider.setPaperSize(PaperSize.mm80),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildPaperSizeOption({
    required String title,
    required String subtitle,
    required bool selected,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 10),
        decoration: BoxDecoration(
          color: selected ? AppConfig.primaryTeal.withValues(alpha: 0.08) : Colors.grey.shade50,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: selected ? AppConfig.primaryTeal : Colors.grey.shade300,
            width: selected ? 2 : 1,
          ),
        ),
        child: Column(
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  selected ? Icons.radio_button_checked : Icons.radio_button_off,
                  color: selected ? AppConfig.primaryTeal : Colors.grey.shade400,
                  size: 18,
                ),
                const SizedBox(width: 6),
                Text(
                  title,
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 16,
                    color: selected ? AppConfig.primaryTeal : Colors.black87,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              subtitle,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 11,
                color: selected ? AppConfig.primaryTeal : Colors.grey.shade600,
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ==========================================
  // 3. TOMBOL TINDAKAN UTAMA
  // ==========================================
  Widget _buildActionButtons(BuildContext context, PrinterProvider provider) {
    return Column(
      children: [
        // Tombol Tes Cetak Struk Thermal (Hijau menonjol)
        SizedBox(
          width: double.infinity,
          height: 50,
          child: ElevatedButton.icon(
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF2E7D32),
              foregroundColor: Colors.white,
              elevation: 2,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
            icon: const Icon(Icons.receipt_rounded, size: 22),
            label: const Text(
              'Tes Cetak Struk Thermal',
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
            ),
            onPressed: () async {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('⏳ Mengirim data cetak struk pengujian...'),
                  duration: Duration(seconds: 1),
                ),
              );

              final success = await provider.testPrint();
              if (context.mounted) {
                ScaffoldMessenger.of(context).hideCurrentSnackBar();
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(
                      success
                          ? '✅ Berhasil mencetak struk pengujian ke printer!'
                          : (provider.errorMessage ?? '⚠️ Gagal mencetak. Hubungkan printer terlebih dahulu.'),
                    ),
                    backgroundColor: success ? const Color(0xFF2E7D32) : Colors.red.shade700,
                    duration: const Duration(seconds: 3),
                  ),
                );
              }
            },
          ),
        ),
        const SizedBox(height: 10),

        // Tombol Pindai Ulang Bluetooth
        SizedBox(
          width: double.infinity,
          height: 46,
          child: OutlinedButton.icon(
            style: OutlinedButton.styleFrom(
              foregroundColor: AppConfig.primaryTeal,
              side: const BorderSide(color: AppConfig.primaryTeal),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
            icon: provider.isScanning
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: AppConfig.primaryTeal),
                  )
                : const Icon(Icons.sync_rounded, size: 20),
            label: Text(
              provider.isScanning ? 'Memindai Perangkat Bluetooth...' : 'Pindai Ulang Bluetooth',
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
            ),
            onPressed: provider.isScanning ? null : () => provider.scanDevices(),
          ),
        ),
      ],
    );
  }

  // ==========================================
  // 4. DAFTAR PRINTER BLUETOOTH DITEMUKAN
  // ==========================================
  Widget _buildDeviceListSection(BuildContext context, PrinterProvider provider) {
    final devices = provider.availableDevices;

    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.grey.shade200),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
            child: Row(
              children: [
                const Icon(Icons.devices_rounded, color: AppConfig.primaryTeal, size: 20),
                const SizedBox(width: 8),
                const Text(
                  'Printer Bluetooth Ditemukan',
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: Colors.black87),
                ),
                const Spacer(),
                Text(
                  '${devices.length} Perangkat',
                  style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          if (provider.isScanning && devices.isEmpty)
            const Padding(
              padding: EdgeInsets.all(28.0),
              child: Center(
                child: Column(
                  children: [
                    CircularProgressIndicator(color: AppConfig.primaryTeal),
                    SizedBox(height: 12),
                    Text('Mencari printer Bluetooth kasir di sekitar...'),
                  ],
                ),
              ),
            )
          else if (devices.isEmpty)
            Padding(
              padding: const EdgeInsets.all(24.0),
              child: Center(
                child: Column(
                  children: [
                    Icon(Icons.bluetooth_searching, size: 40, color: Colors.grey.shade400),
                    const SizedBox(height: 8),
                    const Text(
                      'Tidak ada printer Bluetooth yang terpasang',
                      style: TextStyle(fontWeight: FontWeight.w600, color: Colors.black87),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Pasangkan (Pair) printer thermal Anda di Menu Bluetooth HP Android terlebih dahulu, lalu klik "Pindai Ulang".',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
                    ),
                  ],
                ),
              ),
            )
          else
            ListView.separated(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              itemCount: devices.length,
              separatorBuilder: (context, index) => const Divider(height: 1, indent: 60),
              itemBuilder: (ctx, index) {
                final device = devices[index];
                final bool isCurrent = provider.isConnected &&
                    provider.connectedMac?.toUpperCase() == device.macAdress.toUpperCase();

                return ListTile(
                  contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                  leading: CircleAvatar(
                    backgroundColor: isCurrent
                        ? const Color(0xFFE8F5E9)
                        : AppConfig.primaryTeal.withValues(alpha: 0.1),
                    child: Icon(
                      Icons.print,
                      color: isCurrent ? const Color(0xFF2E7D32) : AppConfig.primaryTeal,
                      size: 22,
                    ),
                  ),
                  title: Text(
                    device.name.isEmpty ? 'Printer Tanpa Nama' : device.name,
                    style: TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 15,
                      color: isCurrent ? const Color(0xFF1B5E20) : Colors.black87,
                    ),
                  ),
                  subtitle: Text(
                    device.macAdress,
                    style: TextStyle(
                      fontSize: 12,
                      fontFamily: 'monospace',
                      color: Colors.grey.shade700,
                    ),
                  ),
                  trailing: isCurrent
                      ? Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                          decoration: BoxDecoration(
                            color: const Color(0xFFE8F5E9),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(color: const Color(0xFFA5D6A7)),
                          ),
                          child: const Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.check_circle, size: 14, color: Color(0xFF2E7D32)),
                              SizedBox(width: 4),
                              Text(
                                'Terhubung',
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: Color(0xFF2E7D32),
                                  fontSize: 12,
                                ),
                              ),
                            ],
                          ),
                        )
                      : ElevatedButton(
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppConfig.primaryTeal,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                          ),
                          onPressed: () async {
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                content: Text('Menghubungkan ke ${device.name.isEmpty ? device.macAdress : device.name}...'),
                                duration: const Duration(seconds: 1),
                              ),
                            );
                            final ok = await provider.connect(device.macAdress, deviceName: device.name);
                            if (context.mounted) {
                              ScaffoldMessenger.of(context).hideCurrentSnackBar();
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(
                                  content: Text(
                                    ok ? '✅ Terhubung ke ${device.name}!' : '⚠️ Gagal terhubung ke ${device.name}',
                                  ),
                                  backgroundColor: ok ? const Color(0xFF2E7D32) : Colors.red,
                                ),
                              );
                            }
                          },
                          child: const Text('Hubungkan', style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold)),
                        ),
                );
              },
            ),
        ],
      ),
    );
  }

  // ==========================================
  // 5. KONEKSI MANUAL
  // ==========================================
  Widget _buildManualConnectionSection(BuildContext context, PrinterProvider provider) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.grey.shade200),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.edit_note_rounded, color: AppConfig.primaryTeal, size: 22),
              SizedBox(width: 8),
              Text(
                'Koneksi Manual MAC Address',
                style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: Colors.black87),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            'Gunakan opsi ini jika nama printer tidak muncul di daftar pemindaian (misal: 66:02:BD:06:18:7B).',
            style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _manualMacController,
                  textCapitalization: TextCapitalization.characters,
                  decoration: InputDecoration(
                    hintText: 'Contoh: 66:02:BD:06:18:7B',
                    hintStyle: TextStyle(color: Colors.grey.shade400, fontSize: 13),
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: BorderSide(color: Colors.grey.shade300),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: const BorderSide(color: AppConfig.primaryTeal, width: 2),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppConfig.primaryTeal,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                onPressed: () async {
                  final inputMac = _manualMacController.text.trim();
                  if (inputMac.isEmpty) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Masukkan MAC Address printer terlebih dahulu.'),
                        backgroundColor: Colors.orange,
                      ),
                    );
                    return;
                  }

                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Menghubungkan ke $inputMac...')),
                  );

                  final ok = await provider.connect(inputMac, deviceName: 'Printer Manual ($inputMac)');
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).hideCurrentSnackBar();
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text(
                          ok ? '✅ Terhubung ke printer $inputMac!' : '⚠️ Gagal terhubung ke $inputMac',
                        ),
                        backgroundColor: ok ? const Color(0xFF2E7D32) : Colors.red,
                      ),
                    );
                  }
                },
                child: const Text('Sambungkan', style: TextStyle(fontWeight: FontWeight.bold)),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
