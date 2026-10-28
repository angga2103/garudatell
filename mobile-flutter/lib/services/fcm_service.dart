import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'storage_service.dart';

/// Layanan Push Notification (Firebase Cloud Messaging) & Sinkronisasi Token
class FcmService {
  static FcmService? _instance;
  bool _isInitialized = false;
  String? _fcmToken;

  FcmService._();

  static FcmService get instance {
    _instance ??= FcmService._();
    return _instance!;
  }

  String? get fcmToken => _fcmToken;
  bool get isInitialized => _isInitialized;

  /// Inisialisasi Firebase secara aman tanpa memicu crash jika google-services.json belum diisi
  Future<void> init() async {
    try {
      await Firebase.initializeApp();
      _isInitialized = true;
      debugPrint('[FCM] Firebase successfully initialized.');

      // Minta izin notifikasi (Android 13+ & iOS)
      final messaging = FirebaseMessaging.instance;
      final settings = await messaging.requestPermission(
        alert: true,
        badge: true,
        sound: true,
      );

      debugPrint('[FCM] Notification authorization status: ${settings.authorizationStatus}');

      // Ambil FCM Token perangkat
      _fcmToken = await messaging.getToken();
      if (_fcmToken != null) {
        debugPrint('[FCM] Token retrieved: $_fcmToken');
        await StorageService.instance.setString('gt_fcm_token', _fcmToken!);
      }

      // Dengarkan jika ada token refresh
      messaging.onTokenRefresh.listen((newToken) async {
        _fcmToken = newToken;
        await StorageService.instance.setString('gt_fcm_token', newToken);
        debugPrint('[FCM] Token refreshed: $newToken');
      });

      // Penanganan pesan saat aplikasi di foreground
      FirebaseMessaging.onMessage.listen((RemoteMessage message) {
        debugPrint('[FCM] Received message in foreground: ${message.notification?.title}');
      });
    } catch (e) {
      debugPrint('[FCM] Notice: Firebase initialization skipped or google-services.json not yet added ($e). App will run normally.');
    }
  }

  /// Menyuntikkan (Inject) FCM_TOKEN ke dalam sesi WebView
  /// Agar backend Flask GarudaTel / iPay dapat mengenali token perangkat pengguna
  Future<void> injectTokenToWeb(WebViewController controller) async {
    final token = _fcmToken ?? await StorageService.instance.getString('gt_fcm_token');
    if (token == null || token.isEmpty) return;

    try {
      final jsCode = """
        (function() {
          window.GARUDATEL_FCM_TOKEN = '$token';
          if (typeof window.onReceiveFcmToken === 'function') {
            window.onReceiveFcmToken('$token');
          }
          window.dispatchEvent(new CustomEvent('fcm_token_ready', { detail: { token: '$token' } }));
          console.log('[GarudaTel Bridge] FCM Token injected to web session.');
        })();
      """;

      await controller.runJavaScript(jsCode);
    } catch (e) {
      debugPrint('[FCM] Error injecting token to web: $e');
    }
  }
}
