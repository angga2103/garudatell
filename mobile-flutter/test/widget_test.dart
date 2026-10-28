import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/services/print_service.dart';
import 'package:mobile_flutter/services/storage_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('AppConfig Tests', () {
    test('Configures production URL and Channel names correctly', () {
      expect(AppConfig.webUrl, equals('https://ipay.my.id'));
      expect(AppConfig.printChannelName, equals('PrintChannel'));
      expect(AppConfig.storageChannelName, equals('StorageChannel'));
    });
  });

  group('StorageService Unit Tests', () {
    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    test('Stores and retrieves key-value pairs', () async {
      final storage = StorageService.instance;
      await storage.setString('test_key', 'test_value');
      final val = await storage.getString('test_key');
      expect(val, equals('test_value'));
    });

    test('Stores and retrieves saved printer MAC address', () async {
      final storage = StorageService.instance;
      await storage.setSavedPrinterMac('00:11:22:33:44:55');
      final mac = await storage.getSavedPrinterMac();
      expect(mac, equals('00:11:22:33:44:55'));
    });

    test('Handles JSON message from StorageChannel correctly', () async {
      final storage = StorageService.instance;
      const jsonMsg = '{"action":"set","key":"agent_pref","value":"dark_mode"}';
      await storage.handleMessage(jsonMsg, null);

      final val = await storage.getString('agent_pref');
      expect(val, equals('dark_mode'));
    });
  });

  group('PrintService & StrukPayload Unit Tests', () {
    test('Parses JSON Struk from Web correctly', () {
      const jsonStruk = '{"storeName":"KONTER GARUDA","refId":"GT-100234","product":"Pulsa Telkomsel 10K","amount":"Rp 12.000","sn":"1234567890","status":"BERHASIL"}';
      final payload = StrukPayload.fromMessage(jsonStruk);

      expect(payload.storeName, equals('KONTER GARUDA'));
      expect(payload.refId, equals('GT-100234'));
      expect(payload.productName, equals('Pulsa Telkomsel 10K'));
      expect(payload.amount, equals('Rp 12.000'));
      expect(payload.sn, equals('1234567890'));
      expect(payload.status, equals('BERHASIL'));
    });

    test('Parses Plain Text ESC-POS Struk from Web', () {
      const plainText = 'STRUK TRANSAKSI GARUDATEL\\nNo: GT-999\\nTotal: Rp 50.000';
      final payload = StrukPayload.fromMessage(plainText);

      expect(payload.rawText, equals(plainText));
      expect(payload.storeName, isNull);
    });

    test('Generates non-empty ESC/POS bytes from StrukPayload', () {
      final payload = StrukPayload(
        rawText: 'Sample text',
        storeName: 'GARUDATEL CELL',
        refId: 'TRX-12345',
        productName: 'Indosat 10GB',
        amount: 'Rp 25.000',
        sn: '9988776655',
      );

      final bytes = PrintService.instance.generateEscPosBytes(payload);
      expect(bytes, isNotEmpty);
      expect(bytes.length, greaterThan(20));
    });
  });
}
