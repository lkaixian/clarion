import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../providers/locale_provider.dart';
import '../providers/theme_provider.dart';
import '../theme/app_theme.dart';
import 'edit_profile_screen.dart';
import '../widgets/common.dart';

/// App preferences: language and theme, each in its own boxed section.
/// Reachable from the pre-login screen too, so it never shows (or lets
/// anyone change) the backend address -- that is a build-time setting.
class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  /// Turns Senior Citizen Mode on/off from within an authenticated session.
  /// `_AuthGate` swaps Home/SeniorHome reactively, but underneath this pushed
  /// route -- popping to root makes the swap visible straight away.
  Future<void> _setSeniorMode(BuildContext context, bool value) async {
    final auth = context.read<AuthProvider>();
    final navigator = Navigator.of(context);
    await auth.setPrefersSeniorMode(value);
    navigator.popUntil((route) => route.isFirst);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final localeProvider = context.watch<LocaleProvider>();
    final themeProvider = context.watch<ThemeProvider>();
    final auth = context.watch<AuthProvider>();

    return Scaffold(
      appBar: AppBar(title: Text(l10n.settingsTitle)),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (auth.isAuthenticated) ...[
              if (auth.user?.patientId != null) ...[
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () => context.pushScreen(const EditProfileScreen()),
                    icon: const Icon(Icons.person_outline),
                    label: Text(l10n.editProfileTitle),
                    style: OutlinedButton.styleFrom(
                      backgroundColor: context.palette.chipBg,
                      foregroundColor: context.palette.primary,
                      padding: const EdgeInsets.all(16),
                      side: BorderSide.none,
                    ),
                  ),
                ),
                const SizedBox(height: 16),
              ],
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: context.palette.chipBg,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(l10n.seniorModeToggleLabel,
                              style: TextStyle(
                                  fontSize: 14, fontWeight: FontWeight.w600, color: context.palette.primary)),
                          const SizedBox(height: 4),
                          Text(l10n.seniorModeToggleDesc,
                              style: TextStyle(fontSize: 12, color: context.palette.textMuted, height: 1.3)),
                        ],
                      ),
                    ),
                    const SizedBox(width: 12),
                    Switch(
                      value: auth.prefersSeniorMode,
                      onChanged: (v) => _setSeniorMode(context, v),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
            ],
            _SettingsBox(
              icon: Icons.language,
              title: l10n.languageLabel,
              child: Wrap(
                spacing: 8,
                runSpacing: 8,
                children: kSupportedLocales.map((locale) {
                  final selected = locale.languageCode == localeProvider.locale.languageCode;
                  return ChoiceChip(
                    label: Text(kLocaleDisplayNames[locale.languageCode] ?? locale.languageCode),
                    selected: selected,
                    onSelected: (_) => localeProvider.setLocale(locale),
                    selectedColor: context.palette.primary,
                    // The default tick is near-black, which disappears on the light-theme primary.
                    checkmarkColor:
                        Theme.of(context).brightness == Brightness.dark ? null : Colors.white,
                    labelStyle: TextStyle(color: selected ? Colors.white : context.palette.textBody),
                  );
                }).toList(),
              ),
            ),
            const SizedBox(height: 16),
            _SettingsBox(
              icon: Icons.palette_outlined,
              title: l10n.themeLabel,
              child: SizedBox(
                width: double.infinity,
                child: SegmentedButton<ThemeMode>(
                  segments: [
                    ButtonSegment(value: ThemeMode.light, label: _SegmentLabel(l10n.themeModeLight)),
                    ButtonSegment(value: ThemeMode.dark, label: _SegmentLabel(l10n.themeModeDark)),
                    ButtonSegment(value: ThemeMode.system, label: _SegmentLabel(l10n.themeModeSystem)),
                  ],
                  showSelectedIcon: false,
                  selected: {themeProvider.themeMode},
                  onSelectionChanged: (selection) =>
                      context.read<ThemeProvider>().setThemeMode(selection.first),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// A bordered box with an icon + title header, as in "— Language 🌐 —".
class _SettingsBox extends StatelessWidget {
  const _SettingsBox({required this.icon, required this.title, required this.child});

  final IconData icon;
  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: context.palette.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: context.palette.border, width: 1.5),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(icon, size: 20, color: context.palette.primary),
            const SizedBox(width: 8),
            Text(title,
                style: TextStyle(
                    fontSize: 15, fontWeight: FontWeight.w700, color: context.palette.primary)),
          ]),
          const SizedBox(height: 4),
          Divider(color: context.palette.border),
          const SizedBox(height: 8),
          child,
        ],
      ),
    );
  }
}

/// One-line label that shrinks instead of breaking a word across lines.
class _SegmentLabel extends StatelessWidget {
  const _SegmentLabel(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => FittedBox(
        fit: BoxFit.scaleDown,
        child: Text(text, maxLines: 1, softWrap: false),
      );
}
