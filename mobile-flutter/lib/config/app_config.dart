import 'package:flutter/material.dart';

class AppConfig {
  /// URL Produksi Web PPOB GarudaTel / iPay
  static const String webUrl = 'https://ipay.my.id';

  /// Nama JavaScript Channel untuk Jembatan Komunikasi
  static const String printChannelName = 'PrintChannel';
  static const String storageChannelName = 'StorageChannel';

  /// Identitas Aplikasi
  static const String appName = 'IPAY';
  static const String appVersion = '1.0.4';

  /// Warna Khas GarudaTel (taste_guidelines.md)
  static const Color primaryTeal = Color(0xFF008779);
  static const Color primaryDark = Color(0xFF006B5F);
  static const Color primaryLight = Color(0xFFE6F7F5);
  static const Color backgroundSoft = Color(0xFFF5F8FA);
  static const Color textDark = Color(0xFF1E293B);
  static const Color textMuted = Color(0xFF64748B);
  static const Color accent = Color(0xFF00A896);
}
