import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config/app_config.dart';
import '../l10n/generated/app_localizations.dart';
import '../providers/locale_provider.dart';
import '../theme/app_theme.dart';

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

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final config = context.watch<AppConfig>();
    final localeProvider = context.watch<LocaleProvider>();

    return Scaffold(
      appBar: AppBar(title: Text(l10n.apiSettingsTitle)),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(l10n.languageLabel,
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.textPrimary)),
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
                  selectedColor: AppColors.primary,
                  labelStyle: TextStyle(color: selected ? Colors.white : AppColors.textBody),
                );
              }).toList(),
            ),
            const SizedBox(height: 28),
            Text(l10n.backendUrlLabel,
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.textPrimary)),
            const SizedBox(height: 8),
            Text(
              l10n.backendUrlDesc,
              style: const TextStyle(fontSize: 12, color: AppColors.textMuted, height: 1.4),
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
              decoration: BoxDecoration(color: AppColors.chipBg, borderRadius: BorderRadius.circular(10)),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(l10n.currentlyActive(config.baseUrl),
                      style: const TextStyle(fontSize: 12, color: AppColors.primary, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Text(l10n.compileTimeDefault(config.compileTimeDefault),
                      style: const TextStyle(fontSize: 12, color: AppColors.textMuted)),
                  Text(
                    config.isOverridden ? l10n.usingOverride : l10n.usingDefault,
                    style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
            Text(
              l10n.emulatorNote,
              style: const TextStyle(fontSize: 11, color: AppColors.textFaint, height: 1.4),
            ),
          ],
        ),
      ),
    );
  }
}
