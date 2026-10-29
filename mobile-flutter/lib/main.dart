import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'config/app_config.dart';
import 'screens/webview_screen.dart';
import 'screens/printer_settings_screen.dart';
import 'services/fcm_service.dart';
import 'services/storage_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Set system UI style (status bar transparan)
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.dark,
    ),
  );

  // Inisialisasi Layanan Native Storage & FCM secara paralel agar first-paint instan
  Future.wait([
    StorageService.instance.init(),
    FcmService.instance.init(),
  ]);

  runApp(const GarudaTelApp());
}

class GarudaTelApp extends StatelessWidget {
  const GarudaTelApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: AppConfig.appName,
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        primaryColor: AppConfig.primaryTeal,
        colorScheme: ColorScheme.fromSeed(
          seedColor: AppConfig.primaryTeal,
          primary: AppConfig.primaryTeal,
          secondary: AppConfig.accent,
          surface: Colors.white,
        ),
        scaffoldBackgroundColor: Colors.white,
        fontFamily: 'Roboto',
      ),
      home: const WebViewScreen(),
      routes: {
        '/web': (_) => const WebViewScreen(),
        '/printer': (_) => const PrinterSettingsScreen(),
      },
      onGenerateRoute: (settings) {
        if (settings.name == '/printer' || (settings.name?.contains('printer') ?? false)) {
          return MaterialPageRoute(builder: (_) => const PrinterSettingsScreen());
        }
        return MaterialPageRoute(builder: (_) => const WebViewScreen());
      },
    );
  }
}
