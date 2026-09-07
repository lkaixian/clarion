import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config/app_config.dart';
import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../providers/locale_provider.dart';
import '../providers/theme_provider.dart';
import '../theme/app_theme.dart';
import 'edit_profile_screen.dart';

/// Runtime-editable API base URL (persisted with shared_preferences) plus
/// the app's language picker.
///
/// The API URL editor exists so that once a Cloudflare tunnel (a
/// `trycloudflare.com` subdomain) is running, the app can be pointed at it —
/// and re-pointed every time the tunnel restarts with a new URL — without
/// a rebuild.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: context.read<AppConfig>().baseUrl);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final l10n = AppLocalizations.of(context);
    final config = context.read<AppConfig>();
    await config.setBaseUrl(_controller.text);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l10n.savedSnack(config.baseUrl))),
      );
    }
  }

  Future<void> _reset() async {
    final l10n = AppLocalizations.of(context);
    final config = context.read<AppConfig>();
    await config.resetToDefault();
    _controller.text = config.baseUrl;
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l10n.resetSnack)));
    }
  }

  /// Turns Senior Citizen Mode on/off from within an authenticated session
  /// (previously only reachable from the pre-login LoginScreen — you'd
  /// have to sign out first to turn it on). `_AuthGate` in app.dart
  /// already reactively swaps `HomeScreen`/`SeniorHomeScreen` based on
  /// `AuthProvider.prefersSeniorMode` via `Consumer<AuthProvider>`, but
  /// that swap happens *underneath* whatever route is currently pushed on
  /// top of it (this Settings screen) — it's applied to the widget tree
  /// immediately, but not visible until the user navigates back to the
  /// root route. Popping back to root here makes the swap visible right
  /// away instead of leaving the user looking at this screen with no
  /// visible feedback that anything changed.
  Future<void> _setSeniorMode(bool value) async {
    final auth = context.read<AuthProvider>();
    await auth.setPrefersSeniorMode(value);
    if (!mounted) return;
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final config = context.watch<AppConfig>();
    final localeProvider = context.watch<LocaleProvider>();
    final themeProvider = context.watch<ThemeProvider>();
    final auth = context.watch<AuthProvider>();

    return Scaffold(
      appBar: AppBar(title: Text(l10n.apiSettingsTitle)),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (auth.isAuthenticated) ...[
              if (auth.user?.role == 'patient') ...[
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () => Navigator.of(context)
                        .push(MaterialPageRoute(builder: (_) => const EditProfileScreen())),
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
                              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: context.palette.primary)),
                          const SizedBox(height: 4),
                          Text(l10n.seniorModeToggleDesc,
                              style: TextStyle(fontSize: 12, color: context.palette.textMuted, height: 1.3)),
                        ],
                      ),
                    ),
                    const SizedBox(width: 12),
                    Switch(
                      value: auth.prefersSeniorMode,
                      onChanged: _setSeniorMode,
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 28),
            ],
            Text(l10n.languageLabel,
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: context.palette.textPrimary)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: kSupportedLocales.map((locale) {
                final selected = locale.languageCode == localeProvider.locale.languageCode;
                return ChoiceChip(
                  label: Text(kLocaleDisplayNames[locale.languageCode] ?? locale.languageCode),
                  selected: selected,
                  onSelected: (_) => localeProvider.setLocale(locale),
                  selectedColor: context.palette.primary,
                  labelStyle: TextStyle(color: selected ? Colors.white : context.palette.textBody),
                );
              }).toList(),
            ),
            const SizedBox(height: 28),
            // Unlike the Senior Mode toggle above (gated on auth.isAuthenticated
            // — it only makes sense once there's a signed-in session to apply
            // it to), Theme is an app-wide display preference like Language,
            // so it must be reachable straight from the pre-login LoginScreen's
            // settings gear too — hence it lives down here, ungated.
            Text(l10n.themeLabel,
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: context.palette.textPrimary)),
            const SizedBox(height: 8),
            SegmentedButton<ThemeMode>(
              segments: [
                ButtonSegment(value: ThemeMode.light, label: Text(l10n.themeModeLight)),
                ButtonSegment(value: ThemeMode.dark, label: Text(l10n.themeModeDark)),
                ButtonSegment(value: ThemeMode.system, label: Text(l10n.themeModeSystem)),
              ],
              selected: {themeProvider.themeMode},
              onSelectionChanged: (selection) =>
                  context.read<ThemeProvider>().setThemeMode(selection.first),
            ),
            const SizedBox(height: 28),
            Text(l10n.backendUrlLabel,
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: context.palette.textPrimary)),
            const SizedBox(height: 8),
            Text(
              l10n.backendUrlDesc,
              style: TextStyle(fontSize: 12, color: context.palette.textMuted, height: 1.4),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _controller,
              keyboardType: TextInputType.url,
              autocorrect: false,
              decoration: InputDecoration(
                labelText: l10n.apiBaseUrlFieldLabel,
                hintText: 'https://xxxx.trycloudflare.com',
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton(onPressed: _save, child: Text(l10n.save)),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: OutlinedButton(onPressed: _reset, child: Text(l10n.resetToDefault)),
                ),
              ],
            ),
            const SizedBox(height: 24),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(color: context.palette.chipBg, borderRadius: BorderRadius.circular(10)),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(l10n.currentlyActive(config.baseUrl),
                      style: TextStyle(fontSize: 12, color: context.palette.primary, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Text(l10n.compileTimeDefault(config.compileTimeDefault),
                      style: TextStyle(fontSize: 12, color: context.palette.textMuted)),
                  Text(
                    config.isOverridden ? l10n.usingOverride : l10n.usingDefault,
                    style: TextStyle(fontSize: 12, color: context.palette.textMuted),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
            Text(
              l10n.emulatorNote,
              style: TextStyle(fontSize: 11, color: context.palette.textFaint, height: 1.4),
            ),
          ],
        ),
      ),
    );
  }
}
