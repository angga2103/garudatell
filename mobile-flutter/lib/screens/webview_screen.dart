import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
import '../config/app_config.dart';
import '../services/fcm_service.dart';
import '../services/print_service.dart';
import '../services/storage_service.dart';
import 'printer_settings_screen.dart';

class WebViewScreen extends StatefulWidget {
  const WebViewScreen({super.key});

  @override
  State<WebViewScreen> createState() => _WebViewScreenState();
}

class _WebViewScreenState extends State<WebViewScreen> {
  late final WebViewController _controller;
  int _loadingProgress = 0;
  bool _hasError = false;
  String _errorMessage = '';

  @override
  void initState() {
    super.initState();
    _initWebView();
  }

  void _initWebView() {
    _hasError = false;

    final WebViewController controller = WebViewController();

    controller
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Colors.white)
      ..setUserAgent("Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 IPAY_NATIVE_APP/1.0")
      ..setNavigationDelegate(
        NavigationDelegate(
          onProgress: (int progress) {
            setState(() {
              _loadingProgress = progress;
            });
          },
          onPageStarted: (String url) {
            setState(() {
              _hasError = false;
            });
            controller.runJavaScript("""
              window.isIpayNative = true;
              window.isIpayNativeApp = true;
              window.isGarudaTelNativeApp = true;
            """);
          },
          onNavigationRequest: (NavigationRequest request) {
            final url = request.url;
            debugPrint('[WebView Navigation] Requested URL: $url');

            // 1. CEGAT URL CETAK RAWBT THERMAL DARI WEB
            if (url.startsWith('rawbt:')) {
              _handleRawBtUrl(url);
              return NavigationDecision.prevent;
            }

            // 2. CEGAT URL WHATSAPP (whatsapp://, wa.me, api.whatsapp.com)
            if (url.startsWith('whatsapp:') ||
                url.contains('wa.me/') ||
                url.contains('api.whatsapp.com/')) {
              _handleWhatsAppUrl(url);
              return NavigationDecision.prevent;
            }

            // 3. CEGAT PROTOKOL TELEPON, SMS, DAN EMAIL
            if (url.startsWith('tel:') || url.startsWith('sms:') || url.startsWith('mailto:')) {
              _handleIntentUrl(url);
              return NavigationDecision.prevent;
            }

            return NavigationDecision.navigate;
          },
          onPageFinished: (String url) async {
            // Suntikkan flag & polyfill pencetakan serta CSS pembersih native
            await controller.runJavaScript("""
              (function() {
                window.isIpayNative = true;
                window.isIpayNativeApp = true;
                window.isGarudaTelNativeApp = true;
                window.appVersion = '${AppConfig.appVersion}';
                
                // Polyfill global openPrinterSettings
                window.openPrinterSettings = function() {
                  if (window.PrintChannel) {
                    window.PrintChannel.postMessage(JSON.stringify({ type: 'open_settings' }));
                  }
                };

                // 1. Injeksi CSS Khusus Native
                if (!document.getElementById('ipay-native-css')) {
                  var style = document.createElement('style');
                  style.id = 'ipay-native-css';
                  style.textContent = '#pwa-install-banner, .pwa-install-banner, .btn-bluetooth-print { display: none !important; }';
                  document.head.appendChild(style);
                }

                // 2. Bersihkan elemen banner PWA jika ada di DOM
                var pwaBanner = document.getElementById('pwa-install-banner');
                if (pwaBanner) pwaBanner.remove();

                // 3. Update Indikator Halaman Profil
                var pwa = document.querySelectorAll('#profil-status-pwa');
                pwa.forEach(function(el) {
                  if (!el.dataset.fixed) {
                    el.dataset.fixed = 'true';
                    el.innerHTML = '<span style="color:#008779; background:#e6f7f5; padding:3px 8px; border-radius:12px; font-size:11px; font-weight:800;">✅ Terpasang (APK Native)</span>';
                  }
                });
                var notif = document.querySelectorAll('#profil-status-notif');
                notif.forEach(function(el) {
                  if (!el.dataset.fixed) {
                    el.dataset.fixed = 'true';
                    el.innerHTML = '<span style="color:#008779; background:#e6f7f5; padding:3px 8px; border-radius:12px; font-size:11px; font-weight:800;">✅ Aktif (FCM Native)</span>';
                  }
                });

                // 4. Polyfill window.print()
                window.print = function() {
                  try {
                    var rcpt = document.getElementById('receiptModal') ||
                               document.querySelector('.receipt-paper') ||
                               document.querySelector('.thermal-box-wrapper') ||
                               document.querySelector('.invoice-container') ||
                               document.querySelector('#receiptContent') ||
                               document.body;
                    var text = rcpt ? (rcpt.innerText || rcpt.textContent) : document.body.innerText;
                    if (window.PrintChannel) {
                      window.PrintChannel.postMessage(JSON.stringify({
                        type: 'receipt',
                        raw_text: text,
                        title: document.title || 'Struk Transaksi'
                      }));
                    }
                  } catch(e) {
                    console.error('[IPAY Print Bridge] Error:', e);
                  }
                };

                // 5. Polyfill window.open() khusus link WhatsApp
                var _origOpen = window.open;
                window.open = function(url, target, features) {
                  if (url && (url.indexOf('whatsapp.com') !== -1 || url.indexOf('wa.me') !== -1 || url.indexOf('whatsapp:') !== -1)) {
                    window.location.href = url;
                    return null;
                  }
                  return _origOpen ? _origOpen.apply(this, arguments) : null;
                };
              })();
            """);

            // Injeksi FCM Token ke sesi Web
            await FcmService.instance.injectTokenToWeb(controller);
          },
          onWebResourceError: (WebResourceError error) {
            // Abaikan error minor (seperti favicon atau analytics gagal)
            if (error.isForMainFrame ?? true) {
              setState(() {
                _hasError = true;
                _errorMessage = error.description;
              });
            }
          },
        ),
      )
      // JEMBATAN 1: PRINTER CHANNEL (STRUK TRANSAKSI & PENGATURAN)
      ..addJavaScriptChannel(
        AppConfig.printChannelName,
        onMessageReceived: (JavaScriptMessage message) async {
          debugPrint('[PrintChannel] Message received: ${message.message}');
          if (!mounted) return;
          try {
            final decoded = jsonDecode(message.message);
            if (decoded is Map && (decoded['type'] == 'open_settings' || decoded['action'] == 'open_settings')) {
              Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => const PrinterSettingsScreen()),
              );
              return;
            }
          } catch (_) {}

          final payload = StrukPayload.fromMessage(message.message);

          // Cek apakah ada printer yang tersimpan di MAC Address
          final savedMac = await StorageService.instance.getSavedPrinterMac();
          if (savedMac != null && savedMac.isNotEmpty) {
            final success = await PrintService.instance.printThermal(payload, targetMac: savedMac);
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(success ? '✅ Struk berhasil dicetak ke printer!' : '⚠️ Gagal mencetak ke printer tersimpan. Membuka dialog pilihan printer...'),
                  backgroundColor: success ? AppConfig.primaryTeal : Colors.orange,
                  duration: const Duration(seconds: 2),
                ),
              );
            }
            if (success) return;
          }

          if (mounted) {
            PrintService.instance.showPrintSelectionModal(context, payload);
          }
        },
      )
      // JEMBATAN 2: STORAGE CHANNEL (PENYIMPANAN PERMANEN NATIVE)
      ..addJavaScriptChannel(
        AppConfig.storageChannelName,
        onMessageReceived: (JavaScriptMessage message) {
          debugPrint('[StorageChannel] Message received: ${message.message}');
          StorageService.instance.handleMessage(message.message, _controller);
        },
      );

    // Konfigurasi Khusus Android WebKit untuk mengelola Cookie Session Flask secara persisten
    if (controller.platform is AndroidWebViewController) {
      final androidController = controller.platform as AndroidWebViewController;
      // Aktifkan DOM Storage (localStorage & sessionStorage)
      androidController.setMediaPlaybackRequiresUserGesture(false);

      // Konfigurasi Cookie Manager Android agar sesi login Flask tidak mudah logout
      final cookieManager = WebViewCookieManager();
      // Izinkan cookies
      cookieManager.setCookie(
        const WebViewCookie(
          name: 'gt_native_client',
          value: 'true',
          domain: 'ipay.my.id',
          path: '/',
        ),
      );
    }

    // Muat URL Produksi
    controller.loadRequest(Uri.parse(AppConfig.webUrl));
    _controller = controller;
  }

  void _handleRawBtUrl(String url) {
    try {
      String base64Data = '';
      const prefix = 'rawbt:data:text/plain;base64,';
      if (url.startsWith(prefix)) {
        base64Data = url.substring(prefix.length);
      } else if (url.contains('base64,')) {
        base64Data = url.split('base64,').last;
      }
      if (base64Data.isNotEmpty) {
        final decodedBytes = base64.decode(base64Data);
        final rawText = utf8.decode(decodedBytes, allowMalformed: true);
        final payload = StrukPayload.fromPlainText(rawText);
        if (mounted) {
          PrintService.instance.showPrintSelectionModal(context, payload);
        }
      }
    } catch (e) {
      debugPrint('[RawBT Intercept] Error: $e');
    }
  }

  Future<void> _handleWhatsAppUrl(String url) async {
    try {
      debugPrint('[WhatsApp Launcher] Opening: $url');
      final uri = Uri.tryParse(url);
      if (uri != null && await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
        return;
      }

      // Fallback: Jika whatsapp:// tidak dapat dibuka, konversi ke link API web resmi WhatsApp
      if (url.startsWith('whatsapp://send?')) {
        final query = url.replaceFirst('whatsapp://send?', '');
        final fallbackUrl = 'https://api.whatsapp.com/send?$query';
        final fallbackUri = Uri.tryParse(fallbackUrl);
        if (fallbackUri != null && await canLaunchUrl(fallbackUri)) {
          await launchUrl(fallbackUri, mode: LaunchMode.externalApplication);
          return;
        }
      }

      // Jika WhatsApp tidak terpasang sama sekali
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Aplikasi WhatsApp tidak ditemukan di ponsel Anda.'),
            backgroundColor: Colors.orange,
            duration: Duration(seconds: 3),
          ),
        );
      }
    } catch (e) {
      debugPrint('[WhatsApp Launcher] Error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Gagal membuka WhatsApp: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  Future<void> _handleIntentUrl(String url) async {
    try {
      final uri = Uri.tryParse(url);
      if (uri != null && await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      }
    } catch (e) {
      debugPrint('[Intent Launcher] Error: $e');
    }
  }

  Future<bool> _handleWillPop() async {
    if (await _controller.canGoBack()) {
      await _controller.goBack();
      return false; // Jangan keluar aplikasi, mundur di web history
    }

    if (!mounted) return true;

    // Tampilkan konfirmasi keluar aplikasi
    final shouldExit = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Keluar Aplikasi?', style: TextStyle(fontWeight: FontWeight.w800)),
        content: const Text('Apakah Anda yakin ingin menutup aplikasi IPAY?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Batal', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: AppConfig.primaryTeal,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Ya, Keluar', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );

    return shouldExit ?? false;
  }

  @override
  Widget build(BuildContext context) {
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: const SystemUiOverlayStyle(
        statusBarColor: AppConfig.primaryTeal,
        statusBarIconBrightness: Brightness.light,
        systemNavigationBarColor: Colors.white,
        systemNavigationBarIconBrightness: Brightness.dark,
      ),
      child: PopScope(
        canPop: false,
        onPopInvokedWithResult: (didPop, result) async {
          if (didPop) return;
          final canExit = await _handleWillPop();
          if (canExit && context.mounted) {
            SystemNavigator.pop();
          }
        },
        child: Scaffold(
          backgroundColor: Colors.white,
          body: SafeArea(
            top: true,
            bottom: false,
            child: Stack(
              children: [
                // WEBVIEW LAYAR PENUH (NATIVE FULLSCREEN TANPA DUPLIKASI APPBAR)
                if (!_hasError)
                  WebViewWidget(controller: _controller)
                else
                  _buildErrorView(),

                // LINEAR PROGRESS BAR SAAT MEMUAT HALAMAN
                if (_loadingProgress < 100 && !_hasError)
                  Positioned(
                    top: 0,
                    left: 0,
                    right: 0,
                    child: LinearProgressIndicator(
                      value: _loadingProgress / 100.0,
                      backgroundColor: Colors.transparent,
                      valueColor: const AlwaysStoppedAnimation<Color>(AppConfig.primaryTeal),
                      minHeight: 2.5,
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildErrorView() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 80,
              height: 80,
              decoration: BoxDecoration(
                color: AppConfig.primaryLight,
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.wifi_off_rounded, size: 40, color: AppConfig.primaryTeal),
            ),
            const SizedBox(height: 20),
            const Text(
              'Gagal Memuat Halaman',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: AppConfig.textDark),
            ),
            const SizedBox(height: 8),
            Text(
              'Periksa koneksi internet Anda dan coba muat ulang portal iPay.\n($_errorMessage)',
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 12, color: AppConfig.textMuted),
            ),
            const SizedBox(height: 24),
            ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: AppConfig.primaryTeal,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Coba Lagi', style: TextStyle(fontWeight: FontWeight.w700)),
              onPressed: () {
                _controller.reload();
              },
            ),
          ],
        ),
      ),
    );
  }
}
