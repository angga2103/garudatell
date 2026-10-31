import 'package:esc_pos_utils_plus/esc_pos_utils_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:print_bluetooth_thermal/print_bluetooth_thermal.dart';
import '../services/printer_service.dart';
import '../services/storage_service.dart';

/// State Management untuk Bluetooth Thermal POS Printer (Provider / ChangeNotifier)
class PrinterProvider extends ChangeNotifier {
  final PrinterService _service = PrinterService.instance;

  bool _isConnected = false;
  String? _connectedMac;
  String? _connectedName;
  List<BluetoothInfo> _availableDevices = [];
  bool _isScanning = false;
  PaperSize _paperSize = PaperSize.mm58;
  String? _errorMessage;

  // Getters
  bool get isConnected => _isConnected;
  String? get connectedMac => _connectedMac;
  String? get connectedName => _connectedName;
  List<BluetoothInfo> get availableDevices => _availableDevices;
  bool get isScanning => _isScanning;
  PaperSize get paperSize => _paperSize;
  String? get errorMessage => _errorMessage;

  /// Inisialisasi awal: Muat printer tersimpan dan cek status koneksi
  Future<void> init() async {
    _paperSize = _service.paperSize;
    _connectedMac = await _service.getSavedMac();
    _connectedName = await StorageService.instance.getSavedPrinterName();

    await checkConnection();
    await scanDevices();
  }

  /// Memeriksa status koneksi aktif secara real-time
  Future<bool> checkConnection() async {
    try {
      _isConnected = await _service.checkConnectionStatus();
      if (!_isConnected) {
        _connectedName = null;
      }
      notifyListeners();
      return _isConnected;
    } catch (e) {
      _isConnected = false;
      notifyListeners();
      return false;
    }
  }

  /// Pindai ulang daftar printer Bluetooth yang sudah dipasangkan (paired)
  Future<void> scanDevices() async {
    _isScanning = true;
    _errorMessage = null;
    notifyListeners();

    try {
      _availableDevices = await _service.getPairedDevices();
      _isConnected = await _service.checkConnectionStatus();

      // Cocokkan nama printer yang sedang terhubung bila ada
      if (_connectedMac != null) {
        final match = _availableDevices.where((d) => d.macAdress.toUpperCase() == _connectedMac!.toUpperCase());
        if (match.isNotEmpty) {
          _connectedName = match.first.name;
        }
      }
    } catch (e) {
      _errorMessage = 'Gagal memindai perangkat Bluetooth: $e';
      debugPrint('[PrinterProvider] scanDevices error: $e');
    } finally {
      _isScanning = false;
      notifyListeners();
    }
  }

  /// Menghubungkan ke printer via MAC Address
  Future<bool> connect(String mac, {String? deviceName}) async {
    _errorMessage = null;
    _isScanning = true;
    notifyListeners();

    try {
      final success = await _service.connect(mac);
      _isConnected = success;

      if (success) {
        _connectedMac = mac.toUpperCase();
        _connectedName = deviceName ?? _findDeviceName(mac);
        if (_connectedName != null) {
          await StorageService.instance.setSavedPrinterName(_connectedName!);
        }
        _errorMessage = null;
      } else {
        _errorMessage = 'Tidak dapat terhubung ke printer ($mac). Pastikan printer menyala dan dalam jangkauan.';
      }

      return success;
    } catch (e) {
      _isConnected = false;
      _errorMessage = 'Error koneksi printer: $e';
      return false;
    } finally {
      _isScanning = false;
      notifyListeners();
    }
  }

  /// Memutuskan koneksi printer yang sedang aktif
  Future<void> disconnect() async {
    try {
      await _service.disconnect();
      _isConnected = false;
      _connectedMac = null;
      _connectedName = null;
      notifyListeners();
    } catch (e) {
      _errorMessage = 'Gagal memutuskan koneksi: $e';
      notifyListeners();
    }
  }

  /// Mengubah ukuran kertas cetak (58mm vs 80mm)
  Future<void> setPaperSize(PaperSize size) async {
    _paperSize = size;
    await _service.setPaperSize(size);
    notifyListeners();
  }

  /// Mencetak struk pengujian (Test Print)
  Future<bool> testPrint({Map<String, dynamic>? storeInfo}) async {
    _errorMessage = null;
    try {
      final success = await _service.printTestReceipt(storeInfo: storeInfo);
      if (!success) {
        _errorMessage = 'Gagal mengirim data cetak ke printer. Pastikan printer terhubung.';
      }
      notifyListeners();
      return success;
    } catch (e) {
      _errorMessage = 'Error test print: $e';
      notifyListeners();
      return false;
    }
  }

  String? _findDeviceName(String mac) {
    for (final device in _availableDevices) {
      if (device.macAdress.toUpperCase() == mac.toUpperCase()) {
        return device.name;
      }
    }
    return null;
  }
}
