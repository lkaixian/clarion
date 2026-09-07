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

  // Added for the audit-log redesign's privacy-sensitivity indicator (see
  // AuditLogScreen) — a routine/attention/critical 3-tier accent system
  // that fits alongside the existing primary/emergency pair rather than
  // introducing an unrelated palette. Reused wherever else a similar
  // "routine vs. needs-a-look" signal is useful.
  static const success = Color(0xFF15803D);
  static const successBg = Color(0xFFDCFCE7);
  static const attention = Color(0xFFB45309);
  static const attentionBg = Color(0xFFFEF3C7);
}

/// Dark counterpart to [AppColors], for the standard (non-senior) app when
/// the user picks Dark or System-default in Settings (see [ThemeProvider]).
/// Same "re-tuned, not blind-inverted" approach as [SeniorColorsLight] is to
/// [SeniorColors] — each semantic colour keeps its hue family but is
/// re-tuned for legibility/contrast against a dark surface rather than a
/// naive channel inversion of [AppColors].
class AppColorsDark {
  static const primary = Color(0xFF5B9BD5); // lighter blue than AppColors.primary, for contrast on dark surfaces
  static const primaryLight = Color(0xFF8FC1E8);
  static const emergency = Color(0xFFEF5350); // softer red than AppColors.emergency, avoids vibrating on black
  static const emergencyBg = Color(0xFF3B1616);
  static const background = Color(0xFF0F172A);
  static const surface = Color(0xFF1E293B);
  static const border = Color(0xFF334155);
  static const textPrimary = Color(0xFFF1F5F9);
  static const textBody = Color(0xFFCBD5E1);
  static const textMuted = Color(0xFF94A3B8);
  static const textFaint = Color(0xFF64748B);
  static const chipBg = Color(0xFF243B55);

  static const success = Color(0xFF4ADE80);
  static const successBg = Color(0xFF14331F);
  static const attention = Color(0xFFFBBF24);
  static const attentionBg = Color(0xFF3A2A0A);
}

/// Theme-dependent slice of the app palette, resolved at runtime from the
/// active [Brightness] via the [PaletteX.palette] extension below.
///
/// Why this exists: [AppColors] / [AppColorsDark] are `static const` holders,
/// so a widget that writes `AppColors.textPrimary` directly is frozen to the
/// light value regardless of the active theme — which was the dark-mode bug
/// (dark slate text on a dark background). Screens read
/// `context.palette.textPrimary` instead and get the right colour per theme.
/// [AppColors] / [AppColorsDark] stay as-is for the theme builders and any
/// genuinely fixed-brand usage (e.g. white-on-red emergency buttons).
@immutable
class PaletteData {
  const PaletteData({
    required this.primary,
    required this.primaryLight,
    required this.emergency,
    required this.emergencyBg,
    required this.background,
    required this.surface,
    required this.border,
    required this.textPrimary,
    required this.textBody,
    required this.textMuted,
    required this.textFaint,
    required this.chipBg,
    required this.success,
    required this.successBg,
    required this.attention,
    required this.attentionBg,
  });

  final Color primary;
  final Color primaryLight;
  final Color emergency;
  final Color emergencyBg;
  final Color background;
  final Color surface;
  final Color border;
  final Color textPrimary;
  final Color textBody;
  final Color textMuted;
  final Color textFaint;
  final Color chipBg;
  final Color success;
  final Color successBg;
  final Color attention;
  final Color attentionBg;
}

const _lightPalette = PaletteData(
  primary: AppColors.primary,
  primaryLight: AppColors.primaryLight,
  emergency: AppColors.emergency,
  emergencyBg: AppColors.emergencyBg,
  background: AppColors.background,
  surface: AppColors.surface,
  border: AppColors.border,
  textPrimary: AppColors.textPrimary,
  textBody: AppColors.textBody,
  textMuted: AppColors.textMuted,
  textFaint: AppColors.textFaint,
  chipBg: AppColors.chipBg,
  success: AppColors.success,
  successBg: AppColors.successBg,
  attention: AppColors.attention,
  attentionBg: AppColors.attentionBg,
);

const _darkPalette = PaletteData(
  primary: AppColorsDark.primary,
  primaryLight: AppColorsDark.primaryLight,
  emergency: AppColorsDark.emergency,
  emergencyBg: AppColorsDark.emergencyBg,
  background: AppColorsDark.background,
  surface: AppColorsDark.surface,
  border: AppColorsDark.border,
  textPrimary: AppColorsDark.textPrimary,
  textBody: AppColorsDark.textBody,
  textMuted: AppColorsDark.textMuted,
  textFaint: AppColorsDark.textFaint,
  chipBg: AppColorsDark.chipBg,
  success: AppColorsDark.success,
  successBg: AppColorsDark.successBg,
  attention: AppColorsDark.attention,
  attentionBg: AppColorsDark.attentionBg,
);

/// `context.palette.<member>` — the theme-aware replacement for
/// `AppColors.<member>` in the standard (non-senior) app.
extension PaletteX on BuildContext {
  PaletteData get palette => Theme.of(this).brightness == Brightness.dark
      ? _darkPalette
      : _lightPalette;
}

/// High-contrast palette used exclusively by Senior Citizen Mode screens.
/// Deliberately distinct from [AppColors] — not just a font-size bump on
/// top of the standard theme. This is the (default) dark variant — see
/// [SeniorColorsLight] for the alternative a user can opt into via
/// `AuthProvider.seniorIsDark`.
class SeniorColors {
  static const background = Colors.black;
  static const surface = Color(0xFF111111);
  static const text = Colors.white;
  static const accent = Color(0xFFFFD60A); // high-visibility yellow
  static const emergency = Color(0xFFFF453A);
  static const safe = Color(0xFF30D158);
}

/// Light counterpart to [SeniorColors], for senior users who find a bright
/// background easier to read (glare/cataracts affect people in both
/// directions — there's no single "correct" contrast direction for every
/// older adult). Deliberately not a blind inversion of [SeniorColors]:
/// each colour keeps the same hue family as its dark-mode counterpart but
/// is re-tuned for legible contrast against a light background rather than
/// black (e.g. the accent yellow becomes a dark gold — pale yellow text is
/// close to unreadable on white, whereas the dark-mode yellow reads fine on
/// black).
class SeniorColorsLight {
  static const background = Color(0xFFF5F5F0); // warm off-white, less glare than pure white
  static const surface = Colors.white;
  static const text = Color(0xFF1A1A1A); // near-black, high-contrast on the light background
  static const accent = Color(0xFF8A6D00); // dark gold — same hue as the dark-mode yellow, darkened for contrast on white
  static const emergency = Color(0xFFB91C1C); // darker red than dark-mode's FF453A, for contrast on white
  static const safe = Color(0xFF15803D); // darker green than dark-mode's 30D158, for contrast on white
}

/// Builds the standard app's light `ThemeData` — was the app's only theme
/// before dark-mode support was added; kept as its own function (rather than
/// folding into [buildAppTheme]) so `MaterialApp.theme` / `.darkMode` call
/// sites read as plainly as the two things they are.
ThemeData buildAppLightTheme() {
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.light,
    colorScheme: ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      primary: AppColors.primary,
      error: AppColors.emergency,
    ),
    scaffoldBackgroundColor: AppColors.background,
    // Explicit text/icon defaults so any widget that *doesn't* go through
    // context.palette still lands on a readable colour (belt-and-braces for
    // the dark-mode sweep — see PaletteData).
    textTheme: ThemeData.light().textTheme.apply(
          bodyColor: AppColors.textBody,
          displayColor: AppColors.textPrimary,
        ),
    iconTheme: const IconThemeData(color: AppColors.textPrimary),
    listTileTheme: const ListTileThemeData(
      textColor: AppColors.textPrimary,
      iconColor: AppColors.textMuted,
    ),
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
}

/// Dark counterpart to [buildAppLightTheme], using [AppColorsDark] for every
/// semantic colour that [buildAppLightTheme] draws from [AppColors]. Kept
/// structurally identical to its light counterpart (same theme properties
/// set, same shapes/paddings/text styles) so switching themes only changes
/// colour, never layout.
ThemeData buildAppDarkTheme() {
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: ColorScheme.fromSeed(
      seedColor: AppColorsDark.primary,
      brightness: Brightness.dark,
      primary: AppColorsDark.primary,
      error: AppColorsDark.emergency,
      surface: AppColorsDark.surface,
    ),
    scaffoldBackgroundColor: AppColorsDark.background,
    // Explicit text/icon defaults so any widget that *doesn't* go through
    // context.palette still degrades to a readable colour on the dark surface
    // rather than the frozen light-mode slate — see PaletteData.
    textTheme: ThemeData.dark().textTheme.apply(
          bodyColor: AppColorsDark.textBody,
          displayColor: AppColorsDark.textPrimary,
        ),
    iconTheme: const IconThemeData(color: AppColorsDark.textPrimary),
    listTileTheme: const ListTileThemeData(
      textColor: AppColorsDark.textPrimary,
      iconColor: AppColorsDark.textMuted,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColorsDark.surface,
      foregroundColor: Colors.white,
      elevation: 0,
      centerTitle: false,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColorsDark.surface,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColorsDark.border),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColorsDark.primary,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(vertical: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    cardTheme: CardThemeData(
      color: AppColorsDark.surface,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: AppColorsDark.border),
      ),
    ),
  );
}
