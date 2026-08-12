import 'package:flutter/material.dart';

/// Standard app palette — kept close to the reference React Native app so
/// the two look like the same product.
class AppColors {
  static const primary = Color(0xFF1F4E79);
  static const primaryLight = Color(0xFF2E75B6);
  static const emergency = Color(0xFFB91C1C);
  static const emergencyBg = Color(0xFFFEE2E2);
  static const background = Color(0xFFF8FAFC);
  static const surface = Colors.white;
  static const border = Color(0xFFE2E8F0);
  static const textPrimary = Color(0xFF1E293B);
  static const textBody = Color(0xFF334155);
  static const textMuted = Color(0xFF64748B);
  static const textFaint = Color(0xFF94A3B8);
  static const chipBg = Color(0xFFDCE6F1);
}

/// High-contrast palette used exclusively by Senior Citizen Mode screens.
/// Deliberately distinct from [AppColors] — not just a font-size bump on
/// top of the standard theme.
class SeniorColors {
  static const background = Colors.black;
  static const surface = Color(0xFF111111);
  static const text = Colors.white;
  static const accent = Color(0xFFFFD60A); // high-visibility yellow
  static const emergency = Color(0xFFFF453A);
  static const safe = Color(0xFF30D158);
}

ThemeData buildAppTheme() {
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      primary: AppColors.primary,
      error: AppColors.emergency,
    ),
    scaffoldBackgroundColor: AppColors.background,
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.primary,
      foregroundColor: Colors.white,
      elevation: 0,
      centerTitle: false,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(vertical: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    cardTheme: CardThemeData(
      color: Colors.white,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: AppColors.border),
      ),
    ),
  );
  return base;
}
