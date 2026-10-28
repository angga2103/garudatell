import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:webview_flutter/webview_flutter.dart';

/// Layanan Penyimpanan Permanen (StorageChannel Bridge)
/// Menghubungkan frontend Web iPay dengan SharedPreferences Native Android
/// Mencegah data preferensi agen dan cache terhapus otomatis oleh browser.
class StorageService {
  static StorageService? _instance;
  SharedPreferences? _prefs;

  StorageService._();

  static StorageService get instance {
    _instance ??= StorageService._();
    return _instance!;
  }

  Future<void> init() async {
    _prefs ??= await SharedPreferences.getInstance();
  }

  /// Menangani pesan yang dikirim dari JavaScript via:
  /// StorageChannel.postMessage(JSON.stringify({ action: "set", key: "...", value: "..." }))
  Future<void> handleMessage(String rawMessage, WebViewController? controller) async {
    await init();
    try {
      final dynamic decoded = jsonDecode(rawMessage);
      if (decoded is! Map<String, dynamic>) {
        // Fallback jika dikirim format string biasa "key=value"
        _handlePlainText(rawMessage);
        return;
      }

      final String action = decoded['action']?.toString().toLowerCase() ?? 'set';
      final String? key = decoded['key']?.toString();
      final dynamic value = decoded['value'];
      final String? callback = decoded['callback']?.toString();

      switch (action) {
        case 'set':
          if (key != null) {
            final strValue = value is String ? value : jsonEncode(value);
            await _prefs?.setString(key, strValue);
            debugPrint('[StorageChannel] Saved: $key');
            if (callback != null && controller != null) {
              await controller.runJavaScript("$callback(true, ${jsonEncode(key)});");
            }
          }
          break;

        case 'get':
          if (key != null && callback != null && controller != null) {
            final storedVal = _prefs?.getString(key);
            debugPrint('[StorageChannel] Get: $key => $storedVal');
            await controller.runJavaScript("$callback(${jsonEncode(storedVal)}, ${jsonEncode(key)});");
          }
          break;

        case 'remove':
          if (key != null) {
            await _prefs?.remove(key);
            debugPrint('[StorageChannel] Removed: $key');
            if (callback != null && controller != null) {
              await controller.runJavaScript("$callback(true, ${jsonEncode(key)});");
            }
          }
          break;

        case 'clear':
          await _prefs?.clear();
          debugPrint('[StorageChannel] Cleared all preferences');
          if (callback != null && controller != null) {
            await controller.runJavaScript("$callback(true);");
          }
          break;

        case 'getall':
          if (callback != null && controller != null) {
            final allKeys = _prefs?.getKeys() ?? {};
            final Map<String, dynamic> allData = {};
            for (final k in allKeys) {
              allData[k] = _prefs?.get(k);
            }
            await controller.runJavaScript("$callback(${jsonEncode(allData)});");
          }
          break;
      }
    } catch (e) {
      debugPrint('[StorageChannel] Error parsing message: $e | Raw: $rawMessage');
    }
  }

  void _handlePlainText(String text) {
    if (text.contains('=')) {
      final parts = text.split('=');
      if (parts.length >= 2) {
        final k = parts[0].trim();
        final v = parts.sublist(1).join('=').trim();
        _prefs?.setString(k, v);
      }
    }
  }

  // Helper Langsung dari Flutter
  Future<String?> getString(String key) async {
    await init();
    return _prefs?.getString(key);
  }

  Future<void> setString(String key, String value) async {
    await init();
    await _prefs?.setString(key, value);
  }

  Future<int> getInt(String key, {int defaultValue = 0}) async {
    await init();
    return _prefs?.getInt(key) ?? defaultValue;
  }

  Future<void> setInt(String key, int value) async {
    await init();
    await _prefs?.setInt(key, value);
  }

  // --- Konfigurasi Printer Kasir Native ---
  Future<String?> getSavedPrinterMac() async {
    return getString('gt_saved_printer_mac');
  }

  Future<void> setSavedPrinterMac(String mac) async {
    return setString('gt_saved_printer_mac', mac);
  }

  Future<String?> getSavedPrinterName() async {
    return getString('gt_saved_printer_name');
  }

  Future<void> setSavedPrinterName(String name) async {
    return setString('gt_saved_printer_name', name);
  }

  /// Metode Cetak: 'direct' (Bluetooth Langsung), 'rawbt' (RawBT App), 'pdf' (Sistem PDF/Laser)
  Future<String> getPrintMethod() async {
    return (await getString('gt_print_method')) ?? 'direct';
  }

  Future<void> setPrintMethod(String method) async {
    return setString('gt_print_method', method);
  }

  /// Panjang Karakter Per Baris: 32 (58mm) atau 48 (80mm)
  Future<int> getPaperWidth() async {
    return getInt('gt_paper_width', defaultValue: 32);
  }

  Future<void> setPaperWidth(int width) async {
    return setInt('gt_paper_width', width);
  }

  /// Jumlah baris kosong di akhir struk (Feed Spacing)
  Future<int> getFeedMargin() async {
    return getInt('gt_feed_margin', defaultValue: 3);
  }

  Future<void> setFeedMargin(int margin) async {
    return setInt('gt_feed_margin', margin);
  }

  // Header & Footer Struk
  Future<String> getHeader1() async {
    return (await getString('gt_header_1')) ?? 'GARUDATEL IPAY';
  }

  Future<void> setHeader1(String value) async {
    return setString('gt_header_1', value);
  }

  Future<String> getHeader2() async {
    return (await getString('gt_header_2')) ?? 'Pusat Pembayaran PPOB Terpercaya';
  }

  Future<void> setHeader2(String value) async {
    return setString('gt_header_2', value);
  }

  Future<String> getHeader3() async {
    return (await getString('gt_header_3')) ?? '';
  }

  Future<void> setHeader3(String value) async {
    return setString('gt_header_3', value);
  }

  Future<String> getFooter() async {
    return (await getString('gt_footer')) ?? 'Terima kasih atas kunjungan Anda';
  }

  Future<void> setFooter(String value) async {
    return setString('gt_footer', value);
  }
}
