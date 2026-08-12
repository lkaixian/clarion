import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../l10n/generated/app_localizations.dart';
import '../../providers/locale_provider.dart';
import '../../theme/app_theme.dart';

/// A single-purpose, senior-styled language switcher — deliberately NOT a
/// route into the full [SettingsScreen], which bundles the language
/// picker together with the API-base-URL editor (not appropriate to show
/// a senior user: "no scope pickers, no secondary reading" is this mode's
/// whole design principle). This screen does exactly one thing: pick a
/// language. Tapping a language applies it immediately and returns to the
/// senior home hub — one decision, one tap, done.
class SeniorLanguageScreen extends StatelessWidget {
  const SeniorLanguageScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final localeProvider = context.watch<LocaleProvider>();

    return Scaffold(
      backgroundColor: SeniorColors.background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            children: [
              Row(
                children: [
                  IconButton(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.arrow_back, color: Colors.white, size: 32),
                  ),
                  Expanded(
                    child: Text(
                      l10n.seniorLanguageTitle,
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: Colors.white, fontSize: 26, fontWeight: FontWeight.w800),
                    ),
                  ),
                  const SizedBox(width: 48),
                ],
              ),
              const SizedBox(height: 24),
              Expanded(
                child: ListView.separated(
                  itemCount: kSupportedLocales.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 16),
                  itemBuilder: (context, index) {
                    final locale = kSupportedLocales[index];
                    final selected = locale.languageCode == localeProvider.locale.languageCode;
                    return _LanguageTile(
                      label: kLocaleDisplayNames[locale.languageCode] ?? locale.languageCode,
                      selected: selected,
                      onTap: () async {
                        await localeProvider.setLocale(locale);
                        if (context.mounted) Navigator.of(context).pop();
                      },
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _LanguageTile extends StatelessWidget {
  const _LanguageTile({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 84,
      child: Material(
        color: selected ? SeniorColors.accent : SeniorColors.surface,
        borderRadius: BorderRadius.circular(20),
        child: InkWell(
          borderRadius: BorderRadius.circular(20),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    label,
                    style: TextStyle(
                      color: selected ? Colors.black : Colors.white,
                      fontSize: 26,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
                if (selected) const Icon(Icons.check_circle, color: Colors.black, size: 32),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
